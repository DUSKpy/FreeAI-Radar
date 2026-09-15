# 参与贡献

感谢你考虑为 FreeAI Radar 做贡献。在开始之前请先读这份文档——
这个项目的价值来自它的**克制**，所以对"多加一个字段"这类改动会比一般项目更谨慎。

## 最重要的三条规则

### 1. 不要编造

任何进入目录的事实都必须有来源。如果一个来源没有说明是否需要信用卡，
答案就是 `unknown`，**不是** `not_need`。

反例（会被拒绝）：

```python
# 错：来源没说，就默认"不需要"
needs_card = bool(row.get("credit_card"))

# 对：来源没说，就是不知道
needs_card = TriState.UNKNOWN if row.get("credit_card") is None else parse(row["credit_card"])
```

### 2. 不要把两个维度合并

访问方式、免费类型、信息状态、调用状态、客户端兼容性——这五个维度各自独立。
把 `web_chat_only` 和 `api` 合并、把 `one_time_trial` 和 `sustained_free_tier`
合并、把 `openai_chat` 和 `openai_responses` 合并，都会让目录开始骗人。

### 3. 不要碰密钥

Radar 永远不会接触用户的 API Key。如果你在写一段代码，它的输入里出现了真实密钥，
那这段代码的方向就是错的。

- 密钥不能出现在 URL、导出文件、遥测、日志里
- CC Switch 预览里 `apiKey` 永远是空值
- 需要说明密钥填哪里时，用 `YOUR_API_KEY` 这类一眼可辨的占位符

`tests/scan_secrets.py` 会在 CI 里扫描 `dist/`，发现形似密钥的字符串就失败。

## 开发环境

```bash
git clone https://github.com/OWNER/freeai-radar
cd freeai-radar
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Python 3.11 及以上。前端没有构建步骤——打开 `site/static/js/` 就是全部源码。

## 提交前必须通过

```bash
ruff check .                     # 必须全绿
pytest -m "not network"          # 必须全绿，且不需要联网
python -m tests.validate_fixtures
```

CI 还会跑一遍完整的离线构建。**本地也建议跑一次**，因为模板里引用一个只在真实采集后
才存在的字段，CI 才会发现：

```bash
python -m radar.export_public --state tests/fixtures/state.minimal.json \
  --output .work/public --base-path /freeai-radar/
python -m radar.build_site --data .work/public \
  --base-path /freeai-radar/ --output dist
python -m tests.scan_secrets dist
```

## 新增一个数据来源

数据来源是这个项目最需要贡献的地方。新增一个适配器的步骤：

1. **确认许可。** 在 `config/sources.yaml` 里填 `license` 和 `terms_url`。
   抓取一个没有明确许可的页面会被拒绝。
2. **确认它是不是"独立来源"。** 如果它和已有来源共享同一份数据（比如
   `free-llm.com` 与 `nejib1/Free-LLM` 的 README 是同一份），它**不算独立证据**，
   必须填在 `mirrors:` 里。把镜像当成独立来源是最常见的错误。
3. **写适配器**，放在 `radar/collectors/` 下，只依赖 `collectors/base.py` 提供的接口。
4. **填 `allowed_domains`。** 白名单之外的域名会被 `radar/safety.py` 在发请求前拒绝。
5. **准备夹具。** 把真实页面存一份到 `tests/fixtures/`，写解析测试。
   测试必须离线可跑——依赖今天上游内容的测试明天就会无故失败。
6. **跑一遍真实采集**验证：

```bash
python -m radar.collect --config config/sources.yaml \
  --aliases config/aliases.yaml \
  --previous .work/state.json --output .work/state.json \
  --init --only your-new-source-id
```

`--previous` 是必填的，第一次跑也要给（配 `--init`）。这样路径写错和首次运行
不会长成同一个样子——不然一个拼写错误就会安静地把整个目录重置掉。

## 修改数据模型

改动 `schemas/` 下任何 schema 之前，先想清楚：

- 新字段是**事实**还是**推导**？推导出来的值不应该进 `state`。
- 三态字段必须是 `need` / `not_need` / `unknown`，不能是布尔。
- 新字段是否需要进 `export_public` 的白名单？默认**不进**——公开导出是白名单制，
  不是黑名单制，新增字段不会自动公开。
- 如果是新增实体，`state.schema.json` 顶层的 `additionalProperties: false` 会拒绝它，
  必须同步改 schema。

## 前端改动

- 样式分四层：`tokens.css` → `glass.css` → `components.css` → `pages.css`。
  颜色、间距、圆角一律走 CSS 变量，不写死。
- JavaScript 用原生 ES Module，**不引入框架**。
- 渲染用户可见的数据时**不要用 `innerHTML`**。抓来的文本必须走 `render.js` 里的
  DOM 构建函数。
- 四个断点必须都验证：≥1200px、1024–1199px、768–1023px、<768px。
- 玻璃效果必须有回退：`@supports (backdrop-filter: blur(1px))` 之外要不透明可读。

## 提交信息

用祈使句，说清楚**为什么**而不只是**做了什么**：

```
fix: strip the data/ segment when resolving manifest URLs

The manifest carries `/base/data/catalog.<hash>.json` while the data
directory *is* `data/`, so the naive join produced `<dir>/data/data/...`
and every versioned file silently loaded as None. The build still exited
0, which is why this went unnoticed: an empty catalog rendered as a
successful build.
```

## 分支与 PR

- 从 `main` 切分支，名字自解释（`fix/manifest-url-resolution`）。
- 一个 PR 只做一件事。重构和新功能不要混在一起。
- **不要 force-push 去掩盖冲突。** 有冲突就正常合并，让审查者看到冲突本身。
- 数据变更（`data/` 目录）由 Action 自动提交，不要在功能 PR 里手动改。

## 行为准则

对事不对人。技术分歧用数据和来源解决，不用语气解决。
