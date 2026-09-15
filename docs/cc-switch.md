# CC Switch 集成

Radar 的目录本身就有用，但它的终点是**让你的编辑器用上这些免费额度**。
[CC Switch](https://github.com/farion1231/cc-switch) 是那个"终点"。

本文档说明 Radar 生成什么、**不**生成什么，以及为什么有些情况下它会明确说
"我做不到"。

## 支持的版本

| 项 | 值 |
| --- | --- |
| CC Switch 版本 | **3.20.3** |
| Git 引用 | `v3.20.3` |
| Commit | `06082e1` |
| Deep Link 协议 | `v1` |

这些常量写死在 `radar/cc_switch.py` 和 `site/static/js/cc-switch.js` 两处，
并各有测试盯着（`TestVersionPinning`）。**升级版本号之前必须重新核对官方文档**，
否则兼容性声明就变成了猜测。

## Radar 生成什么

对每个提供商 × 每个目标应用，Radar 会算出四种结果之一：

| 状态 | 含义 | UI 给什么 |
| --- | --- | --- |
| `ready_without_key` | 协议匹配、字段齐全，只差密钥 | 字段列表 + 逐字段复制 + Deep Link |
| `missing_fields` | 缺 Base URL 等必要字段 | 说明缺哪个字段 |
| `unsupported_protocol` | **协议明确但和目标应用不匹配** | 说明为什么不匹配 |
| `unknown` | **协议的归属没查到** | 说明"无法判断"，不做任何承诺 |

### `unsupported_protocol` 与 `unknown` 的区别

这两个状态必须分开，混起来就是骗人：

- **`unsupported_protocol`**：我们**知道**这个提供商支持哪些协议，
  而其中没有目标应用需要的那个。这是一个确定的否定答案。
  例：提供商只支持 `openai_chat`，用户想导入 Claude Code（需要 `anthropic_messages`）。
- **`unknown`**：我们**不知道**这个提供商支持什么协议。
  这是一个诚实的"没查到"。例：来源完全没提协议。

把第二种说成第一种，就等于在没有依据的情况下说"不支持"。

## 四种协议，各自独立

CC Switch 的目标应用各自只认一种协议：

| 应用 | 需要的协议 |
| --- | --- |
| Claude Code | `anthropic_messages` |
| Codex | `openai_responses` |
| Gemini CLI | `gemini_native` |
| OpenCode | `openai_chat` |
| OpenClaw | `openai_chat` |

**Codex 只认 Responses API，不认 Chat Completions。** 这一点很容易搞错：
一个提供商提供 `/v1/chat/completions`，看起来"是 OpenAI 兼容的"，
但 Codex 用的不是这个端点。把二者混为一谈会让用户白折腾一轮。

所以协议是四个独立的标记位，**从不合并成一个"OpenAI 兼容"布尔值**。

## Radar 不做什么

### 它绝不接触你的密钥

- 预览框里的 `apiKey` **永远是空的**。
- Deep Link 里**不带 `apiKey` 参数**。
- 需要提示密钥填哪里时，用 `YOUR_API_KEY` 这种一眼可辨的占位符。
- 导出文件里的 `api_key` 字段**永远是 `null`**——
  字段存在是为了明确"这里没有值"，而不是留了个位置让人填。

测试套件里有专门的断言守着这几条（`TestNoKeyEverLeaves`）。

### 它不验证你的配置能不能连通

Radar 没有、也不会用你的密钥发起任何请求。

预览里的字段是"按 CC Switch 的规则检查过**格式**"，
**不是**"已经验证过能连通"。导入之后能不能用，
取决于你自己申请到的密钥和账号状态。

这条区别在 UI 里用一整块提示写清楚，不是脚注。

### 它的导出文件不是 CC Switch 原生导入文件

Radar 生成的 JSON 是**数据交换文件**，用途是让你核对和复制字段。
这个标签在导出里写得很明确：

```
"radar_export_label": "Radar 数据交换文件（非 CC Switch 原生导入文件）"
```

真正的原生导入是 Deep Link。两者的差别必须让人一眼看出来。

## Deep Link

支持时给出：

```
ccswitch://v1/import?resource=provider&app=claude&name=<名称>&endpoint=<Base URL>&model=<模型>
```

参数按 V1 协议组织，全部经过 percent 编码——
中文提供商名和带查询串的 Base URL 都能正确往返，
而且 Base URL 里的 `&` **不会**逃逸成额外参数。

### 什么时候不给 Deep Link

**只在 `ready_without_key` 时给。** 其他状态给了也是误导：
用户点下去，CC Switch 打开，然后失败或者导入一个用不了的东西。

### 协议没装怎么办

`ccswitch://` 没有被注册时，点击不会有任何可见反应。
所以每个应用都**同时**提供：

1. **逐字段复制**——每个字段一个复制按钮
2. **复制全部字段**——一次性拷贝成文本
3. **一句明确的话**说明链接可能打不开

不依赖 Deep Link 是唯一路径。这是刻意的降级设计：
Deep Link 好用的时候很好用，但它是否可用**不取决于我们**。

## 字段列表

`ready_without_key` 时给出的字段：

| 字段 | 说明 | 可复制 |
| --- | --- | --- |
| `name` | 提供商名称 | 是 |
| `app` | 目标应用标识 | 是 |
| `endpoint` | Base URL（已规范化） | 是 |
| `model` | 模型 ID（可留空） | 是 |
| `homepage` | 提供商主页 | 是 |
| `protocol` | 使用的协议 | 是 |
| `apiKey` | **空值**，仅提示填写位置 | 否，且被标记为 secret |

## 端点规范化

- 去掉尾部斜杠
- **不猜协议**：`api.example.com/v1` 不会自动补成 `https://...`。
  补了就等于替用户决定了连接目标。原样呈现，让用户自己处理。
- 拼接路径时不产生双斜杠

## 自己构建

```bash
python -m radar.cc_switch \
  --state .work/state.json \
  --output .work/public/data/cc-switch.json \
  --base-path /
```

产物是 `.work/public/data/cc-switch.json`，
被 `export_public` → `build_site` 复制进 `dist/data/`，
页面上由 `site/static/js/cc-switch.js` 在用户点击时读取并实时生成配置。

## 升级到新的 CC Switch 版本

1. 读官方文档，确认 Deep Link 的参数集和语义没有变化。
2. 改 `radar/cc_switch.py` 里的 `SUPPORTED_CC_SWITCH_VERSION` /
   `_REF` / `_COMMIT`，以及 `APP_PROTOCOL_REQUIREMENTS`（如果应用变了）。
3. 改 `site/static/js/cc-switch.js` 里对应的常量。
4. 改 `tests/test_cc_switch.py::TestVersionPinning` 里的断言。
5. 在真实装了新版 CC Switch 的机器上**手动验证一次**——
   常量改对了不代表协议没变。

第 5 步不能省。版本号是我们对自己的声称，
而声称必须有验证撑着，否则它只是另一个未经验证的断言。
