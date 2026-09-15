# FreeAI Radar

一个**可核查**的免费 AI API 目录。

不是"收录了 500 个免费 API"的清单，而是一份**每条结论都能点回原文**的目录：
每个提供商、每个免费套餐、每条限制条件，都带着来源、抓取时间和证据片段。
说不好的地方就说"不知道"，不把"未知"写成"不支持"。

站点是**纯静态页面**，浏览器只读公开 JSON，没有任何后端在你访问时替你发请求。

---

## 这个项目不是什么

先说清楚边界，比说清楚功能更重要。

- **不是一个帮你调用 AI 的网关。** 没有任何统一接口，没有代理，没有转发。
- **不收集、不保存、不传输你的 API Key。** Key 只存在你自己的 CC Switch 里。
- **不承诺"永久免费"。** 免费的判断带有时间戳，是"截至某次采集时，来源这么说"。
- **不替你做兼容性保证。** 它告诉你来源声称支持什么协议，以及**这个声称是谁说的**。
- **不做在线投稿后台。** 修改通过 GitHub 提交，走代码审查。

## 它做什么

| 能力 | 说明 |
| --- | --- |
| 多来源采集 | 每个来源一个独立适配器，Markdown / HTML / 官方字段各有专门解析器 |
| 每日更新 | GitHub Actions 定时采集，跨次运行保留状态，产出变更历史 |
| 来源留痕 | 每条结论附证据片段与原文链接，可点回核对 |
| 口径分离 | 访问方式 ≠ 免费类型 ≠ 信息状态 ≠ 调用状态 ≠ 客户端兼容性，五个维度分开记 |
| 冲突标记 | 两个来源说法不一致时标记为冲突，不静默取其一 |
| 过期识别 | 超过阈值未再确认的条目标记为可能过期 |
| CC Switch 导出 | 生成配置预览、逐字段复制、协议支持时给出 Deep Link，并明确说明何时**不支持** |
| 收藏与对比 | 本地收藏，多列对比（存在你自己的浏览器里） |

## 五个维度，分开记

这是整个项目最核心的设计决定。把下面任何两项合并成一个字段，目录就会开始骗人。

| 维度 | 取值 | 为什么必须独立 |
| --- | --- | --- |
| **访问方式** | `api` / `web_chat_only` / `local` / `unknown` | 免费网页版 ≠ 免费 API |
| **免费类型** | 持续免费额度 / 周期性额度 / 一次性试用 / 限时活动 / 需充值 / 未知 | "试用一次"和"每月免费额度"是两种东西 |
| **信息状态** | 目录声称 / 官方已确认 / 待复核 / 来源冲突 / 已过期 | 来源说的 ≠ 官方说的 |
| **调用状态** | 未测试 / 成功 / 密钥错误 / 限流 / 额度用尽 / 网络错误 / 服务错误 | Radar 不会用你的 Key 发请求，所以默认永远是"未测试" |
| **客户端兼容** | 四种协议各自独立：`openai_chat` / `openai_responses` / `anthropic_messages` / `gemini_native` | Codex 只认 Responses，不认 Chat Completions |

### 三态规则

所有"要不要"类字段都是三态：`need` / `not_need` / `unknown`。

**`unknown` 永远不会被写成 `not_need`。** 来源没提是否需要信用卡，那答案就是"不知道"，
不是"不需要"。这条规则在 schema、归一化、前端渲染三处都有对应测试守着。

## 快速开始

```bash
git clone https://github.com/OWNER/freeai-radar
cd freeai-radar

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 1. 采集（需要联网）
# 第一次跑时 state.json 还不存在，所以要同时给 --init：
# --previous 只是告诉程序"状态该在哪"，--init 才是授权它从空开始。
python -m radar.collect \
  --config config/sources.yaml \
  --reviews config/reviews.yaml \
  --aliases config/aliases.yaml \
  --previous .work/state.json \
  --output .work/state.json \
  --init

# 之后的每一次都复用同一个 --previous，去掉 --init：
# 文件不见了会直接报错，而不是把已有历史当成空的重新开始。

# 2. 导出公开数据集
python -m radar.export_public \
  --state .work/state.json \
  --output .work/public \
  --base-path /

# 3. 生成静态站点
python -m radar.build_site \
  --data .work/public \
  --base-path / \
  --output dist

# 4. 本地预览
python -m http.server 8000 --directory dist
# 打开 http://localhost:8000
```

日常开发只需要第 3、4 步——`tests/fixtures/state.minimal.json` 是一份可离线构建的
最小数据集，用它可以在不联网的情况下验证模板改动：

