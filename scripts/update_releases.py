#!/usr/bin/env python3
"""Sync official Latest releases into static download links. Python stdlib only."""
import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PROXY = 'https://github.v2raydown.com/'
PROJECTS = {'v2rayN': '2dust/v2rayN', 'v2rayNG': '2dust/v2rayNG', 'V2rayU': 'yanue/V2rayU'}
GENERATED = ('data/releases.json', 'download.html', 'sitemap.xml')
ARCH_ORDER = {'arm64-v8a': 0, 'universal': 1, 'armeabi-v7a': 2, 'x86_64': 3, 'x86': 4,
              'arm64': 0, 'x64': 1, 'loong64': 2, 'riscv64': 3}


class ReleaseError(ValueError):
    pass


def fetch_release(repo, token=''):
    """Use GitHub's Latest designation, never the highest-looking version number."""
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10',
               'User-Agent': 'v2rayndown-release-sync'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request('https://api.github.com/repos/' + repo + '/releases/latest', headers=headers)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ReleaseError(f'{repo}: GitHub API HTTP {error.code}; existing files were kept') from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            if attempt == 2:
                raise ReleaseError(f'{repo}: could not read GitHub release data; existing files were kept') from error
        time.sleep(2 ** attempt)


def classify_asset(project, name, tag):
    arch = {'64': 'x64', 'x64': 'x64', '86': 'x86', 'x86': 'x86', 'arm64': 'arm64'}
    if project == 'v2rayN':
        match = re.fullmatch(r'v2rayN-windows-(64|x64|86|x86|arm64)(-desktop)?\.zip', name, re.I)
        if match:
            return {'platform': 'windows', 'architecture': arch[match[1].lower()], 'format': 'ZIP',
                    'variant': 'desktop' if match[2] else '标准包'}
        match = re.fullmatch(r'v2rayN-macos-(64|x64|arm64)\.(dmg|zip)', name, re.I)
        if match:
            return {'platform': 'macos', 'architecture': arch[match[1].lower()],
                    'format': match[2].upper(), 'variant': ''}
        match = re.fullmatch(r'v2rayN-linux-(?:rhel-)?(64|x64|arm64|loong64|riscv64)\.(deb|rpm|zip)', name, re.I)
        if match:
            return {'platform': 'linux', 'architecture': arch.get(match[1].lower(), match[1].lower()),
                    'format': match[2].upper(), 'variant': ''}
    elif project == 'V2rayU':
        match = re.fullmatch(r'V2rayU-(64|x64|arm64)\.dmg', name, re.I)
        if match:
            return {'platform': 'macos', 'architecture': arch[match[1].lower()], 'format': 'DMG', 'variant': ''}
    elif project == 'v2rayNG':
        match = re.fullmatch(r'v2rayNG_(.+?)(-fdroid)?_(arm64-v8a|armeabi-v7a|universal|x86_64|x86)\.apk', name)
        if match and match[1] == tag.lstrip('vV'):
            return {'platform': 'android', 'architecture': match[3], 'format': 'APK',
                    'variant': 'F-Droid' if match[2] else 'GitHub'}
    return None


