// Run with: node scripts/check_download_links.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const context = { URL, document: { querySelector() { return null; } } };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'assets/js/download.js'), 'utf8'), context);
const build = context.buildGitHubDownloadLinks;
const release = 'https://github.com/2dust/v2rayNG/releases/download/2.3.15/v2rayNG_2.3.15-fdroid_arm64-v8a.apk';
const valid = [
  [release, release],
  [release.replace('https://', ''), release],
  [release.replace('https://', 'http://'), release],
  [release.replace('https:', ''), release],
  ['  ' + release + '  ', release],
  ['https://github.com/hunshcn/project/archive/master.zip', 'https://github.com/hunshcn/project/archive/master.zip'],
  ['github.com/hunshcn/project/archive/v0.1.0.tar.gz', 'https://github.com/hunshcn/project/archive/v0.1.0.tar.gz'],
  ['https://github.com/2dust/v2rayN/archive/refs/heads/master.zip', 'https://github.com/2dust/v2rayN/archive/refs/heads/master.zip'],
  ['https://github.com/hunshcn/project/blob/master/filename', 'https://github.com/hunshcn/project/blob/master/filename'],
  ['https://github.com/hunshcn/project/raw/master/path/file%20name.txt?raw=true#L1', 'https://github.com/hunshcn/project/raw/master/path/file%20name.txt?raw=true']
];
for (const [input, original] of valid) {
  const links = build(input);
  assert.equal(links.original, original);
  assert.equal(links.accelerated, 'https://github.v2raydown.com/' + original);
}
const invalid = [
  '', 'not a URL', 'https://example.com/file.zip',
  'https://github.com.evil.example/owner/repo/archive/main.zip',
  'https://github.com@evil.example/owner/repo/archive/main.zip',
  'https://user:password@github.com/owner/repo/archive/main.zip',
  'https://github.com:8443/owner/repo/archive/main.zip',
  'https://github.com/owner/repo',
  'https://github.com/owner/repo/releases/latest',
  'https://github.com/owner/repo/releases/tag/v1',
  'https://github.com/owner/repo/tree/main/folder',
  'https://github.com/owner/repo/releases/download/v1/',
  'https://github.com/owner/repo/archive/main',
  'https://github.com/owner/repo/blob/main/folder/',
  'javascript:alert(1)'
];
for (const input of invalid) assert.throws(() => build(input), undefined, input);
// Each static accelerated download must retain the identical GitHub file as a fallback.
const html = fs.readFileSync(path.join(root, 'download.html'), 'utf8');
const staticDownloads = Array.from(html.matchAll(/href="https:\/\/github\.v2raydown\.com\/(https:\/\/github\.com\/[^"\s]+)"/g));
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'data/releases.json'), 'utf8'));
const expectedAssets = Object.values(manifest.projects).flatMap(release => release.assets.map(asset => asset.url));
assert.equal(staticDownloads.length, expectedAssets.length);
assert.deepEqual(new Set(staticDownloads.map(match => match[1])), new Set(expectedAssets));
for (const [, original] of staticDownloads) {
  assert.equal(build(original).original, original);
  assert.ok(html.includes('href="' + original + '"'), 'Missing original download: ' + original);
}
console.log(`${valid.length} supported inputs, ${invalid.length} rejected inputs, and ${staticDownloads.length} static download pairs passed.`);
