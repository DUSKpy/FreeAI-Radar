# 数据来源

这份文档列出每个来源、它的许可以及**为什么它是或不是独立证据**。
来源配置的可执行版本是 [`config/sources.yaml`](../config/sources.yaml)——
那里是唯一的事实来源，本文档解释它的取舍。

## 独立性：这个项目最重要的一条判断

两个来源如果共享同一份底层数据，那它们**不是两次独立确认**。

举例：`nejib1/Free-LLM` 的 README 和 `free-llm.com` 网站是同一份数据的两种呈现。
一个提供商同时出现在这两处，只说明"这份数据里写了两次"，
**不构成两个来源的交叉验证**。

因此配置里用 `mirrors:` 显式记录镜像关系。归一化时按 `source_family` 分组，
同组内的多份证据只算一份。把镜像当独立来源，会让"已被两个来源确认"这句话变成假话。

## 来源清单

### 已启用

| ID | 名称 | 类型 | 角色 | 许可 |
| --- | --- | --- | --- | --- |
| `free-llm-github` | Free-LLM (GitHub README) | Markdown | 目录 | MIT |
| `awesome-freellm-apis` | awesome-freellm-apis (GitHub README) | Markdown | 目录 | MIT |
| `official-google-ai-studio` | Google AI Studio 官方速率限制页 | HTML | 官方 | 专有（仅取事实） |
| `official-groq` | Groq 官方速率限制页 | HTML | 官方 | 专有（仅取事实） |
| `official-openrouter` | OpenRouter 官方限额文档 | HTML | 官方 | 专有（仅取事实） |

#### `free-llm-github`

- **地址**：`raw.githubusercontent.com/nejib1/Free-LLM/main/README.md`
- **来源族**：`free-llm`
- **镜像**：`free-llm.com`（同源，不算独立证据）
- **解析器**：`free_llm_markdown`
- **许可**：MIT，[LICENSE](https://github.com/nejib1/Free-LLM/blob/main/LICENSE)
- **说明**：README 用 `<!--TABLE:*:START-->` 哨兵注释包裹每张表。
  解析器优先按哨兵定位，哨兵缺失时回退到标题识别。

#### `awesome-freellm-apis`

- **地址**：`raw.githubusercontent.com/open-free-llm-api/awesome-freellm-apis/main/README.md`
- **来源族**：`freellm-net`
- **镜像**：`freellm.net`（同源）
- **解析器**：`awesome_freellm_markdown`
- **许可**：MIT，[LICENSE](https://github.com/open-free-llm-api/awesome-freellm-apis/blob/main/LICENSE)
- **说明**：使用 `BEGIN_PERMANENT_FREE` / `BEGIN_RENEWABLE` / `BEGIN_QUICK_REF`
  注释哨兵。"Best Free Models" 表是**每个提供商多行**的结构，
  续行的提供商单元格为空——解析器必须沿用上一行的提供商，
  否则续行会被当成无名提供商。

#### `official-*`（三个官方来源）

Google AI Studio、Groq、OpenRouter 的官方文档页。

- **解析器**：`official_docs_generic`
- **角色**：`official`——这些来源的结论会被标记为 `official_confirmed`，
  而不是 `directory_claim`
- **许可**：页面本身是专有内容。**只提取事实**（限额数字、模型 ID）
  和**短证据片段**，不镜像页面、不转载正文。
- **说明**：这是一个**通用**官方字段解析器，抽取是尽力而为。
  它对每个字段保留一段摘录，人工可以通过 `config/reviews.yaml` 复核确认。
  Radar 不会因为"解析器觉得是免费"就把它标成官方确认。

### 已禁用

| ID | 名称 | 禁用原因 |
| --- | --- | --- |
| `free-llm-resources` | AILookup/free-llm-resources | **未找到 LICENSE 文件** |

`free-llm-resources` 的适配器和夹具都写好了，但仓库里没有许可声明。
在许可明确之前保持 `enabled: false`。

如果将来作者加上许可，把 `enabled` 改成 `true` 即可，其余无需改动。

## 抓取礼貌

在 `config/sources.yaml` 的 `defaults` 里统一约定：

| 设置 | 值 | 原因 |
| --- | --- | --- |
| `timeout_seconds` | 20 | 够慢的站点加载完，又不会挂住整个采集 |
| `max_body_bytes` | 5 MiB（解压后） | 防解压炸弹 |
| `per_domain_concurrency` | 1 | **同一域名串行**——不并发打同一个站 |
| `global_concurrency` | 3 | 跨域名最多三路并行 |
| `respect_retry_after` | true | 收到 `Retry-After` 就退避 |
| `follow_redirects` | true | 但最多 4 跳 |
| `max_redirects` | 4 | 防重定向循环 |
| `daily_collection` | true | 每个来源每天最多一次 |
| `manual_cooldown_minutes` | 10 | 手动重跑的最小间隔 |

另外：

- 用**条件请求**（`If-None-Match` / `If-Modified-Since`）。
  内容没变时来源返回 `304`，不消耗它的带宽。
- 用**定向 URL** 而不是抓整站：直接取 raw README 或具体文档页，
  不做爬虫式的链接遍历。
- 每次请求带一个说明身份的 User-Agent。

## 域名白名单

每个来源有自己的 `allowed_domains`，在**发请求之前**生效：

```yaml
allowed_domains:
  - raw.githubusercontent.com
```

白名单之外的域名会被 `radar/safety.py` 直接拒绝，请求根本不会发出。
匹配要求 `host == entry` 或 `host.endswith("." + entry)`，
所以 `notgroq.com` **不会**因为以 `groq.com` 结尾而通过。

## 只保存必要事实

这是硬约束，不是节约考虑：

- **保存**：事实值、短证据片段（每段上限 400 字符）、来源链接、
  抓取时间、内容哈希、HTTP 元数据。
- **不保存**：来源页面的完整副本、HTML 原文、图片、cookie、任何密钥。

理由有两条：一是版权——来源页面不是我们的内容；
二是准确性——保存副本会让人以为那份副本才是权威。

## 新增来源

见 [CONTRIBUTING.md](../CONTRIBUTING.md) 的"新增一个数据来源"一节。

最关键的三个问题：

1. **有明确许可吗？** 没有就先禁用，不要"先上了再说"。
2. **它是独立来源吗？** 是镜像就填进 `mirrors:`。
3. **有离线夹具和解析测试吗？** 依赖今天上游内容的测试明天就会无故失败。

## 来源不可用时的行为

一个来源挂掉**不会**让整次采集失败。

- 失败的来源在状态页显示自己的失败原因和时间
- 站点继续用上一次成功的数据，并在数据源状态页与每日报告里标注
- `sources` 的 `status` 区分 `ok` / `not_modified` / `failed` /
  `parse_error` / `skipped`
- **"从未成功"与"成功后返回 0 条"是两种不同的状态**，显示上必须能区分：
  前者说明来源配置有问题，后者说明来源结构可能变了

如果**一半以上**的来源失败，那次运行会被标记为 `degraded`，
每日报告里会明确写出来。