def normalise_release(project, raw):
    repo = PROJECTS[project]
    tag = raw.get('tag_name')
    if raw.get('draft') is not False or raw.get('prerelease') is not False or not isinstance(tag, str) or not tag:
        raise ReleaseError(f'{repo}: expected a published stable release')
    published = raw.get('published_at', '')
    try:
        datetime.fromisoformat(published.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        raise ReleaseError(f'{repo}: missing release publication date') from None
    release_url = raw.get('html_url', '')
    if release_url != 'https://github.com/' + repo + '/releases/tag/' + tag:
        # GitHub may encode slashes in a tag. Compare decoded paths, never another host.
        parsed = urlsplit(release_url)
        if parsed.scheme != 'https' or parsed.netloc != 'github.com' or unquote(parsed.path) != '/' + repo + '/releases/tag/' + tag or parsed.query or parsed.fragment:
            raise ReleaseError(f'{repo}: unexpected release URL')
    assets = []
    seen = set()
    for asset in raw.get('assets', []):
        name = asset.get('name', '')
        classification = classify_asset(project, name, tag)
        if not classification:
            continue
        original = asset.get('browser_download_url', '')
        parsed = urlsplit(original)
        expected = '/' + repo + '/releases/download/' + tag + '/' + name
        if parsed.scheme != 'https' or parsed.netloc != 'github.com' or unquote(parsed.path) != expected or parsed.query or parsed.fragment:
            raise ReleaseError(f'{repo}: unexpected asset URL for {name}')
        if name in seen or asset.get('state') != 'uploaded' or not isinstance(asset.get('size'), int) or asset['size'] <= 0:
            raise ReleaseError(f'{repo}: duplicate or incomplete asset {name}')
        seen.add(name)
        digest = asset.get('digest') or ''
        assets.append(dict(classification, name=name, url=original, size=asset['size'],
                           id=asset.get('id'), sha256=digest[7:] if re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest) else ''))
    required = {
        'v2rayN': {('windows', 'x64'), ('windows', 'arm64'), ('macos', 'x64'), ('macos', 'arm64'), ('linux', 'x64'), ('linux', 'arm64')},
        'v2rayNG': {('android', 'arm64-v8a'), ('android', 'universal')},
        'V2rayU': {('macos', 'arm64'), ('macos', 'x64')},
    }[project]
    present = {(a['platform'], a['architecture']) for a in assets if project != 'v2rayNG' or a['variant'] == 'GitHub'}
    if not required <= present:
        missing = ', '.join('/'.join(pair) for pair in sorted(required - present))
        raise ReleaseError(f'{repo}: latest release lacks required packages ({missing}); existing files were kept')
    return {'repository': repo, 'tag': tag, 'release_url': release_url, 'published_at': published,
            'assets': sorted(assets, key=lambda a: a['name'])}


def escape(value):
    return html.escape(str(value), quote=True)


def version(release):
    return 'v' + release['tag'].lstrip('vV')


def asset_label(asset):
    return {'arm64-v8a': 'ARM64 · 多数近期手机', 'universal': 'Universal · 通用包',
            'armeabi-v7a': 'ARMv7 · 旧设备', 'x86_64': 'x86_64 · 模拟器', 'x86': 'x86 · 32 位',
            'arm64': 'Apple Silicon / ARM64' if asset['platform'] == 'macos' else 'ARM64',
            'x64': 'Intel x64' if asset['platform'] == 'macos' else 'x64',
            'loong64': '龙芯 Loong64', 'riscv64': 'RISC-V 64'}[asset['architecture']]


def render_asset(project, release, asset):
    size = f"{asset['size'] / 1024 / 1024:.1f} MiB"
    label = asset_label(asset) + ' · ' + asset['format']
    if asset['variant'] and project != 'v2rayNG':
        label += ' · ' + asset['variant']
    checksum = ''
    if asset['sha256']:
        checksum = '<details class="release-checksum"><summary>SHA256 校验值</summary><code>' + asset['sha256'] + '</code><p>来源：GitHub 发布资产摘要，与本机计算值逐字符比较。</p></details>'
    aria = escape('加速下载 ' + project + ' ' + version(release) + ' ' + asset['name'])
    return f'''<li class="release-file"><div class="release-file-copy"><h4>{escape(label)}</h4><p>{escape(size)}</p><code>{escape(asset['name'])}</code></div><div class="release-file-actions"><a aria-label="{aria}" class="dl-button" data-release-download="{escape(project)}" href="{escape(PROXY + asset['url'])}" rel="noopener noreferrer" target="_blank">加速下载</a><a class="dl-link" href="{escape(asset['url'])}" rel="noopener noreferrer" target="_blank">GitHub 原始文件</a></div>{checksum}</li>'''


