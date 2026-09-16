# 实施进度 / Progress

对照任务书第 30 节的里程碑表逐项记录。**每完成一个阶段就更新这里**，不要把进度
攒到最后一起写——那样"完成证据"就变成了回忆，而不是当时看到的输出。

图例：**✅ 完成** · **🟡 部分完成** · **⛔ 受阻** · **⬜ 未开始**

最后更新：2026-09-16

**目标仓库：** https://github.com/DUSKpy/FreeAI-Radar
**Pages 地址：** https://duskpy.github.io/FreeAI-Radar/ —— ✅ **已上线，HTTP 200**

---

## 里程碑总览

| 阶段 | 状态 | 完成证据 |
| --- | --- | --- |
| M0 项目检查、来源许可、CC Switch 导入格式 | ✅ | [调研结论](#m0--项目检查来源许可与-cc-switch-格式) |
| M1 Schema、fixture、静态目录详情闭环 | ✅ | 无后端预览 + 离线构建闭环 |
| M2 多源采集、官方核实、diff、历史与失败恢复 | ✅ | 真实来源烟测 56 providers + 离线异常测试 |
| M3 CC Switch 预览、转换和复制回退 | ✅ | 固定版本契约测试 33 项 + 浏览器实测 |
| M4 全页面玻璃 UI、主题、收藏、iPad 适配 | ✅ | `docs/screens/` 19 张截图 |
| M5 CI、Actions、Pages、开源与 fork 教程 | ✅ | 工作流校验 + 离线全流程复现 |
| M6 目标仓库部署和线上验收 | ✅ | **站点 HTTP 200**，8 页全通，线上 56/173/192；CI 与 publish 均全绿 |
| M7 液态玻璃重做与移动端重构 | ✅ | 折射/高光/毛玻璃三层，`docs/screens/` 97 张 |
| M8 界面缺陷清理（可见的与不可见的） | ✅ | 4 类真实缺陷，含一个"点了没反应"的控件 |
| M9 对比度余量：一个"通过"但只多 0.07 的配色 | ✅ | `test_token_contrast.py` 10 项 |
| M10 图片背景、搜索图标重叠、宽屏不铺满 | ✅ | 逐像素审计 1944 元素全通过；`test_photo_backdrop_contrast.py` 14 项，5 处注入全捕获 |
| M11 液态玻璃：折射流动 + 无段透过度滑杆 | ✅ | `.work/glass-verify.mjs` 16/16；照片模式 1944 元素全通过 |
| M12 逐面板自适应：玻璃对背后亮度响应 | ✅ | `.work/glass-adaptive-verify.mjs` 7/7；topbar 17.1% / sidebar 19.3%；照片模式 1944 元素全通过 |

**当前测试基线：** `267 passed` · `ruff check` 全绿 · `ruff format --check` 全绿
（CI 上会少 1 个因沙箱批量删除守卫而跳过的用例）

---

## M0 — 项目检查、来源许可与 CC Switch 格式

**状态：** ✅ 完成

### 做了什么

1. **确认静态架构可行**，不引入常驻服务。任务书第 4 节把架构钉死了：浏览器只读公开
   JSON，Python 只出现在构建/采集期。所以没有 FastAPI、没有在线库、没有管理写入 API、
   没有统一网关。

2. **逐个确认数据来源的许可**，结论写进 `docs/sources.md` 与 `config/sources.yaml`：

   | 来源 | 许可 | 结论 |
   | --- | --- | --- |
   | `nejib1/Free-LLM` | MIT | 启用 |
   | `open-free-llm-api/awesome-freellm-apis` | MIT | 启用 |
   | `AILookup/free-llm-resources` | **无 LICENSE 文件** | **禁用**，适配器写好但默认关闭 |

   第三条是 M0 最有价值的产出：**发现了一个不能用的来源，而不是假设它可以用。**
   任务书说明确要求"没有许可时不复制大段内容或镜像数据库"。

3. **识别镜像关系。** `free-llm.com` 与 Free-LLM 仓库、`freellm.net` 与
   awesome-freellm-apis 各自共享同一份上游数据。它们被登记为同一个 `source_family`
   并标注 `mirrors`——否则同一条数据在两边出现会被误当成两次独立确认。
   这是整个项目最重要的一条判断规则。

4. **确认 CC Switch 的导入格式**：`ccswitch://v1/import`，参数为
   `resource` / `app` / `name` / `endpoint` / `apiKey` / `homepage` / `model`。
   版本钉在 CC Switch **3.20.3** / commit **06082e1**，协议版本 `v1`。

5. **确认五个目标 App 各自需要的协议**——这是 M3 的关键输入：

   | App | 需要的协议 |
   | --- | --- |
   | `claude` | `anthropic_messages` |
   | `codex` | `openai_responses` |
   | `gemini` | `gemini_native` |
   | `opencode` | `openai_chat` |
   | `openclaw` | `openai_chat` |

   于是四种协议必须**分开存储**，不能塌缩成一个 "OpenAI 兼容" 布尔值。

### 证据

- `docs/sources.md` —— 来源表、镜像关系、抓取礼貌性参数
- `docs/cc-switch.md` —— 版本钉定表、协议→App 映射表
- `config/sources.yaml` —— 每个来源的 `license` / `license_url` / `terms_url`

---

## M1 — Schema、fixture 与静态闭环

**状态：** ✅ 完成

### 做了什么

- 定义 `schemas/state.schema.json` 与 `schemas/catalog.schema.json`，均
  Draft 2020-12，`additionalProperties: false`。
- 建立 `tests/fixtures/state.minimal.json`（2 来源 / 3 provider / 6 model /
  6 offer / 8 claim / 3 change），可离线构建。
- 打通 `export_public → build_site` 闭环，产出 8 个页面 + 6 个资源。
- 前端用**原生 ES Module**，没有框架、没有构建步骤。

### 证据

```bash
python -m tests.validate_fixtures
# ok    state.minimal.json vs state.schema.json
# all fixtures validate

python -m radar.build_site --data .work/public-fixture --out dist-fixture --base-path /
# "provider_count": 3
```

### 修掉的真问题

- **`load_versioned()` 路径重复。** manifest 里的 URL 带 `/data/` 段，而 `data_dir`
  本身已经是 `data/`，于是拼出 `<dir>/data/data/…`，**六个版本化文件全部静默加载成
  `None`**——站点渲染出空目录，构建却报告 `provider_count: 0` 并退出 0。
  这是最难发现的一类 bug：成功退出 + 空结果。修完 `provider_count` 从 0 变 56。
- **`offer.evidence` 没进 `required`。** 同一份 schema 里 `claim.evidence` 是必填的，
  但 offer 的不是。用真实 catalog 验证：删掉 `offers[0].evidence` 得到 **0 个校验错误**。
  补上，并留了一条回归测试。
- **`favicon.ico` 每页 404。** 加 `site/static/favicon.svg`。
- **`_prepare_output` 遇到锁文件会炸。** 改用 `contextlib.suppress(OSError)`。

---

## M2 — 多源采集、官方核实、diff、历史与失败恢复

**状态：** ✅ 完成

### 做了什么

- **三个目录适配器**：`free_llm_markdown`、`awesome_freellm_markdown`、
  `ailookup_markdown`（第三个因无许可证默认禁用）。
- **一个官方字段解析器**：`official_docs_generic`，对 Google AI Studio / Groq /
  OpenRouter 三个官方页面做**尽力而为**的字段提取，并保留短摘录供人工复核。
- **规范化**：别名归一、三态逻辑、四个协议独立存储、五个维度不合并。
- **变化检测**：幂等指纹（实体 + 字段 + 新旧值 + 证据版本），重复抓取不重复记事件。
- **失败恢复**：来源失败保留上次数据并更新错误状态；`null_result_streaks` 区分
  "从没成功过"与"成功过但这次是 0 条"。

### 证据

真实采集一次的结果：

```text
providers : 56
models    : 147
offers    : 166
claims    : 609
sources   : 2
```

离线异常测试覆盖：列顺序变化、缺字段、304、429、超时、结构异常、部分失败、
镜像来源族、首次导入幂等。

### 未验证的部分

- `ailookup_markdown` 适配器从未对真实页面跑过——来源因许可证被禁用。
  它只有 fixture 级测试。
- `official_docs_generic` 在真实采集里跑过（产出上面 56 个 provider），但
  官方页面改版会让它退化；抽取是尽力而为的，摘录 + 人工复核是兜底。

---

## M3 — CC Switch 预览、转换与复制回退

**状态：** ✅ 完成

### 做了什么

- `radar/cc_switch.py` 与 `site/static/js/cc-switch.js` 是**同一套规则的镜像实现**，
  两边都有测试盯着，改一边必须改另一边。
- 四种结果状态分开：`ready` / `ready_without_key` / `unsupported_protocol` /
  `missing_fields` / `conflict` / `unknown`。
- Deep Link 只在 `ready_without_key` 时给出；其余状态给手动复制回退。
- 导出走**字段白名单**，不是黑名单。

### 重要发现

测试最初假设"来源没声明协议"应该判成 `unsupported_protocol`。实际行为是：

| 情况 | 状态 | reason |
| --- | --- | --- |
| 来源**没声明**协议 | `unknown` | `protocol_unknown` |
| 来源声明了协议，但不匹配该 App | `unsupported_protocol` | `protocol_not_supported` |

**实际实现比我的假设更严谨**，所以测试被改写去断言并记录这个区分。
合并两者等于把"不知道"说成"不行"——那是不实陈述。

### 证据

- `tests/test_cc_switch.py` —— 33 项，含百分号编码往返测试，以及"endpoint 自带的
  `&` 不能注入额外参数"。
- 浏览器实测截图确认界面显示 **"来源未声明协议，无法判断是否兼容"**，
  而不是编造一个兼容结论。

---

## M4 — 全页面玻璃 UI、主题、收藏、iPad 适配

**状态：** ✅ 完成

### 做了什么

- 四层 CSS：`tokens.css` / `glass.css` / `components.css` / `pages.css`。
- 玻璃效果用 `@supports (backdrop-filter: blur(1px))` 渐进增强，**没有** WebGL、
  **没有**为玻璃效果引入框架。
- 浅色/深色主题，`prefers-reduced-transparency` 走不透明回退。
- 收藏存 `localStorage`（`radar.favorites.v1`）。
- 四个断点全部适配：≥1200 / 1024–1199 / 768–1023 / <768。

### 证据

`docs/screens/` 下 **106 张截图**（M10 后；M8 时 102 张，M7 重做时 97 张，M4 当时 19 张）：
8 个页面 × 6 个宽度（1440 / 1024 / 834 / 768 / 430 / 390）× 亮暗两主题 = 96，
外加线上部署与交互专项 6 张，以及 M10 的图片背景专项 4 张。由 `.work/shot.mjs` 驱动 Playwright 生成，
并且**在脚本内断言 `window.innerWidth` 真的等于目标宽度**——因为之前用别的工具
踩过坑，它静默产出了 8 张字节完全相同的截图，视口根本没生效。

同一脚本还断言：8 页 × 6 宽度**无横向溢出**、手机上表格变卡片且标签已生成、
桌面上表格仍是表格、底部胶囊可见、生效的 `backdrop-filter` 是哪一条。

> M4 当时的截图已被 M7 的重做取代并删除。旧文件名（`overview-*`、
> `directory-820-light`、`directory-desktop`）与现在不一致，留着会让文档自相矛盾。

`.work/flow.mjs` 跑 16 项真实用户流程断言：搜索收窄并反映到 URL、筛选、目录→详情
跳转、CC Switch 弹窗、切换目标 App、收藏持久化、深色主题刷新后保持、404、控制台无报错。
**16/16 通过。**

### 修掉的真问题

- **iPad 侧栏没隐藏。** `@media (max-width: 1023px)` 的注释写着"侧栏换成顶部导航"，
  但那条规则**根本没写**。结果 820px 下网格虽然变成单列，`.sidebar` 仍然占着
  `--sidebar-width`，正文被挤成窄条。修完页面高度从 5333px 降到 4299px，
  390px 下从 6552px 降到 5736px。

### 未验证的部分

- **真实 iPad Safari 没测过。** 自动化的视口模拟不能替代实机。
- **Windows 上的 CC Switch 没实际导入过。** 见 M6。

---

## M5 — CI、Actions、Pages、开源与 fork 教程

**状态：** ✅ 完成

### 做了什么

**工作流**（第 24 节要求）

- `.github/workflows/ci.yml`：`permissions: contents: read`，跑 lint + 测试 +
  离线构建 + 密钥扫描，上传产物。
- `.github/workflows/publish.yml`：**拆成三个 job**，让抓取不受信站点的那个
  不持有写权限 token。
  - `prepare` —— 只读；恢复状态缓存；首次运行显式报错并加 `--init`
  - `persist` —— `contents: write`；rebase-then-push，重试 3 次，**绝不 force-push**
  - `deploy` —— `pages: write` + `id-token: write`

**开源文件**（第 27 节要求）

- `README.md` —— 先讲"这个项目不是什么"
- `CONTRIBUTING.md` —— 三条最重要规则：不编造 / 不合并维度 / 不碰密钥
- `SECURITY.md` —— 三层威胁模型 + SSRF 防护表
- `LICENSE` —— MIT
- `THIRD_PARTY_NOTICES.md` —— 依赖许可 + 数据来源归属（中文 + 英文标题）
- `.gitignore`、`.github/ISSUE_TEMPLATE/` × 4

**文档**

- `docs/github-pages.md` —— 8 步 fork 部署，**第 6 步"勾选 force"是关键**
- `docs/sources.md` —— 独立性判定 + 抓取礼貌性
- `docs/architecture.md` —— 数据流图 + 为什么不引框架
- `docs/cc-switch.md` —— 版本钉定 + 四状态语义
- `docs/release-checklist.md` —— 发布闸门，C6 明确标注需真实仓库
- `data/seed/README.md` —— 空 seed 的用途与"它不是假数据"

**配置**

- `config/aliases.yaml` —— 54 条别名映射到 23 个 canonical，0 冲突
- `config/reviews.yaml` —— **初始为空**（如实反映"还没人逐条核对官方页面"）

### 离线全流程复现

```bash
python -m tests.validate_fixtures          # all fixtures validate
python -m radar.export_public --state tests/fixtures/state.minimal.json \
  --output .work/public-fixture --base-path /
python -m radar.build_site --data .work/public-fixture --out dist-fixture --base-path /
# "provider_count": 3
python -m tests.scan_secrets dist-fixture
# ok    no secret-shaped strings in 36 scanned file(s)
```

空 seed 路径单独验证，产出 `provider_count: 0` 且首页明确写着
"还没有成功完成过一次采集"——**空得诚实，不是空白**。

### 修掉的真问题

- **`--previous` 可以省略，导致拼错的路径和首次运行长得一样。** `--previous` 是可选
  参数，省略时 `_load_previous` 静默返回空状态并标记 `was_initial=True`。
  这意味着一个路径拼写错误会安静地把整个采集历史重置掉。改成必填，并让
  `previous_path is None` 直接报错。`publish.yml` 里首次运行只传了 `--init`、
  没传 `--previous`，一并修正。加了 `tests/test_collect_state.py`（11 项）守住。
- **`.gitignore` 里的裸 `state.json` 会吞掉 `data/seed/state.empty.json`。**
  裸模式在任意深度生效。改成锚定的 `/state.json` 与 `/data/state.json`，
  并用真实 git 仓库验证（不是靠推演 glob 语义）。加了
  `tests/test_repo_hygiene.py`（5 项）守住，其中一项会在 seed 被塞进假数据时失败。
- **文档里的命令参数写错。** `build_site` 的输入参数是 `--data` 不是 `--public`，
  `export_public` 的输出是 `--output` 不是 `--out`。照抄会直接 argparse 报错。
  已修正并逐字跑通。

### 测试规模变化

| 阶段 | 测试数 |
| --- | --- |
| M1 结束 | 199 passed, 1 skipped |
| M5 结束 | **215 passed, 1 skipped** |

新增：`test_collect_state.py`（11）、`test_repo_hygiene.py`（5）。

---

## M6 — 目标仓库部署与线上验收

**状态：** ✅ **完成 —— 站点已上线并通过线上验收**

### 线上验收（实测）

| 项目 | 证据 |
| --- | --- |
| **公开地址** | **https://duskpy.github.io/FreeAI-Radar/** —— **HTTP 200**，25757 字节 |
| 标题 | `<title>FreeAI Radar · 免费 AI API 目录</title>` |
| 8 个页面 | index / directory / provider / changes / sources / reviews / favorites / 404 —— **全部 200** |
| 资源 | `assets/css/glass.css`、`assets/js/app.js`、`assets/favicon.svg` —— 全部 200 |
| 线上数据 | **56 providers / 173 models / 192 offers** |
| `dataset_version` | `sha256:0735fb7289be2d9ebc759967ca22a0a8092ab1906f110ad5c58ad6241e2c8971` |
| 数据源 | 5 个全部 `ok`（修复前 `official-openrouter` 是 `parse_error`） |
| 日报 | `data/reports/2026-09-16.md` 200 |

**两个"看起来像 404"但其实是正确设计的现象，不要误判为故障：**

| 现象 | 真相 |
| --- | --- |
| `data/catalog.json` → 404 | **正确**。文件名内容寻址（真名 `catalog.<sha8>.json`），指针在 `data/manifest.json` 的 `catalog_url`。故意不给裸名，防止浏览器取到陈旧缓存 |
| `.nojekyll` → 404 | **正确**。它是 Pages 流水线消费的构建标记，不是从 artifact 提供的文件 |

### 已经真实完成的

| 项目 | 证据 |
| --- | --- |
| 目标仓库 | `https://github.com/DUSKpy/FreeAI-Radar` |
| 远端文件数 | **129**，与本地 `git ls-tree` **diff 为空** |
| 远端可达性 | README / LICENSE / pyproject / radar / schemas / site / tests / docs 抽查全部 HTTP 200 |
| Issue 模板 | 4 个全部在线（`bug-report` / `config` / `data-correction` / `new-source`） |
| Actions | **已启用** —— `ci` 与 `publish` 两个 workflow 均 `active` |
| Pages | **已部署** —— `build_type: workflow`、source `main`、`https_enforced: true` |

推送前修的问题：Windows 的 `core.autocrlf=true` 会把 CRLF 写进仓库，
Linux CI 随后会看到每个文本文件被改动。加 `.gitattributes`（`* text=auto eol=lf`）
并 `git add --renormalize`，实测索引里 CRLF 数为 **0**。

推送时做了一次可撤销的写权限探针，确认后立即撤销；清除历史前**先验证两条提交的
tree SHA 完全相同**（`2b830fb9…`），证明 `--force-with-lease` 不改变任何文件内容。

### 曾经的阻塞点：凭据缺少 `workflow` scope（已解除）

**解除方式：** 用户提供了带 `repo` + `workflow` 的凭据。推送成功后远端加入
`.github/workflows/ci.yml` + `publish.yml`，两个 workflow 均 `active`
（id `359315728` / `359315730`）。

**工作流运行全记录：**

| 运行 | 结论 | 说明 |
| --- | --- | --- |
| CI #1 | ❌ | ruff `Found 22 errors`（CI 装到 0.16.7、本地 0.8.6，新增 `UP042`） |
| CI #2 | ❌ | `ModuleNotFoundError: pydantic`（三个依赖未声明） |
| CI #3 | ✅ | 修复后全绿 `214 passed, 2 skipped` |
| publish #1 | ✅ | 首次部署成功，站点 404 → **200** |
| CI #4 | ✅ | 解析器修复后 `219 passed, 2 skipped` |
| publish #2 | ✅ | 携带修复重新采集，`official-openrouter` 由 `parse_error` → **`ok`** |

GitHub 原始报错（保留备查）：


```
refusing to allow an OAuth App to create or update workflow
`.github/workflows/ci.yml` without `workflow` scope
```

凭据属于 `DUSKpy`（仓库所有者），scope 为 `gist, read:org, repo`——
**有 `repo`，没有 `workflow`**。

对照实验（排除"是不是 API 路径本身的问题"）：

| 写入方式 | 普通路径 | `.github/workflows/*` |
| --- | --- | --- |
| `git push` | ✅ 成功 | ⛔ 被拒 |
| Contents API | ✅ HTTP 200 | ⛔ HTTP 404 |
| Git Data API（tree） | ✅ HTTP 201 | ⛔ HTTP 404 |

同一凭据、同一套 API，**只有 workflow 路径失败**。GitHub 在三条写入路径上
都强制拦截。这是有意的安全控制，我**不会绕过**。

**解锁：** 由**注入该凭据的一侧重新授权并勾选 `workflow` 权限**，或提供一份带
`workflow` + `repo` scope 的 classic PAT。之后我推送工作流、触发采集、完成上线验收。

> **更正：** 我早先写的 `gh auth refresh -h github.com -s workflow` 对当前凭据**大概率无效**，
> 不应写成必然可行的方案。实测该凭据用户名是 `x-access-token`、口令 40 字符无前缀，
> 属于**环境注入的集成凭据**，而非 `gh` 自己保存的用户登录（`gh auth status` 也因此显示"未登录"）。
> `gh auth refresh` 只能扩展 *用户 OAuth token*，管不到这份凭据。
>
> 判断解锁是否成功的唯一标志：`git push` 不再报 `without 'workflow' scope`。

#### 复核（本轮重新验证，非记忆）

本轮重新跑了一遍对照实验并**从公网新鲜克隆独立验证**，当时的阻塞情况如下
（**下表是阻塞期的历史快照，现已全部解除**，保留是为了说明排查依据）：

| 检查项 | 阻塞期结果 |
| --- | --- |
| `git push` 含 workflow | ⛔ 当时被拒：`without 'workflow' scope` |
| Contents API 写普通新文件（同一 token、同一 API） | ✅ HTTP **201** |
| Contents API 写 `.github/workflows/probe.yml` | ⛔ HTTP **404** |
| 公网 `.github/` 目录内容 | 当时只有 `ISSUE_TEMPLATE`，**无 `workflows/`** |
| Actions 运行次数 | 当时 **0** |
| `https://duskpy.github.io/FreeAI-Radar/` | 当时 **HTTP 404** |

**现已解除后的实测值：** `.github/workflows/` 含 `ci.yml` + `publish.yml`（均 `active`）；
Actions 已运行 6 次（CI 4 次 + publish 2 次）；站点 **HTTP 200**。

其中 404 而非 403 是 GitHub **有意的存在性混淆**：它不确认该路径存在，
而不是在回答"你权限不够"。这一细节值得记下——它让"权限不足"和"路径不存在"
在 API 层面无法区分，所以**不要用状态码推断原因**，要看 git-push 的原始报错。

> 探针产生的临时文件（`.probe-normal*`）已通过 Contents API 删除并复核根目录干净。
> 删除提交使远端历史前进了几个提交，但**已验证远端树与分叉点 tree SHA 完全相同**，
> 即内容零变化——因此用 rebase（而非 force-push）整合，没有掩盖任何冲突。

### 四种验收结果分开报告

| 验收项 | 结果 |
| --- | --- |
| 可部署代码 | ✅ **完成** —— 129 文件已推送，公网克隆逐文件核对一致 |
| 真实 Pages 发布 | ✅ **完成** —— `https://duskpy.github.io/FreeAI-Radar/` HTTP 200，8 页全通 |
| 真实 CC Switch 导入 | ⛔ **未测试** —— 需实机 |
| 真实 API 调用 | ⬜ 本版不要求（任务书：无用户 Key 时最后一项不作为强制门槛） |

---

## M7 — 液态玻璃重做与移动端重构

**状态：** ✅ 完成并**已上线**（Safari 真机仍需实测）

**触发：** 用户反馈"前端设计实在是太难看了，还不能自动适配屏幕"，
并要求做出 iOS 风格的液态玻璃。

### 线上验收（实测，2026-09-16）

推送 `69de18a` → CI `success` → 触发 `publish` → `success` → Pages 已更新。
**在真实部署上**（不是本地构建）实测：

| 检查 | 结果 |
| --- | --- |
| 8 页 HTTP | ✅ 全部 **200** |
| 新资源 | ✅ `responsive.css` / `table-cards.js` 均 **200** |
| 生效的材质 | ✅ `backdrop-filter: url("#radar-refract")`（真折射） |
| 环境层 | ✅ `body::before` **6 层**渐变 |
| 横向溢出 | ✅ 1440px / 390px 均 **0** |
| 目录页 facet | ✅ 7 项免费类型 / 5 项注册条件，**无载入中残留** |
| 手机表格→卡片 | ✅ `tr` 计算值为 `block`；**21/21** 单元格带 `data-label`；去重标签 `上下文窗口 / 声明能力 / 协议` |
| 伪元素真的渲染 | ✅ `getComputedStyle(td,'::before').content` == `"上下文窗口"` |
| 底部胶囊 | ✅ `display:block`、`border-radius:999px`、带折射 |
| manifest 大小写 | ✅ `catalog_url` = `/FreeAI-Radar/...`，**200 可解析** |

线上截图（真实部署，含完整 56 个 provider 的数据）：

- `docs/screens/live-1440-deployed.png`
- `docs/screens/live-390-deployed.png`
- `docs/screens/live-provider-390-deployed.png`

### 诊断（先量后改）

对着真实 CSS 和截图逐条查，找到四个具体问题，不是"感觉不好看"：

1. 玻璃是 **78% 不透明**的白色 + 只有 18px 模糊 —— 那是一块白板，不是玻璃。
2. 字号**全部写死 px**，全项目 `clamp()` **0 处**、`rem` **1 处**。
3. 只有 4 个断点、**0 个容器查询**，且 1024–1199px 区间**完全没有规则**。
4. 背景环境光是 22% 透明度叠在 `#eef3f9` 上，**根本看不见** ——
   玻璃没有东西可折射，所有折射效果都白做。

另有一条**只在验证过程中才暴露的产品缺陷**，影响比 UI 更大：
`_rebase_urls()` 改了内存里的 manifest，但 `_copy_data()` 逐字复制源文件，
**改写从未落盘** —— 见 `docs/delivery.md` 第 4 节第 17 条。

### 做了什么

- **真折射**：同一文档内联 SVG 滤镜链 —— `feTurbulence` 造位移场
  （不重复、不需要 PNG 资源）→ `feDisplacementMap` → 按通道分离 +
  `feOffset` 反向偏移 + `feBlend mode="screen"` 得到色散边缘 →
  提饱和 + 提亮。只用在导航和面板上，**不用在文字和数据表上**。
- **诚实的浏览器分流**：`@supports (backdrop-filter: url(#radar-refract))`
  命中则叠加折射（模糊折进滤镜链，避免二次模糊）；否则给加厚毛玻璃。
- **容器查询**取代断点式尺寸：一个组件在窄侧栏和宽主栏里各按自己的宽度排，
  这是唯一正确的做法。
- **流式字号**：`clamp()` 全量替换固定 px；补上 1024–1199 与横屏手机两个区间。
- **表格 → 卡片**：`thead` 视觉隐藏 + `td::before { content: attr(data-label) }`，
  列名由 `table-cards.js` 抄写并用 `MutationObserver` 处理异步行。**没有改任何页面模块。**
- **底部导航改成 iOS 浮动胶囊**，5 项，含安全区。
- **补上缺失的外观入口**（见下方缺陷 13）。
- **外观面板**用原生 `<dialog>` + `showModal()`：焦点捕获、Escape 关闭、
  顶层渲染（因此不会被页面的 `backdrop-filter` 裁切）都是白拿的。

### 证据

| 检查 | 结果 |
| --- | --- |
| 横向溢出扫描 | ✅ 8 页 × 6 宽度 **全部无溢出** |
| 截图 | ✅ 97 张（8 页 × 6 宽度 × 2 主题 + 外观面板 1 张） |
| 表格变卡片（手机） | ✅ 8/32 视图，标签已生成 |
| 表格仍是表格（桌面） | ✅ 32/32 视图 |
| 底部胶囊可见（手机） | ✅ 32/32 视图 |
| 生效的 `backdrop-filter` | ✅ `url("#radar-refract")` |
| 折射降级（模拟 Safari） | ✅ `blur(40px) saturate(1.8) brightness(1.08)`，7/7 卡片，0 溢出 |
| 外观面板 | ✅ 触达 66×49px、顶层打开、5/5 控件有 48px 触控目标、三项设置刷新后保持、Escape 可关 |
| 单测 | ✅ `231 passed, 1 skipped`（本轮 +4） |
| ruff / format | ✅ 钉住的 0.16.7 下全绿 |
| UI 审计 | ✅ 8 页 × 3 宽 = 24 视图，**0 处问题** |
| 横向溢出 | ✅ 8 页 × 6 宽，全部 0 |
| 筛选开关行为 | ✅ 手机开→关可逆、桌面隐藏、`aria-expanded` 同步 |

---

## M8 — 界面缺陷清理（可见的与不可见的）

这一轮的起点是"继续改前端 UI"，但前三次修复都不是改好看程度，
而是在**找出界面在骗用户的地方**。

### 1. 两个网格被反向分配（`2609ef5`）

CSS Grid 的轨道按 **DOM 源码顺序**分配。`.directory` 写的是
`2609ef5` 之前的 `grid-template-columns: 260px minmax(0, 1fr)`，
而模板里第一个子元素是 `.directory__main`、第二个才是 `.facets`。
结果：1440px 下结果卡片被压成 **260px**，筛选栏拿到 **846px**。

`.report` 同理 —— 日报正文被压成 240px、高 2259px 的一条，
而日期索引占了 864px。

两处都没有触发任何既有检查：元素都在、HTML 合法、不溢出、截图"看着有内容"。
发现方式是写了一个脚本，专门标记"靠前的子元素比靠后的兄弟窄 2.2 倍以上"
的网格。见 `tests/test_build.py::TestLayoutTracksMatchTheDomOrder`。

### 2. 桌面端有一个点了没反应的"筛选"按钮（本轮）

`.facets__toggle` 的隐藏规则写成了单类选择器：

```css
.facets__toggle { display: none; }   /* components.css 第 215 行 */
```

但按钮的类名是 `class="btn btn--small facets__toggle"`，而
`.btn { display: inline-flex }` 在**同一个文件的第 473 行**。
两者特异度都是 (0,1,0)，于是级联只能靠源码顺序分胜负 —— **`.btn` 赢**。

后果：1440px 和 1024px 下，筛选栏本来就一直可见，
却仍然渲染出一个 53×34 的"筛选"按钮，点击只切换 `aria-expanded`，
面板纹丝不动。**一个看起来可交互、实际什么都不做的控件。**

这个 bug 连注释都写错了 —— 第 213 行的注释明确写着
"在桌面端隐藏，因为筛选栏始终可见"，而代码做的正好相反。

改成两个类（`.btn.facets__toggle`）把特异度提到 (0,2,0)，
胜负不再取决于哪条规则先写。`responsive.css` 里恢复显示的规则同步改成两个类，
否则下一轮重构会在反方向重新引入同一个问题。

排查过程本身也有两个坑，记下来：

- **`rule.media` 判断真值是不可靠的** —— `CSSStyleRule` 也有一个空的
  `media`（`MediaList`，转字符串是 `""`），所以用真值判断会把**每一条**
  普通规则都误报成"有媒体条件"。正确写法是 `rule instanceof CSSMediaRule`。
  一开始的 CSSOM 遍历用了错的写法，返回的结果自相矛盾。
- **数花括号也不可靠** —— 嵌套的 at-rule 让深度计算失去意义，
  脚本对每个 at-rule 都报 depth 0。

最终用 CDP 的 `CSS.getMatchedStylesForNode` 拿到权威答案：
`.btn` 与 `.facets__toggle` 都是 `origin: regular`、`media: (none)`。

### 3. 回归测试是**先验证会失败**才留下的

新增的 4 个测试里，3 个选择器测试在把缺陷改回去后**确实失败**，
改回修复后才通过。第 4 个（断言元素带 `btn` 类）用来防止
标记里去掉 `.btn` 导致两类的选择器静默失配。

这里有一个值得记的教训：第一版测试用 `in` 字符串判断，
结果**在有缺陷的代码上也是通过的** —— 因为断言匹配到了
解释这条规则的注释文本（注释里引用了 `.btn.facets__toggle`）。
断言前必须先剥掉 `/* ... */`。**会读散文的测试不是测试。**

### 4. 顺手排查了同类隐患

写了个脚本扫描所有"单类选择器 + `display`"的重复声明，
确认其余各处（`.sidebar`、`.topnav`、`.bottomnav`、`.facets` 等）
的分歧都发生在**媒体查询内部**，那是刻意的响应式覆盖，不是 bug。
只有 `.facets__toggle` 这一处是在无条件规则之间打架。

---

### 修掉的真问题

见 `docs/delivery.md` 第 4 节第 13–16 条：手机上外观控件完全不可达、
评审页 390px 溢出 153px、页脚 SHA 在 834/1024px 溢出、
短面板被拉伸成满屏 776px（真因是 UA 给模态 `dialog` 设了上下两端 inset）。

这几条有一个共同点：**界面看起来是对的**，但手机用户够不到、页面被撑宽、
面板空了一大块。只看截图发现不了，是机械扫描找出来的。

### 未验证的部分

- **真机 Safari / Firefox** —— 降级路径是用原地改写 CSS 的方式模拟的，
  逻辑等价但不是真机。
- **真机 iOS 的 `env(safe-area-inset-*)`** —— 桌面浏览器下这些值是 0。

---

## M9 — 对比度余量：一个"通过"但只多 0.07 的配色

M8 之后，浏览器逐像素审计（930 个文本元素 × 6 页 × 2 主题 × 整页高度）
结论是全部通过 WCAG AA。为了把这件事固化成毫秒级的离线测试，
新增了 `tests/test_token_contrast.py`。**写这个测试的过程本身暴露了三个问题**，
其中两个是我自己造成的。

### 1. 我断言了一组根本不存在的配对

第一版 `PAIRINGS` 里写了 `--text` on `--surface-sunken`。
grep 完才发现：`--text` 从来没有落在下沉表面上，
它只出现在 `--surface` 和 `--surface-soft` 上。

这条断言在 14.49:1 通过，所以测试是绿的 —— 但它**什么都没覆盖**。
更糟的是它占了一个位置：真正会发生的配对
（`--text-subtle`、`--text-muted` on `--surface-sunken`）当时完全没有被断言。

**对着不存在的组合写的绿色断言，比不写更坏，因为它看起来像覆盖。**

### 2. 收紧之后，我的新守卫又抓到了我自己的两处臆造

为了防止再犯，加了一个守卫：每一条被断言的配对，都必须在样式表里
找得到对应声明。守卫第一次运行就红了，指出两条：

```
--text-subtle on --surface
--text-subtle on --surface-soft
```

这两条其实是**真实的**，但形式不同：`.sidebar__label`、
`.topbar__eyebrow`、`.sitefoot__disclaimer` 都设了 `color: var(--text-subtle)`
而背景由祖先（或页面本身）决定，没有任何单条规则同时包含两者。

所以配对有两种形态，守卫也必须分开处理：

- **DECLARED** —— 同一条规则里同时有 `color:` 和 `background:`，
  可以直接 grep（`--text-subtle`/`--surface-sunken` 等 4 组）。
- **INHERITED** —— 文字色由元素设定、表面由祖先决定，单规则 grep 看不见。
  对这类只能退到"两个 token 都确实在用"这个可证伪的主张。

写一个假的 grep 去"证明"继承配对，等于把守卫变成摆设。

### 3. 真正的发现：最紧的一处只多 0.07

配对校准之后，数值摊开来看，整个体系里最紧的一处是：

| 配对 | 改前 | 改后 |
| --- | --- | --- |
| 浅色 `--text-subtle` on `--surface` | 5.33 | 6.40 |
| 浅色 `--text-subtle` on `--surface-soft` | 5.01 | 6.01 |
| **浅色 `--text-subtle` on `--surface-sunken`** | **4.57** | **5.49** |
| 浅色 `--text-muted` on `--surface-sunken` | 6.39 | 6.39 |

`--text-subtle` 用在 11px 的辅助文字上（`.navlink__count`、`.sidebar__label`、
`.topbar__eyebrow`），所以 4.5:1 是硬线。**4.57 通过，但只多 0.07**：
只要有人微调任一 token，就会跌破 AA，而且不会有任何东西报警。

`--text-subtle` 由 `#5c6c85` 改为 `#526073`，最差情况从 4.57 提到 5.49。
同时与 `--text-muted`（`#47566c`）仍相差 28，两级灰阶肉眼可分；
再深就会塌成同一级（`#4f5c6e` 只差 16，`#4c5867` 只差 12）。

### 4. 一个关于"证据"的教训

验证时我用 `.navlink__count` 作为 `--text-subtle`/`--surface-sunken`
的证据。但逐像素测出来是 `10.06:1`、`text=rgb(13, 61, 120)` —— 那是
`--accent-fg`，不是 `--text-subtle`。

原因是这个元素有**两个状态**：

- 非激活（`components.css:129`）：`--text-subtle` on `--surface-sunken`
- 激活（`components.css:144`，`[aria-current="page"]`）：
  `--accent-fg` on `rgba(255,255,255,0.66)`

`directory.html` 上唯一带数字的 navlink 恰好是激活的那个，
所以不特意构造的话，量到的永远是第二个状态。
而且非激活的计数是 `0x0`（"我的收藏"没有数字），**根本不渲染**。

我最初的 grep 只找到 129 行，却以为探针量到了它。修正做法：
注入一个计数让非激活态真正渲染，再测 —— 得到
`light 5.49:1 text=rgb(82,96,115) bg=rgb(232,238,247)`，
和 token 计算完全吻合，背景正是 `--surface-sunken`。

**"我 grep 到了这条规则"和"我量到了这条规则"是两件事。**

### 5. 守卫本身也要证明会失败

新增的守卫全部逐条注入缺陷验证过，避免"守卫不会失败"这种循环：

- 重新加回 `--text`/`--surface-sunken` → 红
- 在 `DECLARED_PAIRINGS` 里写一条没有规则支持的配对 → 红
- 指向一个从不作为背景使用的 token（`--radius-pill`）→ 红，
  报 `--radius-pill is never used as a background`

最后一次注入很关键：第一次尝试用了不存在的 token 名（`--madeuptoken`），
被"token 是否存在"那条先拦下了，**所以并没有真正验证到"用途检查"**。
换成存在但从不作背景的 token 才真正证明了它。

---

## M10 — 图片背景：一个自己制造的无障碍回归，和四个错误假设

用户反馈三件事：**页面在宽屏下不铺满**、**搜索图标与占位文字重叠**、
以及**背景太干净，液态玻璃看不出来**，并建议把一张照片放进背景，
同时要求**后续可以自己在图片背景和纯色背景之间切换**。

前两件是明确的缺陷（见 `docs/delivery.md` 第 21、22 条）。第三件是新功能，
而它把"文字可读"从一个我们完全掌控的性质，变成了**取决于用户选哪张图**的性质。

### 1. 新功能引入的回归：40 个元素跌破 AA

纯色基线是 1944/1944 全通过。加上照片后：**37 个深色 + 3 个浅色失败**。

失败方向在两个主题里是**相反**的：

- **深色怕亮图**：亮图透过半透明面板把面板提亮，浅色文字失去对比。
  `.sidebar__label` 从 5.97:1 掉到 3.48:1。
- **浅色怕暗图**：暗图把面板压暗，深色文字失去对比。`.howto__body` 掉到 4.34:1。

这意味着**只对着我们自带的那张夜景调参是不够的** —— 它恰好只在两个方向上
各覆盖一半。换一张图就会复发，而且不会有任何东西报警。

### 2. 四次错误，一次比一次更像对的

定位这个问题的过程比修它更有价值，因为**我错了四次**：

**错误一：把原因推给图层顺序。** 我认为 `.env-photo`（`z-index: -2`）
被 `body::before/::after`（`-1`）挡住了。写 `.work/layer-probe.mjs` 对比
同一页两种模式下的实际像素：背景区域差值高达 117，**照片明明可见**。
真相是 `body` 的背景会**传播到 canvas**，画在所有负 z-index 层之下。
**推理错了，像素是对的。**

**错误二：抓住一个"显然正确"但实测为零的杠杆。**
`--glass-brightness` 看起来是完美工具：压暗被采样的背景，
既保住透明（照片仍从面板透出）又降亮度。实测 **48% 和 62% 给出逐字节相同的结果**，
同样 6 个失败。因为 `.glass--nav` / `.glass--panel` 用的是
`backdrop-filter: url(#radar-refract)`，它**替换**整条滤镜链而不是追加，
brightness 从未到达那几个失败元素。

**错误三：坏探针把我送错了方向。** 为求快写的 `.work/contrast-photo.mjs`
报"1131 个里 79 个失败"，且"填充色"恰好等于 `--text` 本身 —— 物理上不可能。
原因是 `node.screenshot()` 作用在**内联元素**上会连兄弟内容一起截。
**坏探针比没有探针更危险，它会让你去改一个错的 token。**

**错误四：测"最坏情况"时把被测的保护措施一起删了。**
注入"纯白照片"时替换了 `.env-photo` 的整条 `background-image`，
**连第一层的 scrim 一起删掉**，于是"最坏情况"量到 1.69:1 的荒谬结果。
**构造最坏情况必须只替换被测变量。**

外加一个自造假警报：`bare-text.mjs` 报"41 个链接直接落在页面背景上"，
单独复查后发现 61 个文本链接里**只有 1 个**（跳过链接，自带背景）没有绘制祖先。
**探针的结论必须能被第二个探针推翻，否则它只是一个观点。**

### 3. 修法：把 scrim 按最坏的照片定尺

scrim 不是装饰，是**把不可控输入约束到可控区间**的装置。因为
`.howto__body` 和 `.directory__count` 直接落在页面背景上（没有面板可以加厚），
它们的 `--text-muted` 就成了 scrim 强度的唯一约束 —— 于是这个值可以**算**出来：

| 主题 | 最坏照片 | 约束 | 改前 | 改后 |
| --- | --- | --- | --- | --- |
| 浅色 | 纯黑 | 背景亮度 ≥ 0.583 | 82% → 4.34:1 | **88% → 5.00:1** |
| 深色 | 纯白 | 背景亮度 ≤ 0.073 | 72% → 4.43:1 | **82% → 5.16:1** |

深色主题另外**把三档玻璃整体加厚**（`--glass-nav-bg` 44% → 82%、
card 52% → 84%、plate 88% → 94%），保持三档之间的相对关系与色相不变。
这正是 iOS 在内容很花时的做法。浅色主题不需要，因为近白色 88% 的 scrim
只让暗照片把背景压暗一点点，而**压暗反而提高深色文字的对比**。

代价必须写明：**浅色主题下照片只剩 12% 透出，读起来是一层很淡的色晕。**
这是"对任意照片保证 AA"的价格，也是这个功能保持 opt-in 的原因。
把 scrim 调低换照片清晰度是可行的，但那样保证就退化成"对自带那张图成立"。

### 4. 一个修 bug 时才发现的新陷阱

新覆盖块 `[data-theme="dark"][data-backdrop="photo"]` 是 **(0,2,0)**，
而"降低透明度"的 token 块原本是 **(0,1,0)** —— 于是它**会输**，
同时选"降低透明度"和"图片背景"会**悄悄退回半透明面板**，
恰好是唯一绝对不能那样的组合。

改法是把后者加上 `:root` 前缀提到 (0,2,0)，靠源码顺序决定胜负
（`glass.css` 里元素级的 `background: var(--surface)` 本来就在 (0,2,0)，
所以渲染从未出错，但 token 状态会自相矛盾）。

**加一条高特异度覆盖时，必须检查它压过了谁。** 这条写进了测试。

### 5. 验证

- 逐像素复测 1944 个元素（6 页 × 2 主题 × 整页高度）：**全部通过**，最差 4.80:1。
- 结构最坏情况（合成纯白 / 纯黑图）另行验证，不依赖自带的那张照片。
- 新增 `tests/test_photo_backdrop_contrast.py` 12 个测试把算术固化到离线，
  并**注入 5 处缺陷验证全部被捕获**：浅色 scrim 回 82%、深色 scrim 回 72%、
  nav 档回 44%、card 档回 52%、降低透明度选择器退回 (0,1,0)。
- 截图矩阵重新生成 96 张，另加 4 张照片模式截图作为该功能的交付证据。

---

## M11 — 液态玻璃：让它流动，并把透过度做成滑杆

用户反馈："目前的液态玻璃没有苹果的流动感，完全就是定制的感觉，不会因为背景的变化而变化"，
并指出 iOS 27 已经可以自主调节玻璃透过度。这两点各自对应一个具体缺陷，不是审美分歧。

### 1. 折射不流动：位移场是**静态**的

`feTurbulence` 生成位移贴图后就没有再变过。静态位移场 = 一张印在面板上的固定花纹，
眼睛会把它读成"贴上去的装饰"，这正是"定制感"的来源。

参考实现（`dpawlikowski/liquid-glass`，纯 CSS+SVG，与本技术栈一致）的
turbulence 是**带 `<animate>` 的**。本项目之前没有。

修法：给 `baseFrequency` 加 24s 的 SMIL 动画，并动画 `baseFrequency` 而不是
`feDisplacementMap` 的 `scale` —— **改 scale 只是让同一个场呼吸，
改 frequency 才会重新生成场，弯折的边缘才会真的移动。**

代价是真实的（fractalNoise 每帧重算），所以周期刻意放慢到 24s，
且该滤镜只作用于浮动导航面，从不作用于卡片列表。

SMIL 无法用 CSS media query 关闭，所以 `theme.js` 用 `pauseAnimations()` /
`unpauseAnimations()` 接上"减弱动效"偏好（含 OS 级 `prefers-reduced-motion`）。
已验证：时钟会走，`pauseAnimations()` 后时钟冻结。

### 2. 透过度只有两段

原来是 `降低透明` 复选框（对应 iOS 26.1 的 Clear/Tinted 两段）。
**两段的问题**：觉得玻璃"稍微有点透"的人，只能选择彻底放弃玻璃。

iOS 27（WWDC 2026）把这条做成了**无段滑杆**，理由是"多少玻璃才对"没有唯一正确答案。
本项目照做：

- 把"clear 端颜色"与"色调"拆开：`--glass-*-clear` 是设计值，`--glass-tint` 是 0–100% 的滑杆
- 渲染值 `--glass-*-bg` = `color-mix(in srgb, var(--surface) var(--glass-tint), var(--glass-*-clear))`
- tint=0% 就是原设计，tint=100% 就是旧的"降低透明"，**一个滑杆统一了两套模式**
- `:root, [data-theme="dark"]` 用逗号选择器写一次，lighten/dark/照片三套 clear 值自动跟随

`color-mix()` 不支持时回退到 clear 值（即原设计）。
不支持 `backdrop-filter` 的浏览器本来就拿不透明回退，所以这条路径无风险。

### 3. 扩散不随背景变化

iOS 27 修的正是这点：**玻璃对背后复杂内容的扩散要更强**（不是更弱）。
第一版的方向反了——保持清透让复杂背景直接透上来。

照片就是"复杂内容"的定义，所以 `:root[data-backdrop="photo"]` 下
`--glass-blur` 24px → 34px、`--glass-blur-strong` 40px → 54px。
纯色光斑背景没有多少高频细节需要抑制，保持原值。

### 验证

- `.work/glass-verify.mjs` **16/16**：动画存在且时钟前进、暂停有效；
  滑杆存在、0/50/100 三档渲染值各不相同、100 时不透明、中间值可达、持久化且刷新后保留
- 逐像素审计：照片模式 1944 元素**全部通过** AA
- `264 passed` · ruff 全绿

### 过程中抓到的一个真 bug

滑杆从 100% 调回 50% 时，只移除了 `data-transparency` 属性却没清掉存储的
`radar.transparency` 键，于是 `currentTint()` 下次仍返回 100 ——
**用户把滑杆调回来，刷新后又弹回实色。** 两个键表达同一个概念，
写其中一个就必须清另一个。是浏览器验证脚本抓到的，离线测试看不见。

---

## 已知缺口 / Known gaps

按重要性排序，不掩饰：

1. **真实 iPad Safari 未测** —— 只有视口模拟。
2. **真实 CC Switch 导入未测** —— Deep Link 的百分号编码有单元测试，
   但没有在真机上点过。
3. **`config/reviews.yaml` 为空** —— 还没有人工复核过任何字段，
   所以线上 `needs_review=0` 是"没有待复核项"，不等于"已复核完"。
4. **`ailookup_markdown` 未对真实页面跑过** —— 来源因许可证未确认而禁用。
5. **`official_docs_generic` 是尽力而为的** —— 官方页面改版会退化，
   摘录 + 人工复核是兜底，不是保证。**已实测过一次退化**：噪声剥离误删正文，
   详见 `docs/delivery.md` 第 4 节第 9 条。
6. **连通性从未验证** —— `call_status` 线上 192/192 全是 `untested`。
7. **Safari / Firefox 上液态玻璃没有折射** —— 平台边界，不是缺陷。见
   `docs/delivery.md` 第 6.1 节。Chromium 系有真折射，其他浏览器拿到的是
   加厚的毛玻璃，不是"坏掉的玻璃"。

---

## 下一步

1. **在真实 iPad 上打开一次**，在装有 CC Switch 的 Windows 上导入一次 ——
   这两条从 M6 起就挂着，是模拟视口和单元测试都替代不了的。
2. 逐步填充 `config/reviews.yaml`，每个条目都要有真实 `evidence_url`。
3. 确认 `free-llm-resources` 的许可证，决定是否启用那个适配器。
4. **换一张照片背景后重跑一次对比度审计**。scrim 已经按"任意照片的最坏情况"
   定尺，所以理论上不需要 —— 但"理论上"不是证据。命令：
   `RADAR_BACKDROP=photo node .work/contrast-fullpage.mjs`。

### 一条已知且接受的审计发现

`.work/ui-audit.mjs` 在 `changes@phone` 上报告一个 64×17 的链接
（"结构化报告"）小于 44px 触摸目标。它位于一句话内部
（`changes.html:136`："完整列表请查看<a>结构化报告</a>。"），
属于 WCAG 2.5.8 明确豁免的 **inline** 情形 —— 给它加内边距会破坏行内排版。
审计脚本目前对所有链接套用同一个 44px 阈值，所以这是**误报**，不是缺陷；
要么接受，要么给脚本加"行内链接豁免"。
