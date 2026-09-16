# 第三方声明 / Third-Party Notices

FreeAI Radar 的**代码**以 MIT 许可发布（见 [LICENSE](LICENSE)）。MIT 只覆盖本仓库作者编写的代码，**不覆盖**本仓库聚合的第三方事实数据，也不覆盖下列第三方依赖。

本文件分三部分：

1. [依赖库](#1-依赖库) —— 构建与测试时用到的软件包
2. [数据来源](#2-数据来源) —— 目录型来源与官方核验来源
3. [我们不声称拥有的内容](#3-我们不声称拥有的内容)

---

## 1. 依赖库

### 1.1 运行时依赖

站点本身**没有运行时依赖**——发布出去的只有 HTML、CSS、原生 ES Module 和 JSON，浏览器直接读，没有打包、没有框架、没有 CDN。下表中的包只在构建/采集阶段运行。

| 包 | 版本 | 许可证 | 用途 | 项目地址 |
| --- | --- | --- | --- | --- |
| [httpx](https://pypi.org/project/httpx/) | 0.28.1 | BSD-3-Clause | 采集阶段的 HTTP 客户端（超时、重定向上限、HTTP/2 关闭、连接复用） | https://github.com/encode/httpx |
| [PyYAML](https://pypi.org/project/PyYAML/) | 6.0.2 | MIT | 解析 `config/*.yaml` | https://github.com/yaml/pyyaml |
| [Jinja2](https://pypi.org/project/Jinja2/) | 3.1.5 | BSD-3-Clause | 静态页面模板渲染 | https://github.com/pallets/jinja |
| [pydantic](https://pypi.org/project/pydantic/) | 2.x | MIT | `radar/models.py` 中所有采集记录的 schema 层（`ConfigDict`、`field_validator`） | https://github.com/pydantic/pydantic |
| [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) | 4.12.3 | MIT | 解析官方 HTML 文档页（`official_docs_generic`） | https://www.crummy.com/software/BeautifulSoup/ |
| [lxml](https://pypi.org/project/lxml/) | 5.3.0 | BSD-3-Clause | BeautifulSoup 的解析后端 | https://lxml.de/ |

> **Jinja2 的许可证**：PyPI 元数据里没有逐一列出 SPDX 标识，以 classifiers 为准；上游仓库使用 BSD-3-Clause。如需逐字确认请查阅上表中的项目地址。
>
> **此表曾与 `pyproject.toml` 不一致**：`pydantic`、`beautifulsoup4`、`lxml` 三个包被代码导入，
> 但有一段时间没有写进 `dependencies`。本地开发机碰巧装有它们，所以测试一直是绿的；
> 直到 CI 用**真正干净的安装**才暴露出来（`pip install -e .[dev]` 不会带上未声明的包）。
> 现已全部声明。教训：改了 `import` 就要同步 `pyproject.toml`，并且**用干净环境验证**。

### 1.2 开发依赖

以下包**不出现在发布产物中**，只在 CI 与本地开发时使用：

| 包 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| [pytest](https://pypi.org/project/pytest/) | 8.3.4 | MIT | 测试运行器（含 `network` marker 分离联网测试） |
| [ruff](https://pypi.org/project/ruff/) | 0.8.6 | MIT | Lint 与格式化检查 |
| [jsonschema](https://pypi.org/project/jsonschema/) | 4.23.0 | MIT | 按 Draft 2020-12 校验 fixture 与产出的 JSON |

### 1.3 可选依赖

| 包 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| [playwright-core](https://www.npmjs.com/package/playwright-core) | 1.63.0 | Apache-2.0 | **仅**用于本地/CI 的截图与浏览器流程验证（`.work/capture.mjs`、`.work/flow.mjs`）。不是构建依赖，站点不使用它。 |

### 1.4 构建环境

| 组件 | 版本 | 许可证 |
| --- | --- | --- |
| CPython | 3.11+（CI 用 3.13） | PSF License |
| Node.js | 22.x（仅用于可选的浏览器验证脚本） | MIT |

---

## 2. 数据来源

采集来源的许可证、条款与具体抓取策略，逐条记录在 [`config/sources.yaml`](config/sources.yaml) 与 [`docs/sources.md`](docs/sources.md) 中。此处只做汇总。

### 2.1 目录型来源（`role: directory`）

| 来源 | 上游仓库 | 许可证 | 状态 | 我们读取的内容 |
| --- | --- | --- | --- | --- |
| Free-LLM | `nejib1/Free-LLM` README | MIT | 启用 | Markdown 表格中的提供商名、模型名、免费额度等事实字段 |
| awesome-freellm-apis | `open-free-llm-api/awesome-freellm-apis` README | MIT | 启用 | 同上，另含 Base URL 速查表与模态信息 |
| free-llm-resources | `AILookup/free-llm-resources` README | **未声明（无 LICENSE 文件）** | **禁用** | 许可证确认前不读取 |

**关于 `free-llm-resources`：** 该仓库在首次核验时没有发布 LICENSE 文件。按照任务书要求，在没有明确许可的情况下，我们既不复制大段内容也不做镜像。适配器被写成只提取少量事实字段（提供商名、模型标识、数值型速率限制）加一个链接，且**默认禁用**。在维护者澄清许可证之前不会启用。

**关于"镜像"：** `free-llm.com` 与 `Free-LLM` 仓库、`freellm.net` 与 `awesome-freellm-apis` 各自共享同一份上游数据。它们被标注为 `mirrors` 并归入同一个 `source_family`——同一条数据同时出现在两边**不构成两次独立确认**。这一点是本项目的核心判断规则，详见 `docs/sources.md`。

### 2.2 官方核验来源（`role: official`）

官方页面只用于**核验**（确认目录来源的事实是否仍然成立、额度是否变化），并且**只保留短摘录 + 链接**，不做全文转载。

| 来源 | 页面 | 条款 | 我们读取的内容 |
| --- | --- | --- | --- |
| Google AI Studio | `ai.google.dev/gemini-api/docs/rate-limits` | https://policies.google.com/terms | 速率限制页面的短摘录与字段 |
| Groq | `console.groq.com/docs/rate-limits` | https://groq.com/terms-of-use/ | 同上 |
| OpenRouter | `openrouter.ai/docs/api-reference/limits` | https://openrouter.ai/terms | 同上 |

这些页面的内容版权归各自所有者。本仓库不重新发布其正文，只在 JSON 里保存一条带链接、带抓取时间的**有限长度摘录**（`evidence`），供使用者自行核对。

### 2.3 未收录的来源

以下内容**刻意没有**收录，原因一并说明：

- **没有明确许可证的目录仓库** —— 见上文的 `free-llm-resources`。
- **只能通过镜像访问、拿不到原始出处的清单** —— 无法确认独立性与时效性，不作为证据。
- **要求登录、要求 API Key 或明确禁止自动访问的页面** —— 采集器不携带任何密钥，不会为了拿数据去登录。
- **社区转述、论坛帖子、聚合站** —— 不属于独立来源，只能作为线索，不能作为 `evidence`。

---

## 3. 我们不声称拥有的内容

- **提供商名称、模型名称、商标、Logo** 归各自所有者。本仓库只做事实性引用（nominative use），不暗示任何形式的背书或合作关系。
- **免费额度、速率限制、模型可用性** 由各提供商决定，可能随时变更。本仓库记录的是"某次抓取时某来源是这样写的"，并附带抓取时间与证据链接——它不是承诺，也不构成服务条款。
- **`data/` 下的 JSON** 是本项目的聚合结果，但其中被聚合的事实不因聚合而改变归属。
- **没有任何 API 密钥**被收集、存储、传输或展示。导出文件中的 `api_key` 字段始终为 `null`，由使用者自行填入自己的 CC Switch。

---

## 4. 如果你是被收录方

如果你的项目被本仓库聚合，而你不希望这样：请开一个 [data-correction issue](.github/ISSUE_TEMPLATE/data-correction.yml)，说明是**更正**还是**移除**。移除请求不需要给出理由，我们不会为此设置门槛。

如果你的项目使用了与本仓库不兼容的许可证：同上，请告知，我们会移除对应来源的适配器并把已生成的数据从 `data/` 中清掉。