def render_files(project, release, assets, primary_count=None):
    assets = sorted(assets, key=lambda a: (ARCH_ORDER.get(a['architecture'], 5), {'DMG': 0, 'DEB': 0, 'RPM': 1, 'ZIP': 2, 'APK': 0}[a['format']], a['variant'] == 'desktop', a['name']))
    def listing(items):
        return '<ul class="release-files">' + ''.join(render_asset(project, release, a) for a in items) + '</ul>'
    if primary_count and len(assets) > primary_count:
        return listing(assets[:primary_count]) + f'<details class="release-more"><summary>其他架构（{len(assets) - primary_count} 个文件）</summary>' + listing(assets[primary_count:]) + '</details>'
    return listing(assets)


def card(project, release, heading, description, assets, tutorial, primary_count=None):
    date = release['published_at'][:10]
    return f'''<article class="dl-card release-card"><span class="dl-badge">最新稳定版 · {escape(version(release))}</span><h3>{escape(heading)}</h3><p>{escape(description)}</p><p class="release-meta">发布于 <time datetime="{escape(release['published_at'])}">{date}</time> · {escape(release['repository'])}</p>{render_files(project, release, assets, primary_count)}<div class="release-card-links"><a class="dl-link" href="{escape(release['release_url'])}" rel="noopener noreferrer" target="_blank">发布说明与全部文件</a><a class="dl-link" href="{tutorial}">安装与配置教程</a></div></article>'''


def render_platforms(data):
    projects = data['projects']
    n, ng, u = (projects[key] for key in PROJECTS)
    def select(release, platform, architecture=None, variant=None):
        return [a for a in release['assets'] if a['platform'] == platform and (architecture is None or a['architecture'] == architecture) and (variant is None or a['variant'] == variant)]
    def section(platform, title, body, note=''):
        extra = '<p class="dl-note">' + note + '</p>' if note else ''
        return f'<section aria-labelledby="platform-{platform}" class="platform-section" id="tab-{platform}" role="tabpanel" tabindex="0"><h2>{title}</h2>{body}{extra}</section>'
    win = '<div class="dl-grid">' + ''.join(card('v2rayN', n, heading, desc, select(n, 'windows', arch), 'blog-v2rayn-guide.html') for arch, heading, desc in [
        ('x64', 'v2rayN · Intel / AMD x64', '适用于 x64 架构 Windows 电脑。选择 ZIP 后完整解压到可写目录，再启动应用。'),
        ('arm64', 'v2rayN · Windows ARM64', '适用于 ARM 处理器的 Windows 设备。ARM64 与 x64 不同，请先核对系统类型。')]) + '</div>'
    if select(n, 'windows', 'x86'):
        win += '<details class="release-extra"><summary>32 位 Windows 安装包</summary>' + render_files('v2rayN', n, select(n, 'windows', 'x86')) + '</details>'
    mac = '<div class="dl-grid">' + card('V2rayU', u, 'V2rayU · macOS', '偏好菜单栏操作时可选择 V2rayU。Apple Silicon 选择 ARM64，Intel 芯片选择 x64。', select(u, 'macos'), 'blog-v2rayu-macos.html') + card('v2rayN', n, 'v2rayN · macOS', '需要跨平台配置管理时可选择 v2rayN。DMG 与 ZIP 按芯片架构分别下载。', select(n, 'macos'), 'blog-v2rayn-guide.html') + '</div>'
    android = '<div class="dl-grid">' + card('v2rayNG', ng, 'v2rayNG · GitHub 构建', '多数近期手机选择 ARM64；不确定架构时可选择 Universal。升级时保持与现有应用相同的构建渠道。', select(ng, 'android', variant='GitHub'), 'blog-v2rayng-android.html', 2)
    fdroid = select(ng, 'android', variant='F-Droid')
    if fdroid:
        android += card('v2rayNG', ng, 'v2rayNG · F-Droid 构建', '项目发布页提供的 F-Droid 变体。不同渠道可能使用不同签名，升级前先备份并核对现有安装来源。', fdroid, 'blog-v2rayng-android.html', 2)
    android += '</div>'
    linux = '<div class="dl-grid">' + ''.join(card('v2rayN', n, 'v2rayN · Linux ' + label, 'Debian / Ubuntu 选择 DEB，Fedora / RHEL 选择 RPM；便携使用可选择 ZIP。系统依赖以该版发布说明为准。', select(n, 'linux', arch), 'blog-v2ray-linux.html') for arch, label in [('x64', 'x64'), ('arm64', 'ARM64')]) + '</div>'
    other = select(n, 'linux', 'loong64') + select(n, 'linux', 'riscv64')
    if other:
        linux += '<details class="release-extra"><summary>龙芯 / RISC-V 安装包</summary>' + render_files('v2rayN', n, other) + '</details>'
    ios = '''<div class="dl-grid"><article class="dl-card"><span class="dl-badge">App Store · 第三方客户端</span><h3>Shadowrocket</h3><p>iPhone 与 iPad 通过 App Store 获取当前可用版本。它是独立第三方应用，不是 v2rayN 或 v2rayNG 的 iOS 版本；价格、地区、系统与协议要求以商店页面为准。</p><div class="dl-actions"><a class="dl-button" href="https://apps.apple.com/us/app/shadowrocket/id932747118" rel="noopener noreferrer" target="_blank">前往 App Store</a><a class="dl-link" href="clients.html">客户端选择说明</a></div></article><article class="dl-card"><span class="dl-badge">安装前确认</span><h3>核对协议与订阅格式</h3><p>iOS 应用通过商店安装，不使用桌面 ZIP 或 Android APK，也不提供 GitHub 安装包加速。先确认客户端支持的格式，再导入自己的有效配置并验证连接。</p><div class="dl-actions"><a class="dl-link" href="docs.html">了解订阅与配置</a><a class="dl-link" href="faq.html">连接问题排查</a></div></article></div>'''
    return '\n'.join([
        section('windows', 'Windows：v2rayN 直接下载', win, '标准包与 desktop 包是项目提供的不同界面构建。请核对所选版本的系统要求与依赖；不要混用 x64、ARM64 和 32 位包。'),
        section('macos', 'macOS：按芯片直接下载', mac, '在「关于本机」中确认芯片后下载。遇到兼容性或开发者验证提示时，核对发布者与系统要求，再按项目说明安装。'),
        section('android', 'Android：v2rayNG 直接下载', android, '安装后仍需有效的节点或订阅；允许系统 VPN 请求不会自动获得节点。'),
        section('linux', 'Linux：按架构与格式直接下载', linux),
        section('ios', 'iOS / iPadOS：通过 App Store 安装', ios)])


