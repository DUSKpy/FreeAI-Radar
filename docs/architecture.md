# 架构

## 一句话

浏览器读公开 JSON，Python 只在构建时跑。线上没有服务、没有数据库、没有写接口。

## 数据流

```
config/sources.yaml
        │
        │  ① 采集（每日，GitHub Actions）
        ▼
radar/collect.py ──► radar/collectors/*  ──► radar/parsers/*
        │                    │                     │
        │              安全网关               Markdown 表格
        │              safety.py              HTML 文档
        │                                    官方字段
        ▼
  .work/state.json  ◄──── 跨次运行的唯一记忆
        │
        │  ② 归一化（在 collect 内部）
        │     · 合并同一实体的多次观察
        │     · 标记来源冲突
        │     · 判定过期
        ▼
radar/normalize.py
        │
        │  ③ 导出（字段白名单）
        ▼
radar/export_public.py ──► .work/public/data/
        │                     manifest.json
        │                     catalog.<hash>.json
        │                     changes.<hash>.json
        │                     reports/YYYY-MM-DD.md
        │                     index.json
        ▼
radar/build_site.py ──► dist/          （Jinja2 渲染九个页面）
        │
        │  ④ 发布
        ▼
   GitHub Pages（纯静态）
        │
        │  ⑤ 访问时
        ▼
   浏览器 ──► 只读 fetch 公开 JSON（不发任何出站请求）
```

## 为什么是静态站点

任务书的要求，也是这个问题的正确形状：

- **没有密钥风险。** 没有服务端就没有"服务端拿着密钥"这件事。
- **没有可用性承诺。** Pages 挂了是 Pages 的事，不是我们维护的服务。
- **没有运维。** 没有进程、没有日志轮转、没有扩缩容。
- **可审计。** 从 JSON 到页面全是纯函数，任何人都能在本地复现同一个产物。

代价是**没有实时性**。数据是"上一次采集时的样子"，
所有时间戳都明确标出来。这个代价是项目愿意付的。

## 状态：跨次运行的记忆

`.work/state.json` 是整个项目里唯一有状态的部件。

| 内容 | 为什么必须持久化 |
| --- | --- |
| `snapshots` | 内容哈希与 HTTP 元数据，条件请求靠它 |
| `providers` / `models` / `offers` / `claims` | 上一轮归一化后的目录 |
| `changes` | 变更日志（保留 90 天） |
| `runs` | 运行历史（最多 120 次） |
| `collection_meta` | 最后成功时间、连续空结果计数 |

**它丢失的后果**：每次运行都像首次运行——所有条目都变成"新增"，
变更历史失去意义，站点会声称 56 个提供商全是今天发现的。

因此 workflow 里 restore 之后**显式检查文件是否存在**，
缺失时打警告并按首次运行处理，而不是静默继续。

GitHub Actions 用 `actions/cache` 在运行之间传递它，
同时把产物上传为 artifact 便于排查。

## 归一化：把多个来源的说法合成一个

这是最容易做错的一层。核心规则：

### 三态合并

```python
_tighten(UNKNOWN, UNKNOWN) == UNKNOWN   # 两次都没说 → 还是不知道
_tighten(NEED, UNKNOWN)    == NEED      # 一次明确说需要 → 需要
_tighten(NOT_NEED, UNKNOWN)== NOT_NEED  # 一次明确说不需要 → 不需要
_tighten(NEED, NOT_NEED)   == NEED      # 两说冲突 → 取先到的，并标记冲突
```

**`UNKNOWN` 永远不会被"顺手"变成 `NOT_NEED`。** 这是全套测试里守得最紧的一条。

### 冲突标记

两个来源对同一字段给出不同值时，条目被标记为 `source_conflict`
并进入待复核队列。**不静默取其一**——静默取一意味着某天它会无声地变，
而没有任何人知道它变过。

### 来源族而非来源

按 `source_family` 分组，同族的多份证据只算一份。
否则 `free-llm.com` 和它的 GitHub README 会被算成"两个独立来源确认"。

### 过期判定

- 来源超过 168 小时（7 天）未成功采集 → 来源标记 `stale`
- 条目超过 30 天未被重新确认 → 条目标记 `stale`
- 过期的条目**仍然显示**，但明确标注"可能已过期"。
  直接隐藏会更糟：用户会以为这个提供商不存在了。

## 导出：白名单，不是黑名单

`export_public.py` 逐字段列出要公开什么。

这意味着**新增一个内部字段不会自动公开**。默认是私有的，
要公开必须显式加进白名单。

反向设计（"除了这些以外都公开"）会让一次疏忽就泄露内部状态，
而内部状态里可能含有维护者的判断备注、内部评分、机械标记。

导出后 `tests/scan_secrets.py` 再扫一遍产物作为兜底。

## 版本化：不混版本

数据文件和页面之间靠 **manifest** 建立版本关系：

