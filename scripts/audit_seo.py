#!/usr/bin/env python3
"""Audit the static site's metadata, article semantics, resources and link graph.

Run: python3 scripts/audit_seo.py
Uses only Python's standard library. This does not measure rankings or CWV.
"""
from collections import Counter, deque
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
import json
import posixpath
import sys
import csv
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DOMAIN = 'v2raydown.com'
VOID = set('area base br col embed hr img input link meta param source track wbr'.split())

@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return ''.join(x.text() if isinstance(x, Node) else x for x in self.children)

    def walk(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.walk(tag)

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()

class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('document')
        self.stack = [self.root]
        self.errors = []

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            self.errors.append('Invalid closing tag: ' + tag)
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def first(root, tag, key=None, value=None):
    return next((n for n in root.walk(tag)
                 if key is None or n.attrs.get(key) == value), None)


def audit():
    domain = (ROOT / 'CNAME').read_text().strip()
    base = 'https://' + domain + '/'
    pages = {}
    errors, warnings = [], []
    if domain != PRODUCTION_DOMAIN:
        errors.append('CNAME must preserve the production domain: ' + PRODUCTION_DOMAIN)
    for path in sorted(ROOT.glob('*.html')):
        parser = Tree()
        parser.feed(path.read_text())
        if len(parser.stack) != 1:
            parser.errors.append('Unclosed HTML tags')
        errors.extend(path.name + ': ' + e for e in parser.errors)
        pages[path.name] = parser.root

    def issue(name, message):
        errors.append(name + ': ' + message)

    def target(href, source):
        url = urlsplit(urljoin(base + source, href))
        if url.netloc != domain or url.scheme not in ('http', 'https'):
            return None
        name = posixpath.normpath(unquote(url.path)).lstrip('/')
        if name in ('', '.'):
            name = 'index.html'
        return name, unquote(url.fragment)

    graph = {name: set() for name in pages}
    incoming = {name: set() for name in pages}
    mapping = ROOT / 'seo' / 'keyword-map.csv'
    optimized_pages = set()
    if mapping.exists():
        with mapping.open(encoding='utf-8-sig', newline='') as handle:
            optimized_pages = {row['file'] for row in csv.DictReader(handle)}
    titles, descriptions = [], []
    schemas_total = references = article_count = new_count = faq_count = 0
    deferred_icons = runtime_articles = unused_icon_css = 0
    for name, root in pages.items():
        for tag in ('title', 'h1', 'main', 'header', 'footer'):
            if len(list(root.walk(tag))) != 1:
                issue(name, 'Expected exactly one ' + tag)
        title = first(root, 'title').text().strip()
        desc_node = first(root, 'meta', 'name', 'description')
        desc = desc_node.attrs.get('content', '') if desc_node else ''
        titles.append(title)
        descriptions.append(desc)
        if not title or not desc:
            issue(name, 'Missing title or description')
        canonical = first(root, 'link', 'rel', 'canonical')
        expected = base + ('' if name == 'index.html' else name)
        if canonical is None or canonical.attrs.get('href') != expected:
            issue(name, 'Canonical differs from expected URL')
        robots = first(root, 'meta', 'name', 'robots')
        if robots and 'noindex' in robots.attrs.get('content', '').lower():
            issue(name, 'Unexpected noindex')
        ids = Counter(n.attrs['id'] for n in root.walk() if n.attrs.get('id'))
        if any(n > 1 for n in ids.values()):
            issue(name, 'Duplicate HTML IDs')
        for node in root.walk():
            attr = 'href' if node.tag in ('a', 'link') else 'src' if node.tag in ('img', 'script') else None
            href = node.attrs.get(attr) if attr else None
            if not href:
                continue
            resolved = target(href, name)
            if resolved is None:
                continue
            destination, fragment = resolved
            references += 1
            if not (ROOT / destination).is_file():
                issue(name, 'Missing local resource: ' + href)
                continue
            if fragment and destination in pages:
                dest_ids = {n.attrs.get('id') for n in pages[destination].walk()}
                tab_alias = destination == 'download.html' and fragment in ('windows', 'macos', 'android', 'linux', 'ios')
                if fragment not in dest_ids and not tab_alias:
                    issue(name, 'Missing fragment: ' + href)
            if node.tag == 'a' and destination in pages:
                graph[name].add(destination)
                if destination != name:
                    incoming[destination].add(name)
        data = []
        for node in root.walk('script'):
            if node.attrs.get('type') == 'application/ld+json':
                try:
                    data.append(json.loads(node.text()))
                except json.JSONDecodeError as exc:
                    issue(name, 'Invalid JSON-LD: ' + str(exc))
            if 'unpkg.com/lucide' in node.attrs.get('src', '') and 'defer' in node.attrs:
                deferred_icons += 1
        schemas_total += len(data)
        fa_elements = [n for n in root.walk() if any(c.startswith('fa-') for c in n.attrs.get('class', '').split())]
        fa_css = [n for n in root.walk('link') if 'font-awesome' in n.attrs.get('href', '')]
        if fa_css and not fa_elements:
            unused_icon_css += 1
            issue(name, 'Unused Font Awesome stylesheet')
        schema = next((d for d in data if d.get('@type') == 'Article'), None)
        if schema:
            article_count += 1
            if schema.get('headline') != first(root, 'h1').text().strip():
                issue(name, 'Article headline does not match H1')
            if schema.get('description') != desc:
                issue(name, 'Article description does not match meta')
            if schema.get('url') != expected:
                issue(name, 'Article URL does not match canonical')
            byline = next((n for n in root.walk() if n.has_class('article-byline')), None)
            author = schema.get('author', {})
            author_link = first(byline, 'a') if byline else None
            if author_link is None or author_link.text().strip() != author.get('name'):
                issue(name, 'Visible byline does not match Article author')
            elif urljoin(base + name, author_link.attrs.get('href', '')) != author.get('url'):
                issue(name, 'Author profile URL mismatch')
            breadcrumb = next((d for d in data if d.get('@type') == 'BreadcrumbList'), None)
            nav = first(root, 'nav', 'aria-label', '面包屑')
            visible = [n.text().strip() for n in nav.walk() if n.tag == 'a' or n.attrs.get('aria-current') == 'page'] if nav else []
            if not breadcrumb or visible != [r['name'] for r in breadcrumb.get('itemListElement', [])]:
                issue(name, 'Visible breadcrumb and JSON-LD differ')
            else:
                for item in breadcrumb['itemListElement']:
                    resolved = target(item['item'], name)
                    if not resolved or resolved[0] not in pages:
                        issue(name, 'Breadcrumb target is not a local page')
                        continue
                    dest, frag = resolved
                    if frag and not any(n.attrs.get('id') == frag for n in pages[dest].walk()):
                        issue(name, 'Breadcrumb category fragment missing')
            if name in optimized_pages:
                new_count += 1
                if any(n.attrs.get('src') == 'https://cdn.tailwindcss.com' for n in root.walk('script')):
                    runtime_articles += 1
                    issue(name, 'New article still uses browser-side utility compiler')
                content = next(n for n in root.walk() if n.has_class('article-content'))
                child_elements = [n for n in content.children if isinstance(n, Node)]
                if not child_elements or not child_elements[0].has_class('quick-answer'):
                    issue(name, 'Direct answer is not before the TOC')
                faq = next((n for n in content.walk() if n.attrs.get('id') == 'article-faq'), None)
                questions = list(faq.walk('h3')) if faq else []
                if len(questions) < 2:
                    issue(name, 'Missing useful follow-up Q&A')
                faq_count += len(questions)
                if any(d.get('@type') == 'FAQPage' for d in data):
                    issue(name, 'Article unnecessarily declares FAQPage')
                toc = next((n for n in content.walk('nav') if n.has_class('article-toc')), None)
                if not toc:
                    issue(name, 'Missing article TOC')
                else:
                    for link in toc.walk('a'):
                        frag = link.attrs.get('href', '').lstrip('#')
                        heading = next((h for h in content.walk('h2') if h.attrs.get('id') == frag), None)
                        if heading is None or link.text().strip() != heading.text().strip():
                            issue(name, 'TOC text and heading differ: ' + frag)
        collection = next((d for d in data if d.get('@type') == 'CollectionPage' and d.get('mainEntity', {}).get('@type') == 'ItemList'), None)
        if collection:
            cards = [n.attrs['href'] for n in root.walk('a') if 'data-tutorial-card' in n.attrs]
            listed = collection['mainEntity']['itemListElement']
            if len(cards) != collection['mainEntity'].get('numberOfItems') or set(cards) != {urlsplit(r['url']).path.lstrip('/') for r in listed}:
                issue(name, 'Catalogue HTML and ItemList differ')

    for label, values in [('title', titles), ('description', descriptions)]:
        for value, count in Counter(values).items():
            if value and count > 1:
                errors.append('Duplicate ' + label + ': ' + value)
    queue, depths = deque(['index.html']), {'index.html': 0}
    while queue:
        source = queue.popleft()
        for dest in graph[source]:
            if dest not in depths:
                depths[dest] = depths[source] + 1
                queue.append(dest)
    for name in pages:
        if name not in depths:
            issue(name, 'Unreachable from homepage')
    sitemap = ET.parse(ROOT / 'sitemap.xml')
    urls = [n.text for n in sitemap.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    expected_urls = {base + ('' if n == 'index.html' else n) for n in pages}
    if len(urls) != len(set(urls)) or set(urls) != expected_urls:
        errors.append('Sitemap does not exactly match canonical HTML pages')
    if 'Sitemap: ' + base + 'sitemap.xml' not in (ROOT / 'robots.txt').read_text():
        errors.append('robots.txt sitemap URL mismatch')
    remaining = [n for n, root in pages.items() if any(s.attrs.get('src') == 'https://cdn.tailwindcss.com' for s in root.walk('script'))]
    if remaining:
        warnings.append('Legacy pages still using browser-side utility CSS compiler: ' + str(len(remaining)))
    warnings.append('Live redirects, response headers, Google-selected canonical, rankings and field CWV were not measured.')
    return {'pages': len(pages), 'articles': article_count, 'optimized_new_articles': new_count,
            'visible_follow_up_answers': faq_count, 'local_references': references,
            'json_ld_blocks': schemas_total, 'sitemap_urls': len(urls),
            'max_click_depth': max(depths.values()), 'orphan_pages': len(pages)-len(depths),
            'article_runtime_compiler_dependencies': runtime_articles,
            'deferred_icon_scripts': deferred_icons, 'unused_icon_stylesheets': unused_icon_css,
            'inbound_links': {n:len(incoming[n]) for n in sorted(pages) if n.startswith('blog-')},
            'errors': errors, 'warnings': warnings}

if __name__ == '__main__':
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(bool(result['errors']))