def replace_block(text, name, content):
    start, end = '<!-- RELEASES:' + name + ':START -->', '<!-- RELEASES:' + name + ':END -->'
    if text.count(start) != 1 or text.count(end) != 1:
        raise ReleaseError('Missing or duplicate generated block: ' + name)
    before, remainder = text.split(start)
    _, after = remainder.split(end)
    return before + start + '\n' + content + '\n' + end + after


def render_download(text, data):
    updated = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai'))
    date = updated.date().isoformat()
    text = replace_block(text, 'UPDATED', '<p class="page-meta">下载信息更新：<time datetime="' + escape(data['updated_at']) + '">' + updated.strftime('%Y 年 %m 月 %d 日 %H:%M') + '（北京时间）</time> · 每 6 小时检查最新稳定版</p>')
    text = replace_block(text, 'PLATFORMS', render_platforms(data))
    rows = ''.join('<tr><td>' + escape(key) + '</td><td>' + escape(version(release)) + '</td><td>' + release['published_at'][:10] + '</td><td><a class="dl-link" href="' + escape(release['release_url']) + '" rel="noopener noreferrer" target="_blank">发布说明</a></td></tr>' for key, release in data['projects'].items())
    text = replace_block(text, 'SUMMARY', '<p>按项目标记的 Latest 稳定版同步；预发布版不会自动替换下载按钮。下方日期是项目发布时间，页面顶部显示最近一次下载信息变更时间。所有加速按钮均保留对应的 GitHub 原始文件入口。</p><div aria-label="最新稳定版记录，可横向滚动" class="dl-table-wrap" role="region" tabindex="0"><table class="dl-table"><thead><tr><th scope="col">客户端</th><th scope="col">最新稳定版</th><th scope="col">发布日期</th><th scope="col">项目来源</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    def schema(match):
        value = json.loads(match[1])
        if value.get('@type') == 'CollectionPage':
            value['dateModified'] = date
        return '<script type="application/ld+json">\n' + json.dumps(value, ensure_ascii=False, indent=2) + '\n</script>'
    return re.sub(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', schema, text, flags=re.S)


def render_sitemap(text, data):
    date = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    pattern = r'(<url>\s*<loc>https://v2rayndown\.org/download\.html</loc>\s*<lastmod>)[^<]+(</lastmod>)'
    text, count = re.subn(pattern, lambda match: match[1] + date + match[2], text)
    if count != 1:
        raise ReleaseError('Could not find download.html in sitemap')
    return text


def sync(root=ROOT, api_dir=None, check=False, dry_run=False, now=None):
    root = Path(root)
    manifest_path = root / 'data/releases.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if check:
        if previous is None:
            raise ReleaseError('Missing data/releases.json')
        # Validate cached input as strictly as a fresh API response.
        for project, repo in PROJECTS.items():
            release = previous['projects'][project]
            raw = {'tag_name': release['tag'], 'draft': False, 'prerelease': False,
                   'published_at': release['published_at'], 'html_url': release['release_url'],
                   'assets': [dict(a, browser_download_url=a['url'], state='uploaded', digest='sha256:' + a['sha256'] if a['sha256'] else '') for a in release['assets']]}
            if release != normalise_release(project, raw):
                raise ReleaseError('Cached release metadata is inconsistent: ' + repo)
        data = previous
    else:
        projects = {}
        for project, repo in PROJECTS.items():
            raw = json.loads((Path(api_dir) / (project + '.json')).read_text()) if api_dir else fetch_release(repo, os.environ.get('GITHUB_TOKEN', ''))
            projects[project] = normalise_release(project, raw)
        if previous and previous.get('projects') == projects:
            data = previous
        else:
            data = {'schema_version': 1, 'updated_at': (now or datetime.now(timezone.utc)).isoformat(timespec='seconds').replace('+00:00', 'Z'), 'projects': projects}
    # Build and validate every output before touching any file.
    outputs = {
        'data/releases.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        'download.html': render_download((root / 'download.html').read_text(), data),
        'sitemap.xml': render_sitemap((root / 'sitemap.xml').read_text(), data),
    }
    changed = [name for name, content in outputs.items() if not (root / name).exists() or (root / name).read_text() != content]
    if check and changed:
        raise ReleaseError('Generated downloads are out of sync: ' + ', '.join(changed))
    if not check and not dry_run:
        for name in changed:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.tmp')
            temporary.write_text(outputs[name])
            temporary.replace(target)
    return changed, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Offline: validate committed data and generated HTML without writing files')
    parser.add_argument('--api-dir', type=Path, help='Use saved GitHub API responses (v2rayN.json, v2rayNG.json, V2rayU.json) instead of network')
    parser.add_argument('--dry-run', action='store_true', help='Fetch and validate but do not write files')
    args = parser.parse_args()
    if args.check and (args.api_dir or args.dry_run):
        parser.error('--check cannot be combined with --api-dir or --dry-run')
    try:
        changed, data = sync(api_dir=args.api_dir, check=args.check, dry_run=args.dry_run)
    except (ReleaseError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print('Release sync failed: ' + str(error), file=sys.stderr)
        return 1
    print('Latest stable: ' + ', '.join(key + ' ' + value['tag'] for key, value in data['projects'].items()))
    print(('Would update: ' if args.dry_run else 'Updated: ') + ', '.join(changed) if changed else 'No content changes; existing timestamps kept.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
