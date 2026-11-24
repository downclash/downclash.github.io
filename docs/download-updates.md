# 最新版本下载链接自动更新

当前实现保存在本地工作区，尚未推送到 GitHub，因此云端定时检测和网站部署尚未激活。工作流文件为 `.github/workflows/update-releases.yml`。

## 更新流程

工作流通过 GitHub Releases API 获取 v2rayN、v2rayNG、V2rayU 的 Latest 稳定版，以发布资产实际提供的文件名和 URL 生成加速链接。站点使用 `https://github.v2raydown.com/` 前缀，同时提供 GitHub 原始下载与发布说明。预发布版不替代稳定版，App Store 应用不套用 GitHub 文件加速。

| 触发方式 | 行为 |
| --- | --- |
| 每 6 小时，UTC 的 00:17、06:17、12:17、18:17 | 检测发布信息；有生成文件变化时提交，无变化时不提交；检查成功后均部署 |
| 推送到 `main` | 检测、验证并部署网站，包含同次提交的文章与样式修改 |
| Actions 中手动 Run workflow，分支选 `main` | 立即执行一次检测、验证与部署 |

北京时间对应每日 02:17、08:17、14:17、20:17。计划运行可能因 GitHub Actions 排队而延迟，不能保证新版本发布后即时更新。工作流只在 `main` 运行，定时触发还要求它位于仓库默认分支。

脚本更新以下文件，工作流也只允许将这三个路径加入自动提交：

- `data/releases.json`：已核对的发布信息和安装包下载地址。
- `download.html`：可直接点击的版本、架构、加速下载及原始下载链接。
- `sitemap.xml`：下载页的实际内容更新日期。

API 请求、资产解析或任一检查失败时，工作流停止，不提交生成内容，也不部署。既有线上版本继续保留。生成结果通过检查后，如有变更则先提交和推送上述文件，再在同一运行中上传并部署 Pages 产物。无变化时仍重新部署，保证上一次提交成功、部署失败的情况能在下次成功运行时恢复。它不依赖 bot 提交再次触发另一个工作流；使用 `GITHUB_TOKEN` 的 push 不会触发新的 push 工作流或分支式 Pages 构建。

Pages 产物仅包含根目录 HTML、`assets/`、`CNAME`、`robots.txt`、`sitemap.xml`、`data/releases.json`。脚本、测试、文档、SEO 审核文件、Git 配置以及工作流文件不会被打包到公开网站。

## 首次启用

1. 将当前完整站点修改、更新脚本、测试、缓存数据及工作流一并提交到该仓库的 `main`，并推送。只上传工作流而缺少脚本或缓存会使检查失败。
2. 在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。确认已有自定义域名与 HTTPS 设置正确；`CNAME` 文件本身不能代替远端域名设置。
3. 在 **Settings → Actions → General** 确认允许本工作流使用的官方 Actions。工作流为更新 job 声明 `contents: write`，为部署 job 声明 `contents: read`、`pages: write` 和 `id-token: write`；组织策略仍可能限制这些权限。
4. 确认 `main` 分支规则允许该自动任务提交这三个生成文件，并允许 `github-pages` environment 从 `main` 部署。需要人工批准或强制 PR 的规则不会被本工作流绕过；若规则阻止 push，任务会失败且不部署，应按现有治理方式调整发布流程。
5. 打开 **Actions → Update releases and deploy site → Run workflow**，选择 `main` 首次执行。检查 update 和 deploy 两个 job 成功，再核对正式网站下载链接。

不需要额外创建个人访问令牌。GitHub 自动提供的 `GITHUB_TOKEN` 仅在工作流的更新步骤通过环境变量传入；本地运行时没有令牌也可访问公开 API，但请求额度较低。不要将令牌写进 JSON、HTML、命令历史或提交记录。

仓库历史提交说明曾引用 `downclash/v2raydown@<commit>`，表明这里曾由另一个源项目生成部署文件。如果原项目的自动部署仍在运行，它可能覆盖本仓库的下载页、新文章或更新脚本。首次启用前，应将当前改动同步回原源项目，或停止旧发布任务，以选定一个权威发布来源。本轮没有修改那个外部源项目，也没有确认其远端任务状态。

## 本地执行与验证

在仓库根目录运行，脚本和测试仅使用 Python、Node.js 内置标准库，无需 npm 或 pip 安装：

```sh
# 联网检测并重新生成三个目标文件
python3 scripts/update_releases.py

# 离线核对缓存数据与生成 HTML 是否一致，不请求 GitHub
python3 scripts/update_releases.py --check

# 完整检查
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/audit_seo.py
node scripts/check_download_links.cjs
git diff --check
```

本地预览可在仓库根目录启动：

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

随后打开 `http://127.0.0.1:8765/download.html?platform=windows`。停止终端中的服务器后，该地址会停止响应；这不影响已经生成的静态页面或云端更新任务。

测试发布接口时，可把响应 JSON 放入脚本约定的 fixture 目录，然后执行 `python3 scripts/update_releases.py --api-dir /path/to/fixtures`。这会使用本地响应生成内容；它不表示已联网确认 GitHub 当前版本。不要把测试生成的虚构版本提交或发布。

修改页面中由脚本管理的下载区块后，应同步修改生成模板或渲染逻辑，并重新运行 `--check`，避免下次版本检测覆盖手工改动。连接超时、API 限额、下载资产缺失或命名规则变化时，查看 Actions 失败日志，修复后手动重新执行；不要将不确定的文件名拼接成可发布下载地址。

## 运行边界

GitHub 在公共仓库连续 60 天无活动时可能自动禁用定时工作流。若检测长期不运行，先在 Actions 检查任务是否被禁用并重新启用。工作流没有新增人为的定期空提交来规避该机制。

本流程验证发布元数据、文件匹配和页面一致性，不会下载完整安装包进行运行测试，也不保证加速服务的传输速度。安装时仍应核对发布项目、架构、签名和项目提供的校验值。

## 官方依据

- [GitHub Pages：配置发布来源](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [GitHub Pages：自定义工作流与部署权限](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub Actions：工作流触发与 GITHUB_TOKEN 的限制](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [GitHub Actions：schedule 的默认分支、延迟和暂停行为](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [actions/checkout](https://github.com/actions/checkout)、[actions/setup-python](https://github.com/actions/setup-python)、[actions/setup-node](https://github.com/actions/setup-node)
- [actions/configure-pages](https://github.com/actions/configure-pages)、[actions/upload-pages-artifact](https://github.com/actions/upload-pages-artifact)、[actions/deploy-pages](https://github.com/actions/deploy-pages)
- 本工作流固定使用的发布标签：[upload-pages-artifact v5.0.0](https://github.com/actions/upload-pages-artifact/releases/tag/v5.0.0)、[deploy-pages v5.0.1](https://github.com/actions/deploy-pages/releases/tag/v5.0.1)。通用 Pages 教程可能仍展示早期主版本示例；这两个标签已按官方 Release 页面核对。