```bash
python -m radar.export_public --state tests/fixtures/state.minimal.json \
  --output .work/public --base-path /freeai-radar/
python -m radar.build_site --data .work/public \
  --base-path /freeai-radar/ --output dist
```

## 部署到你自己的 GitHub Pages

见 [docs/github-pages.md](docs/github-pages.md)。要点：

1. Fork 本仓库。
2. Settings → Pages → Source 选 **GitHub Actions**。
3. Settings → Actions → General → Workflow permissions 选 **Read and write**。
4. Settings → Actions → General → 勾选 **Allow GitHub Actions to create and approve pull requests**。
5. 手动跑一次 `publish` workflow（Actions → publish → Run workflow），
   勾选 `force` 做首次完整采集。

之后每天 UTC 00:23（北京时间 08:23）自动更新。

> 首次运行必须在 workflow 里勾选 `force`。没有历史状态时，条件请求缓存会让所有来源
> 都返回 `304 not_modified`，站点会看起来是空的。

## 项目结构

```
radar/                  采集与构建（只在构建时运行，线上不执行）
  collectors/           每个来源一个适配器，互不依赖
  parsers/              Markdown 表格 / HTML 文档 / 官方字段解析器
  normalize.py          归一化：去重、三方合并、冲突标记、过期判定
  safety.py             SSRF 防护：方案白名单、域名白名单、DNS 解析后二次校验
  export_public.py      按字段白名单导出公开 JSON
  build_site.py         用 Jinja2 渲染静态站点
  cc_switch.py          CC Switch 配置与 Deep Link 生成
site/
  templates/            页面模板
  static/css/           tokens → glass → components → pages 四层样式
  static/js/            原生 ES Module，无框架、无构建步骤
schemas/                JSON Schema（state / catalog / manifest）
tests/                  pytest 套件 + 离线夹具
config/sources.yaml     来源配置（每个来源的域名白名单、许可、解析器）
```

## 架构约束

这些是硬约束，不是偏好：

- **静态站点。** 没有常驻服务，没有在线数据库，没有管理写接口。
- **浏览器只读公开 JSON。** 页面不替你发任何出站请求。
- **Python 只在构建时运行。** 线上零 Python。
- **密钥不出现在 URL、导出文件、遥测、日志里。** CC Switch 预览里 `apiKey` 永远是空的。
- **不加框架。** 用原生 ES Module 与手写 CSS，避免引入需要构建步骤的依赖。
- **不用 WebGL。** Liquid Glass 用 `backdrop-filter`，配合 `@supports` 回退到不透明样式。

## 数据来源与许可

来源清单、每个来源的许可与使用条款见 [docs/sources.md](docs/sources.md)。

只保存必要的事实、短证据片段和链接，**不镜像来源页面**。每个适配器的
`allowed_domains` 在发请求之前就生效，白名单之外的域名会被直接拒绝。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请走 [SECURITY.md](SECURITY.md) 的私下渠道。

## 许可

代码以 MIT 许可发布，见 [LICENSE](LICENSE)。
第三方数据与依赖的归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 免责声明

Radar 只做信息汇总与核对，**不保证任何第三方服务的可用性、额度或条款**。
"免费"是某一时刻来源的说法，随时可能变化。使用任何服务前请自行阅读该服务的官方条款。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/github-pages.md](docs/github-pages.md) | fork 后部署到自己的 Pages，含首次运行必须勾 `force` 的原因 |
| [docs/sources.md](docs/sources.md) | 每个来源的 URL、许可、采集方法、解析器版本；镜像关系的判定规则 |
| [docs/architecture.md](docs/architecture.md) | 数据流、状态持久化、规范化规则、为什么不引框架 |
| [docs/cc-switch.md](docs/cc-switch.md) | 版本钉定、四种结果状态、Deep Link 形状、升级流程 |
| [docs/release-checklist.md](docs/release-checklist.md) | 发布闸门。C6 组需要真实仓库，没有时只能标"未验证" |
| [docs/progress.md](docs/progress.md) | M0–M6 逐阶段进度与证据 |
| [docs/delivery.md](docs/delivery.md) | 交付报告：已实现并验证 / 已实现未验证 / 未实现或受阻 |

> **当前状态：** 代码完整、测试通过、可复现，**129 个源文件已推送到
> [DUSKpy/FreeAI-Radar](https://github.com/DUSKpy/FreeAI-Radar) 并逐文件核对一致**；
> 但**站点尚未上线**——`.github/workflows/` 需要 `workflow` scope 才能推送，
> 而当前凭据没有。见 [docs/delivery.md](docs/delivery.md) 第 3.1 节。
>
> 解锁只需一步：`gh auth refresh -h github.com -s workflow`
