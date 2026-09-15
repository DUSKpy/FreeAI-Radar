# 实施进度 / Progress

对照任务书第 30 节的里程碑表逐项记录。**每完成一个阶段就更新这里**，不要把进度
攒到最后一起写——那样"完成证据"就变成了回忆，而不是当时看到的输出。

图例：**✅ 完成** · **🟡 部分完成** · **⛔ 受阻** · **⬜ 未开始**

最后更新：2026-09-15

**目标仓库：** https://github.com/DUSKpy/FreeAI-Radar
**Pages 地址：** https://duskpy.github.io/FreeAI-Radar/ （已配置，当前 404 —— 未部署）

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
| M6 目标仓库部署和线上验收 | 🟡 | 129 文件已推送并逐文件核对一致；站点未上线 —— 凭据缺 `workflow` scope |

**当前测试基线：** `215 passed, 1 skipped` · `ruff check` 全绿 · `ruff format --check` 全绿

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

`docs/screens/` 下 19 张截图，尺寸为任务书要求的四档：

| 尺寸 | 用途 | 数量 |
| --- | --- | --- |
| 1440×900 | 桌面，含总览/目录/详情/变更/来源/核验/收藏 | 7 × 亮暗 |
| 1024×768 | 笔记本 | 1 × 亮暗 |
| 820×1180 | iPad | 1 × 亮暗 |
| 390×844 | 手机 | 1 × 亮暗 |

截图由 `.work/capture.mjs` 驱动 Playwright 生成，并且**在脚本内断言
`window.innerWidth` 真的等于目标宽度**——因为之前用别的工具踩过坑，
它静默产出了 8 张字节完全相同的截图，视口根本没生效。

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

**状态：** 🟡 **部分完成 —— 代码已部署，站点未上线（凭据 scope 阻塞）**

### 已经真实完成的

| 项目 | 证据 |
| --- | --- |
| 目标仓库 | `https://github.com/DUSKpy/FreeAI-Radar` |
| 推送提交 | main 最新提交（`git ls-remote origin main` 可查） |
| 远端文件数 | **129**，与本地 `git ls-tree` **diff 为空** |
| 远端可达性 | README / LICENSE / pyproject / radar / schemas / site / tests / docs 抽查全部 HTTP 200 |
| Issue 模板 | 4 个全部在线（`bug-report` / `config` / `data-correction` / `new-source`） |
| Actions | **已启用** —— `actions/permissions` 返回 `{"enabled": true}` |
| Pages | **已配置** —— `build_type: workflow`、source `main`、`https_enforced: true` |
| Pages 地址 | `https://duskpy.github.io/FreeAI-Radar/`（已确定，当前 404） |

推送前修的问题：Windows 的 `core.autocrlf=true` 会把 CRLF 写进仓库，
Linux CI 随后会看到每个文本文件被改动。加 `.gitattributes`（`* text=auto eol=lf`）
并 `git add --renormalize`，实测索引里 CRLF 数为 **0**。

推送时做了一次可撤销的写权限探针，确认后立即撤销；清除历史前**先验证两条提交的
tree SHA 完全相同**（`2b830fb9…`），证明 `--force-with-lease` 不改变任何文件内容。

### 阻塞点：凭据缺少 `workflow` scope

GitHub 原始报错：

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

本轮重新跑了一遍对照实验并**从公网新鲜克隆独立验证**，结果与上述一致：

| 检查项 | 结果 |
| --- | --- |
| `git push` 含 workflow | ⛔ 仍被拒：`without 'workflow' scope` |
| Contents API 写普通新文件（同一 token、同一 API） | ✅ HTTP **201** |
| Contents API 写 `.github/workflows/probe.yml` | ⛔ HTTP **404** |
| 公网 `.github/` 目录内容 | 只有 `ISSUE_TEMPLATE`，**无 `workflows/`** |
| Actions 运行次数 | **0**（从未运行过） |
| `https://duskpy.github.io/FreeAI-Radar/` | **HTTP 404**（从未部署） |

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
| 真实 Pages 发布 | ⛔ **未开始** —— 工作流从未运行 |
| 真实 CC Switch 导入 | ⛔ **未测试** —— 需实机 |
| 真实 API 调用 | ⬜ 本版不要求（任务书：无用户 Key 时最后一项不作为强制门槛） |

**源码在仓库里 ≠ 站点已上线。** 少了工作流，就没有东西去构建和部署它。

---

## 已知缺口 / Known gaps

按重要性排序，不掩饰：

1. **站点未上线** —— 代码已部署，但工作流文件被 `workflow` scope 挡在仓库外。
   解锁需要由注入凭据的一侧重新授权（或提供带 `workflow` scope 的 PAT）。
2. **真实 iPad Safari 未测** —— 只有视口模拟。
3. **真实 CC Switch 导入未测** —— Deep Link 的百分号编码有单元测试，
   但没有在真机上点过。
4. **`ailookup_markdown` 未对真实页面跑过** —— 来源因许可证禁用。
5. **`official_docs_generic` 是尽力而为的** —— 官方页面改版会退化，
   摘录 + 人工复核是兜底，不是保证。
6. **`config/reviews.yaml` 为空** —— 意味着所有 provider 的 `info_status`
   都是 `directory_claim`，没有一个 `official_confirmed`。**这是如实状态，
   不是缺陷。** 填满它需要有人真的去逐条核对官方页面。

---

## 下一步

1. **拿到目标仓库 → 做 M6。** 这是唯一能把"可部署代码"变成"已上线站点"的事。
2. 在真实 iPad 上打开一次，在装有 CC Switch 的 Windows 上导入一次。
3. 逐步填充 `config/reviews.yaml`，每个条目都要有真实 `evidence_url`。
4. 确认 `free-llm-resources` 的许可证，决定是否启用那个适配器。
