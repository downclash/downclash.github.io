// Generate links locally; the acceleration service is contacted only when opened.
function buildGitHubDownloadLinks(value) {
  const input = value.trim();
  if (!input) throw new Error('请先粘贴 GitHub 文件链接。');
  let source;
  try {
    source = new URL(input.startsWith('//') ? 'https:' + input : (/^https?:\/\//i.test(input) ? input : 'https://' + input));
  } catch (error) {
    throw new Error('链接格式不正确，请复制 GitHub 文件的完整地址。');
  }
  if (!['http:', 'https:'].includes(source.protocol) || source.hostname !== 'github.com' || source.username || source.password || source.port) {
    throw new Error('请使用 github.com 的文件链接。');
  }
  const filePath = /^\/[^/]+\/[^/]+\/(?:releases\/download\/[^/]+\/.+|archive\/.+\.(?:zip|tar\.gz|tgz)|(?:blob|raw)\/[^/]+\/.+)$/;
  if (!filePath.test(source.pathname) || source.pathname.endsWith('/')) {
    throw new Error('仅支持 Release 文件、archive 源码压缩包和 blob/raw 单文件；请勿使用发布页或项目文件夹链接。');
  }
  source.protocol = 'https:';
  source.hash = '';
  return { original: source.href, accelerated: 'https://github.v2raydown.com/' + source.href };
}

(function () {
  const form = document.querySelector('[data-github-accelerator]');
  if (!form) return;
  const input = form.querySelector('input');
  const status = document.getElementById('github-file-status');
  const result = form.querySelector('[data-accelerator-result]');
  const accelerated = form.querySelector('[data-accelerated-link]');
  const original = form.querySelector('[data-original-link]');

  function clearResult() {
    result.hidden = true;
    accelerated.removeAttribute('href');
    original.removeAttribute('href');
    input.removeAttribute('aria-invalid');
    status.textContent = '';
  }

  input.addEventListener('input', clearResult);
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearResult();
    try {
      const links = buildGitHubDownloadLinks(input.value);
      accelerated.href = links.accelerated;
      original.href = links.original;
      const filename = new URL(links.original).pathname.split('/').pop();
      let label = filename;
      try { label = decodeURIComponent(filename); } catch (error) { /* Keep the original file name. */ }
      form.querySelector('[data-accelerator-filename]').textContent = '文件：' + label;
      form.querySelector('[data-accelerator-url]').textContent = links.accelerated;
      status.textContent = '已生成加速链接，请核对文件名后选择下载。';
      result.hidden = false;
    } catch (error) {
      input.setAttribute('aria-invalid', 'true');
      status.textContent = error.message;
      input.focus();
    }
  });
  form.hidden = false;
})();