- `catalog.<hash>.json`——文件名里带内容哈希
- `manifest.json`——记录当前是哪个哈希

浏览器启动时**先读 manifest，再按它给的 URL 取数据**。
如果页面渲染到一半发现版本不一致，宁可显示恢复提示，
也不把两个版本的数据混在一起显示。

`dataset_version` 是内容哈希，**计算时排除 `generated_at`**——
否则每次构建都会产生一个新版本号，缓存彻底失效。

## 前端：没有构建步骤

```
site/static/js/
  app.js              入口，按 data-page 动态 import 页面模块
  bootstrap.js        读 <script id="radar-bootstrap"> 的初始状态
  data-client.js      数据获取，manifest 优先，拒绝混版本
  render.js           全部 DOM 构建（从不用 innerHTML 渲染抓来的数据）
  markdown.js         手写 Markdown → DOM（不产出 HTML 字符串）
  theme.js            主题 / 透明度 / 动效三项偏好
  favorites.js        收藏，localStorage，上限 500 条
  cc-switch.js        CC Switch 配置生成（与 radar/cc_switch.py 一一对应）
  directory.js        搜索、筛选、分页、URL 同步
  provider.js         详情页
  ...
```

不用框架的理由：这个站点的交互复杂度（筛选 + 分页 + 一个对话框）
不足以抵消引入框架带来的供应链与构建成本。
**零依赖意味着零供应链风险**。

`cc-switch.js` 是 `radar/cc_switch.py` 的忠实镜像。
两处逻辑重复是刻意的：Python 侧生成构建期的导出文件，
JS 侧在用户点击时实时生成。两边的常量（支持的版本号、commit）
都写死并各有测试盯着，任何一边改了另一边会失败。

## 样式：四层

```
tokens.css       CSS 变量：颜色、间距、圆角、字号、状态色
   ↓
glass.css        Liquid Glass 材质：环境层 / 内容层 / 控件层
   ↓
components.css   组件：导航、按钮、卡片、表格、对话框、状态块
   ↓
pages.css        页面布局 + 断点
```

颜色、间距、圆角一律走变量，不写死。四个断点写在 `pages.css` 末尾：

| 断点 | 布局 |
| --- | --- |
| ≥1200px | 桌面：左侧固定侧边栏 + 内容 + 右侧栏 |
| 1024–1199px | 笔记本：右栏先塌陷（把主列挤窄比挤右栏更糟） |
| 768–1023px | iPad 竖屏：侧边栏换成横向滚动的顶栏 |
| <768px | 手机：底部标签栏 |

**玻璃效果必须有回退。** `@supports (backdrop-filter: blur(1px))` 之外
使用不透明背景。同时尊重 `prefers-reduced-transparency` 与
`prefers-reduced-motion`，并提供用户可手动切换的偏好。

`body::before` 上的静态渐变**不加 `filter` 或 `transform`**——
那会创建包含块，把 `position: fixed` 的导航裁掉。

## 安全边界

三层，见 [SECURITY.md](../SECURITY.md)：

1. **采集期**（主要风险）：SSRF 防护、域名白名单、DNS 解析后复检、
   体积上限、重定向上限、**从不执行来源页面的脚本**。
2. **渲染期**：服务端自动转义，客户端从不用 `innerHTML` 渲染抓来的数据，
   Markdown 解析成 DOM 而非字符串，只有 `http(s)` 能变成链接。
3. **运行期**：静态站点，**页面不替访客发出任何出站请求**。

## 目录结构约定

```
radar/           只跑在构建时
  collectors/    一个来源一个文件，只依赖 base.py 的接口
  parsers/       纯函数：文本进，结构出。无网络、无 IO
  normalize.py   纯函数：记录进，记录出
site/
  templates/     Jinja2
  static/        无构建步骤，直接就是浏览器加载的文件
schemas/         JSON Schema，是数据模型的权威定义
tests/           pytest + 离线夹具（tests/fixtures/）
config/          来源、别名、人工复核配置
docs/            文档与交付截图
```

## 测试策略

274 个测试，**全部离线**，跑完约 7 秒。

| 文件 | 守什么 |
| --- | --- |
| `test_safety.py` | SSRF 防护：回环、内网、元数据、域名白名单绕过、DNS 复检 |
| `test_invariants.py` | 五维分离、三态规则、四种协议不合并、schema 封闭性、无密钥字段 |
| `test_cc_switch.py` | 协议门禁、不谎报兼容、密钥永不出现在载荷里、Deep Link 形状 |
| `test_parsers.py` | 表格解析、哨兵作用域、列名容错、证据摘录边界 |
| `test_build.py` | 两个真实 bug 的回归、base path、全部页面与资源、构建幂等 |

`tests/validate_fixtures.py` 和 `tests/scan_secrets.py` 作为独立模块，
被 CI 直接调用，也可以本地手动跑。

**网络相关测试标记为 `network` 并在 CI 里排除**——
上游抖一下不该让 CI 变红。
