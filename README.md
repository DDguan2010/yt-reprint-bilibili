# YouTube To Bilibili Authorized Sync

这个项目用于在 GitHub Actions 中定时搜索 YouTube 上符合条件的视频，并把你有权同步的内容投稿到 Bilibili。它不需要自建服务器，状态直接保存在仓库文件里。

默认流程是：搜索候选内容、按规则筛选、下载媒体文件、生成 Bilibili 标题/简介/标签、调用 `biliup` 命令行工具投稿、记录已处理 ID。

## 功能

- 支持 GitHub Actions 定时运行和手动运行。
- 支持 `config.yml` 配置关键词、时长、播放量、发布时间、频道名单、标签和分区。
- 有 `YOUTUBE_API_KEY` 时优先使用 YouTube Data API 搜索。
- 没有 `YOUTUBE_API_KEY` 时使用 `yt-dlp ytsearch` 作为搜索兜底。
- 使用 `data/posted.json` 记录已处理视频，避免重复处理。
- 支持 `dry_run`，先验证流程再正式投稿。

## 文件结构

```text
.github/workflows/daily.yml   GitHub Actions 自动流程
config.yml                    主配置文件
requirements.txt              Python 依赖
scripts/search.py             搜索候选视频
scripts/select.py             筛选和排序
scripts/download.py           下载视频、封面、字幕和元数据
scripts/upload.py             调用 biliup 投稿
scripts/update_state.py       更新 data/posted.json
data/posted.json              已处理视频记录
data/download-archive.txt     yt-dlp 下载记录
```

## 使用前准备

1. 确认你只同步自己有权使用的内容，例如自有频道、已获得授权的频道，或明确允许再发布的内容。
2. 创建一个 GitHub 仓库，把本项目推送上去。
3. 在仓库的 `Settings -> Secrets and variables -> Actions -> New repository secret` 添加密钥。

正式投稿必需的仓库配置项：

```text
BILIUP_COOKIE_JSON
```

可选仓库配置项：

```text
YOUTUBE_API_KEY
YOUTUBE_COOKIES_TXT
```

## Bilibili 登录文件

`BILIUP_COOKIE_JSON` 的内容需要由 `biliup` 登录流程生成。建议在本地先安装并登录：

```bash
python -m pip install biliup
biliup login
```

登录后找到 `biliup` 生成的登录文件内容，把完整 JSON 内容复制到 GitHub Secret `BILIUP_COOKIE_JSON`。

如果你本地生成的文件名或格式和 `biliup` 文档不同，以当前安装版本的 `biliup` 官方说明为准。

## 配置关键词和筛选规则

编辑 `config.yml`：

```yaml
search:
  max_uploads_per_run: 1
  max_candidates_per_keyword: 10
  keywords:
    - "open source AI tutorial"
    - "programming productivity tools"

filters:
  min_duration_seconds: 180
  max_duration_seconds: 1800
  min_view_count: 1000
  published_within_days: 14
  require_creative_commons: true
```

建议第一阶段保持：

```yaml
require_creative_commons: true
max_uploads_per_run: 1
```

如果你使用的是授权频道白名单，可以设置：

```yaml
filters:
  channel_allowlist:
    - "UCxxxxxxxxxxxxxxxxxxxxxx"
```

## 手动测试流程

进入 GitHub 仓库页面：

1. 打开 `Actions`。
2. 选择 `Daily Authorized Video Sync`。
3. 点击 `Run workflow`。
4. `dry_run` 选择 `true`。
5. 可选输入一个测试关键词。
6. 运行完成后下载 `run-state` artifact，检查 `selected.json` 和 `upload-result.json`。

`dry_run=true` 时会执行搜索、筛选、下载和生成投稿命令，但不会真正投稿，也不会更新 `posted.json`。这种模式可以不配置 `BILIUP_COOKIE_JSON`。

## 正式运行

手动确认 dry-run 结果正常后：

1. 再次点击 `Run workflow`。
2. 设置 `dry_run=false`。
3. 等待 workflow 完成。
4. 成功后会更新 `data/posted.json` 并自动提交。

定时运行配置在 `.github/workflows/daily.yml`：

```yaml
schedule:
  - cron: "30 18 * * *"
```

这里是 UTC 时间。`18:30 UTC` 大约是北京时间次日 `02:30`。

## 本地 dry-run

本地也可以验证配置和脚本：

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts/search.py
python scripts/select.py
python scripts/download.py
set DRY_RUN=true
python scripts/upload.py
```

PowerShell 使用：

```powershell
$env:DRY_RUN = "true"
python scripts/upload.py
```

## 常见调整

如果候选太少，可以降低这些限制：

```yaml
min_view_count: 100
published_within_days: 30
require_creative_commons: false
```

如果投稿命令因为 `biliup` 参数变化失败，优先修改 `config.yml` 中的：

```yaml
bilibili:
  upload_command_template: >-
    biliup -u {cookie_file} upload {video_file}
    --copyright {copyright}
    --source {source}
    --tid {tid}
    --title {title}
    --desc-file {desc_file}
    --tag {tags}
```

## 注意事项

- GitHub Actions 定时运行可能有延迟，不适合要求严格到分钟级的任务。
- GitHub-hosted runner 对运行时长和磁盘空间有限制，建议单次只处理 1 个视频。
- `biliup` 登录文件可能会失效，需要定期更新 `BILIUP_COOKIE_JSON`。
- `yt-dlp` 搜索兜底拿不到完整授权信息；如果你要求严格筛选 Creative Commons，建议配置 `YOUTUBE_API_KEY`。
- Bilibili 分区、标签、简介模板请按你的账号定位自行调整。
