"""Offline regression checks for release selection and static-page synchronization."""
from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


SPEC = importlib.util.spec_from_file_location(
    'update_releases', Path(__file__).resolve().parents[1] / 'scripts/update_releases.py')
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs))


def release(project, tag, names):
    repo = updater.PROJECTS[project]
    return {
        'tag_name': tag, 'draft': False, 'prerelease': False,
        'html_url': f'https://github.com/{repo}/releases/tag/{tag}',
        'published_at': '2026-11-01T06:00:00Z',
        'assets': [
            {'id': index + 1, 'name': name, 'size': 10485760 + index,
             'state': 'uploaded', 'download_count': 100,
             'digest': 'sha256:' + 'a' * 64,
             'browser_download_url': f'https://github.com/{repo}/releases/download/{tag}/{name}'}
            for index, name in enumerate(names)
        ],
    }


def api_responses(tags=None):
    tags = tags or {'v2rayN': '7.25.6', 'v2rayNG': '2.3.15', 'V2rayU': 'v5.4.1'}
    return {
        'v2rayN': release('v2rayN', tags['v2rayN'], [
            'v2rayN-windows-64.zip', 'v2rayN-windows-arm64.zip',
            'v2rayN-macos-64.dmg', 'v2rayN-macos-arm64.dmg',
            'v2rayN-linux-64.deb', 'v2rayN-linux-arm64.deb']),
        'v2rayNG': release('v2rayNG', tags['v2rayNG'], [
            f'v2rayNG_{tags["v2rayNG"].lstrip("vV")}_arm64-v8a.apk',
            f'v2rayNG_{tags["v2rayNG"].lstrip("vV")}_universal.apk']),
        'V2rayU': release('V2rayU', tags['V2rayU'], ['V2rayU-64.dmg', 'V2rayU-arm64.dmg']),
    }


class ReleaseSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.api = self.root / 'api'
        self.api.mkdir()
        self.raw = api_responses()
        self.write_api()
        blocks = '\n'.join(f'<!-- RELEASES:{name}:START -->\nold content\n<!-- RELEASES:{name}:END -->'
                           for name in ['UPDATED', 'PLATFORMS', 'SUMMARY'])
        self.root.joinpath('download.html').write_text(
            '<!doctype html><html><head><script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"CollectionPage","dateModified":"2026-01-01"}'
            '</script></head><body><p id="retained">Keep editorial content.</p>' + blocks + '</body></html>')
        self.root.joinpath('sitemap.xml').write_text(
            '<?xml version="1.0"?><urlset><url><loc>https://v2raydown.com/</loc>'
            '<lastmod>2026-01-01</lastmod></url><url><loc>https://v2raydown.com/download.html</loc>'
            '<lastmod>2026-01-01</lastmod></url></urlset>')
        self.now = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)

    def write_api(self):
        for project, response in self.raw.items():
            self.api.joinpath(project + '.json').write_text(json.dumps(response))

    def run_sync(self, **kwargs):
        return updater.sync(self.root, api_dir=self.api, now=kwargs.pop('now', self.now), **kwargs)

    def snapshot(self):
        return {name: self.root.joinpath(name).read_bytes() if self.root.joinpath(name).exists() else None
                for name in updater.GENERATED}

    def seed(self):
        self.run_sync()
        return self.snapshot()

    def test_generates_real_file_pairs_for_every_project_without_javascript(self):
        changed, manifest = self.run_sync()
        self.assertEqual(set(changed), set(updater.GENERATED))
        text = self.root.joinpath('download.html').read_text()
        links = Links(text).links
        accelerated = [a for a in links if 'data-release-download' in a]
        expected = {a['browser_download_url'] for r in self.raw.values() for a in r['assets']}
        self.assertEqual({a['href'][len(updater.PROXY):] for a in accelerated}, expected)
        self.assertEqual(len(accelerated), 10)
        original_links = {a.get('href') for a in links}
        self.assertTrue(expected <= original_links)
        self.assertEqual({a['data-release-download'] for a in accelerated}, set(updater.PROJECTS))
        self.assertIn('Keep editorial content.', text)
        self.assertEqual(manifest['updated_at'], '2026-11-24T06:00:00Z')

    def test_new_release_updates_all_urls_versions_metadata_and_only_download_sitemap_date(self):
        self.seed()
        self.raw = api_responses({'v2rayN': '8.1.0', 'v2rayNG': '3.0.0', 'V2rayU': 'v6.0.0'})
        self.write_api()
        changed, manifest = self.run_sync(now=datetime(2026, 12, 1, 18, 5, tzinfo=timezone.utc))
        self.assertEqual(set(changed), set(updater.GENERATED))
        text = self.root.joinpath('download.html').read_text()
        links = Links(text).links
        for project, response in self.raw.items():
            version = 'v' + response['tag_name'].lstrip('vV')
            self.assertIn(version, text)
            self.assertEqual(manifest['projects'][project]['tag'], response['tag_name'])
            for asset in response['assets']:
                self.assertIn(updater.PROXY + asset['browser_download_url'], {a.get('href') for a in links})
        self.assertNotIn('/download/7.25.6/', text)
        self.assertNotIn('/download/2.3.15/', text)
        self.assertNotIn('/download/v5.4.1/', text)
        self.assertIn('2026 年 12 月 02 日 02:05', text)
        self.assertIn('"dateModified": "2026-12-02"', text)
        sitemap = self.root.joinpath('sitemap.xml').read_text()
        self.assertIn('<loc>https://v2raydown.com/</loc><lastmod>2026-01-01</lastmod>', sitemap)
        self.assertIn('<loc>https://v2raydown.com/download.html</loc><lastmod>2026-12-02</lastmod>', sitemap)

    def test_download_counts_and_api_order_do_not_create_update_or_change_timestamp(self):
        before = self.seed()
        for response in self.raw.values():
            response['assets'].reverse()
            for asset in response['assets']:
                asset['download_count'] += 50000
        self.write_api()
        changed, manifest = self.run_sync(now=datetime(2026, 12, 31, tzinfo=timezone.utc))
        self.assertEqual(changed, [])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(manifest['updated_at'], '2026-11-24T06:00:00Z')

    def test_same_tag_replaced_asset_is_detected(self):
        self.seed()
        self.raw['V2rayU']['assets'][0]['id'] = 12345
        self.raw['V2rayU']['assets'][0]['size'] += 1024
        self.raw['V2rayU']['assets'][0]['digest'] = 'sha256:' + 'b' * 64
        self.write_api()
        changed, manifest = self.run_sync(now=datetime(2026, 11, 25, tzinfo=timezone.utc))
        self.assertIn('data/releases.json', changed)
        self.assertIn('download.html', changed)
        asset = manifest['projects']['V2rayU']['assets'][0]
        self.assertEqual(asset['id'], 12345)
        self.assertEqual(asset['sha256'], 'b' * 64)

    def test_rejects_unpublished_incomplete_or_untrusted_release_without_overwriting(self):
        before = self.seed()
        pristine = deepcopy(self.raw)
        def missing_package(raw):
            raw['v2rayN']['assets'] = [a for a in raw['v2rayN']['assets'] if a['name'] != 'v2rayN-macos-arm64.dmg']
        cases = [
            ('prerelease', lambda r: r['v2rayN'].__setitem__('prerelease', True)),
            ('draft', lambda r: r['v2rayNG'].__setitem__('draft', True)),
            ('missing_required_package', missing_package),
            ('cross_repository_asset', lambda r: r['V2rayU']['assets'][0].__setitem__('browser_download_url', 'https://github.com/attacker/V2rayU/releases/download/v5.4.1/V2rayU-64.dmg')),
            ('cross_host_asset', lambda r: r['v2rayN']['assets'][0].__setitem__('browser_download_url', 'https://downloads.example/v2rayN-windows-64.zip')),
            ('zero_size', lambda r: r['v2rayNG']['assets'][0].__setitem__('size', 0)),
            ('not_uploaded', lambda r: r['v2rayN']['assets'][0].__setitem__('state', 'new')),
            ('duplicate_name', lambda r: r['V2rayU']['assets'].append(deepcopy(r['V2rayU']['assets'][0]))),
            ('release_url', lambda r: r['V2rayU'].__setitem__('html_url', 'https://github.com/attacker/V2rayU/releases/tag/v5.4.1')),
        ]
        for name, mutate in cases:
            with self.subTest(name=name):
                self.raw = deepcopy(pristine)
                mutate(self.raw)
                self.write_api()
                with self.assertRaises(updater.ReleaseError):
                    self.run_sync()
                self.assertEqual(before, self.snapshot())

    def test_network_failure_keeps_existing_site(self):
        before = self.seed()
        with patch.object(updater, 'fetch_release', side_effect=updater.ReleaseError('network unavailable')):
            with self.assertRaises(updater.ReleaseError):
                updater.sync(self.root, now=self.now)
        self.assertEqual(before, self.snapshot())

    def test_offline_check_never_fetches_and_detects_generated_html_drift(self):
        self.seed()
        with patch.object(updater, 'fetch_release', side_effect=AssertionError('offline check made an HTTP request')):
            self.assertEqual(updater.sync(self.root, check=True)[0], [])
            text = self.root.joinpath('download.html').read_text().replace('最新稳定版', 'edited version label', 1)
            self.root.joinpath('download.html').write_text(text)
            before = self.snapshot()
            with self.assertRaisesRegex(updater.ReleaseError, 'out of sync'):
                updater.sync(self.root, check=True)
            self.assertEqual(before, self.snapshot())

    def test_offline_check_rejects_tampered_asset_metadata(self):
        self.seed()
        manifest_path = self.root / 'data/releases.json'
        data = json.loads(manifest_path.read_text())
        data['projects']['v2rayN']['assets'][0]['architecture'] = 'arm64'
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        before = self.snapshot()
        with self.assertRaisesRegex(updater.ReleaseError, 'metadata is inconsistent'):
            updater.sync(self.root, check=True)
        self.assertEqual(before, self.snapshot())

    def test_dry_run_does_not_write_any_output(self):
        before = self.snapshot()
        changed, _ = self.run_sync(dry_run=True)
        self.assertEqual(set(changed), set(updater.GENERATED))
        self.assertEqual(before, self.snapshot())

    def test_missing_or_duplicate_markers_prevent_any_writes(self):
        self.seed()
        text = self.root.joinpath('download.html').read_text()
        marker = '<!-- RELEASES:SUMMARY:START -->'
        for name, replacement in [('missing', ''), ('duplicate', marker + marker)]:
            with self.subTest(name=name):
                self.root.joinpath('download.html').write_text(text.replace(marker, replacement))
                before = self.snapshot()
                with self.assertRaisesRegex(updater.ReleaseError, 'Missing or duplicate generated block'):
                    self.run_sync()
                self.assertEqual(before, self.snapshot())


