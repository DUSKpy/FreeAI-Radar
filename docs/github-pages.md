# 部署到 GitHub Pages

从 fork 到线上可访问，大约十分钟。**第 6 步（首次强制采集）最容易漏**，
漏了会得到一个"标题正常、目录空"的站点。

## 前置条件

- 一个 GitHub 账号
- 仓库需要有 Actions 权限（公开仓库免费）

## 步骤

### 1. Fork 仓库

在仓库页面点 **Fork**。

### 2. 开启 Pages 并选择 Actions 作为来源

`Settings` → `Pages` → **Build and deployment** → `Source` 选 **GitHub Actions**。

不要选 "Deploy from a branch"。分支模式会尝试用 Jekyll 处理产物，
而 `publish.yml` 已经负责构建和部署了。

### 3. 给 workflow 写权限

`Settings` → `Actions` → `General` → **Workflow permissions**
→ 选 **Read and write permissions** → Save。

为什么需要：`persist` 阶段要把采集结果提交回 `data/`，
跨次运行的状态就靠这个提交保存。只读权限下这一步会失败。

### 4. 允许 Actions 创建 PR（可选但建议）

同一页面的 **Allow GitHub Actions to create and approve pull requests** 打勾。

这一步不是必须的。勾上之后，如果将来想改成"数据变更走 PR 而不是直接提交"，
不用再回来改设置。

### 5. 确认 Pages 的环境

`Settings` → `Environments` 里应该已经自动出现一个 `github-pages` 环境。
不需要手动创建。

### 6. 手动跑一次，并勾选 force ⚠️

`Actions` → 左侧选 **publish** → 右侧 **Run workflow** →
**把 `force` 打勾** → Run。

**这一步不能省。** 原因：

首次运行时没有历史状态，所有条件请求都带不上 `If-None-Match`；
但更常见的情况是——你 fork 过来的仓库里可能已经带了 `data/` 目录，
里面是上游的状态和 ETag。此时条件请求会收到 `304 Not Modified`，
采集器认为"内容没变"，于是**不产生任何记录**，
站点会构建成一个空的目录。

勾选 `force` 会忽略条件请求缓存，强制重新拉取全部来源。

### 7. 确认首次部署成功

workflow 跑完后：

- `Actions` → `publish` → 最近一次运行，三个 job（`collect` / `commit data` /
  `deploy to Pages`）都应该是绿的
- 页面底部的 **Deployed** 摘要里会给出站点地址
- 地址形如 `https://<你的用户名>.github.io/freeai-radar/`

打开它，首页应该显示非零的服务商数量。

### 8. 之后自动运行

`cron: "23 0 * * *"`（UTC）= 北京时间每天 08:23。

GitHub 的定时任务在高峰期可能延迟几分钟到几十分钟，这是平台行为，不是故障。

## 关于 `base_path`

站点不是部署在域名根目录，而是在 `/<仓库名>/` 下。构建脚本已经处理：

- 所有资源引用都是 `/freeai-radar/assets/...` 这样的**基于 base path 的绝对路径**
- `404.html` 在嵌套未知路径下也能正确加载样式
- `manifest.json` 里的 `catalog_url` 等字段带 base path

如果你的仓库名不是 `freeai-radar`，两处会自动跟上，因为 workflow 里用的是
`${{ github.event.repository.name }}`。本地手动构建时记得传 `--base-path`：

```bash
python -m radar.build_site --data .work/public \
  --base-path /你的仓库名/ --output dist
```

## 常见问题

### 站点打开是空的，或者服务商数量是 0

**最可能的原因**：首次运行没勾 `force`，采集全部返回 304。

处理：Actions → publish → Run workflow → 勾上 `force`。

如果仍然为空，看 `collect` job 的日志里每个来源的 `status`：

| status | 含义 | 处理 |
| --- | --- | --- |
| `ok` | 正常 | — |
| `not_modified` | 条件请求命中缓存 | 用 `force` 重跑 |
| `failed` | 网络或 HTTP 错误 | 看 `error` 字段 |
| `parse_error` | 页面能取到但解析不出内容 | 上游可能改版了，需要改解析器 |
| `skipped` | 被 `--skip` 排除 | — |

### `commit data` job 失败，提示权限不足

回到第 3 步，确认 Workflow permissions 是 **Read and write**。

### `deploy to Pages` 失败：Pages 未启用

回到第 2 步。`Source` 必须是 **GitHub Actions**。

### 采集被 SSRF 防护拦住了

日志里出现 `private/reserved address refused` 或 `resolves to blocked address`。
两种可能：

1. **你期望的**：来源域名解析到了内网地址。这是真实拦截，不要绕过。
2. **误拦**：你在 Clash / Surge 这类 DNS 代理后面，域名被解析成
   `198.18.x.x` 假地址。

第二种情况可以放开（**仅限本地**，不要写进仓库）：

```bash
FA_RADAR_ALLOW_DNS_PROXY=1 python -m radar.collect ...
```

在 Actions 里对应的是仓库变量 `FA_RADAR_ALLOW_DNS_PROXY`。
**默认不要设**——它放宽了 SSRF 防护的一类地址段。

### 我想改成每天跑两次

改 `.github/workflows/publish.yml` 里的 cron：

```yaml
on:
  schedule:
    - cron: "23 0 * * *"
    - cron: "23 12 * * *"
```

注意 `concurrency: publish` 配的是 `cancel-in-progress: false`，
所以两次运行会排队而不是互相打断。

### 我不想让 Action 自动提交数据

把 `persist` job 整个删掉，并给 `collect` 加 `--init`。
代价是**每次运行都是首次运行**：没有跨次状态，所有条目都会被标记为"新增"，
变更历史失去意义。除非你只是想要一个一次性的快照，否则不建议。

### 我改了源码但线上没变

`publish.yml` 只在定时和手动触发时运行。改代码后要么等下一次定时，
要么手动 Run workflow。

如果你改的是 `ci.yml` 覆盖的东西（模板、样式、Python），
先确认 `ci` workflow 是绿的——它会跑一遍完整构建。