class ClassificationAndFetchTests(unittest.TestCase):
    def test_distinguishes_channels_platforms_and_debug_files(self):
        regular = updater.classify_asset('v2rayNG', 'v2rayNG_2.3.15_arm64-v8a.apk', '2.3.15')
        fdroid = updater.classify_asset('v2rayNG', 'v2rayNG_2.3.15-fdroid_arm64-v8a.apk', '2.3.15')
        self.assertEqual(regular['variant'], 'GitHub')
        self.assertEqual(fdroid['variant'], 'F-Droid')
        self.assertIsNone(updater.classify_asset('v2rayNG', 'v2rayNG_2.3.14_arm64-v8a.apk', '2.3.15'))
        desktop = updater.classify_asset('v2rayN', 'v2rayN-windows-arm64-desktop.zip', '7.25.6')
        self.assertEqual((desktop['platform'], desktop['architecture'], desktop['variant']), ('windows', 'arm64', 'desktop'))
        self.assertEqual(updater.classify_asset('v2rayN', 'v2rayN-windows-86.zip', '7.25.6')['architecture'], 'x86')
        self.assertEqual(updater.classify_asset('v2rayN', 'v2rayN-linux-rhel-loong64.rpm', '7.25.6')['architecture'], 'loong64')
        self.assertIsNone(updater.classify_asset('V2rayU', 'V2rayU-dSYM.zip', 'v5.4.1'))
        self.assertIsNone(updater.classify_asset('v2rayN', 'v2rayN-public-key.asc', '7.25.6'))
        self.assertIsNone(updater.classify_asset('v2rayN', 'v2rayN-macos-arm64.dmg.sig', '7.25.6'))

    def test_missing_or_invalid_digest_is_not_presented_as_a_checksum(self):
        raw = api_responses()['V2rayU']
        raw['assets'][0]['digest'] = None
        raw['assets'][1]['digest'] = 'sha256:not-a-real-checksum'
        normalized = updater.normalise_release('V2rayU', raw)
        self.assertTrue(all(a['sha256'] == '' for a in normalized['assets']))
        text = updater.render_files('V2rayU', normalized, normalized['assets'])
        self.assertNotIn('SHA256 校验值', text)

    def test_rendered_external_values_cannot_inject_html(self):
        release_data = updater.normalise_release('V2rayU', api_responses()['V2rayU'])
        release_data['tag'] = 'v1"><script>alert(1)</script>'
        asset = deepcopy(release_data['assets'][0])
        asset['name'] = '"><img src=x onerror=alert(1)>'
        asset['url'] = 'https://github.com/example/file?x=" onmouseover="alert(1)'
        rendered = updater.render_asset('V2rayU', release_data, asset)
        self.assertNotIn('<img', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;img', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        for link in Links(rendered).links:
            self.assertNotIn('onmouseover', link)
            self.assertNotIn('onerror', link)

    def test_fetch_uses_latest_endpoint_not_version_sorting_and_retries_transient_failure(self):
        response = api_responses()['V2rayU']
        class JsonResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps(response).encode()
        temporary_error = HTTPError('https://api.github.com', 503, 'unavailable', {}, None)
        with patch.object(updater, 'urlopen', side_effect=[temporary_error, JsonResponse()]) as opened, patch.object(updater.time, 'sleep'):
            self.assertEqual(updater.fetch_release('yanue/V2rayU', 'test-token')['tag_name'], 'v5.4.1')
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/yanue/V2rayU/releases/latest')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-token')
        self.assertEqual(opened.call_count, 2)

    def test_auth_failure_does_not_retry_and_never_echoes_token(self):
        error = HTTPError('https://api.github.com', 403, 'forbidden', {}, None)
        with patch.object(updater, 'urlopen', side_effect=error) as opened, patch.object(updater.time, 'sleep') as slept:
            with self.assertRaises(updater.ReleaseError) as raised:
                updater.fetch_release('yanue/V2rayU', 'secret-token')
        self.assertEqual(opened.call_count, 1)
        slept.assert_not_called()
        self.assertNotIn('secret-token', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
