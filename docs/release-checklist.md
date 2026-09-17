# 发布检查清单

这份清单是**发布前的闸门**，不是说明文档。每条都写成可以回答"是/否"的形式，答"否"就不要发布。

清单分成三组：**A 代码与数据**、**B 站点与前端**、**C 部署**。C 组包含几条只有在真实仓库里才能确认的项——没有真实仓库时它们只能是"未验证"，**不允许**在交付报告里写成"已完成"。

---

## A. 代码与数据

### A1 静态检查

```bash
ruff check .
ruff format --check .
```

- [ ] `ruff check .` 输出 `All checks passed!`
- [ ] `ruff format --check .` 无差异（CI 里这一条是警告级，但发布前应当干净）

### A2 测试

```bash
pytest -m "not network"
```

- [ ] 全部通过，0 failed
- [ ] 没有 `error`（区分 `failed` 与 `error`——后者通常意味着导入坏了）
- [ ] 跳过的用例都检查过跳过原因，没有"因为环境不对所以跳过"这种掩盖

联网测试**默认不跑**（`network` marker 被 deselect）。它们不是发布闸门的一部分，因为一次上游抖动不应该阻塞发布——但发布前应当至少手动跑过一次，确认适配器对上线上页面仍然有效：

```bash
pytest -m network --run-network
```

- [ ] 联网用例在最近一次真实采集里跑过并通过

### A3 契约校验

```bash
python -m tests.validate_fixtures
```

- [ ] fixture 与 schema 全部匹配，0 errors

### A4 数据来源状态

```bash
# 查看上次采集的 reports；要实时重跑就用：
python -m radar.collect --config config/sources.yaml \
  --previous .work/state.json --dry-run
```

> `--previous` 必填。故意不给它、或者给一个不存在的路径而不加 `--init`，
> 都应当**报错退出**——这两条都值得在发布前手动验证一次。

- [ ] 每个**启用**的来源状态是 `ok` 或 `not_modified`
- [ ] 没有来源连续失败超过阈值
- [ ] 如果整体 `degraded`，确认这是**已知且可接受**的（比如某来源临时 5xx），否则不要发布
- [ ] 每个来源的 `allowed_domains` 与它实际请求的主机一致

### A5 密钥扫描

```bash
python -m tests.scan_secrets dist
```

- [ ] 0 findings
- [ ] 如果有 finding，**先确认它不是文档里的示例**，再修；不要为了过扫描而放宽规则

### A6 导出字段

- [ ] `radar/export_public.py` 用的是**白名单**（列出允许导出的字段），不是黑名单（列出要删的字段）
- [ ] 导出的 JSON 里 `api_key` 全部为 `null`
- [ ] 抽样检查一个 provider，确认没有把 `state.json` 的内部字段（采集游标、ETag、抓取日志等）漏出去

---

## B. 站点与前端

### B1 构建闭环

```bash
python -m radar.export_public
python -m radar.build_site
```

- [ ] 退出码 0
- [ ] 构建输出里的 `provider_count` **不为 0**（这是最容易静默失败的地方——退出码 0 但目录是空的）
- [ ] `dist/` 下的页面全部生成，资源全部存在

### B2 页面清单

逐个打开，确认不是空白骨架：

- [ ] 总览 overview
- [ ] 目录 directory
- [ ] 提供商详情 provider
- [ ] 变更 changes
- [ ] 来源状态 sources
- [ ] 核验清单 reviews（只读）
- [ ] 收藏 favorites
- [ ] 404

每页都应有 `lang="zh-CN"`。

### B3 四个断点

分别在四个宽度下看，**浅色与深色都看**：

- [ ] ≥1200px 桌面 —— 左导航 + 主内容 + 右栏
- [ ] 1024–1199px 笔记本 —— 右栏先收起，左导航保留
- [ ] 768–1023px 平板/iPad —— **侧栏必须消失**，换成顶部导航
- [ ] <768px 手机 —— 底部导航出现，页面留出 `safe-area-inset-bottom`

> 第 3 条曾经失败过：`@media (max-width: 1023px)` 只把 grid 改成单列，但没有隐藏 `.sidebar`，导致 iPad 上侧栏仍然占着宽度、正文被挤成窄条。改完之后 820px 的页面高度从 5333px 降到 4299px。每次动 CSS 都要重新看一遍这条。

### B4 玻璃与降级

- [ ] 支持 `backdrop-filter` 时，导航/卡片是玻璃质感
- [ ] 开启"减少透明度"（`prefers-reduced-transparency`）后，内容**仍然可读**——不透明的回退必须生效
- [ ] 关闭 `backdrop-filter`（或在不支持的浏览器里）不影响功能，只影响观感
- [ ] `body::before` 上**没有** `filter` / `transform`——这两个属性会把后代变成新的包含块，进而把 `position: fixed` 的导航弄坏

### B5 行为验证

```bash
node .work/flow.mjs
```

- [ ] 16/16 通过
- [ ] 搜索能把结果收窄，而且反映到 URL（`?q=...`，可分享）
- [ ] 筛选器勾选生效
- [ ] 卡片能跳到 provider 页
- [ ] CC Switch 弹窗能打开，**从不吐出密钥**
- [ ] 切换目标 App 会重新渲染，并且给出可用 App 的选项
- [ ] 收藏写入 `localStorage`（`radar.favorites.v1`），刷新后仍在
- [ ] 深色主题刷新后保持
- [ ] 控制台无报错

### B6 CC Switch 三态

- [ ] 来源**未声明**协议时，界面说的是"无法判断是否兼容"，状态是 `unknown`——**不是**"不支持"
- [ ] 来源声明了协议但与该 App 需要的不一致时，状态才是 `unsupported_protocol`
- [ ] 这两者不能合并。合并等于把"不知道"说成"不行"，是不实陈述。
- [ ] Deep Link 只在 `ready_without_key` 时给出；其余状态给出明确的手动复制回退
- [ ] endpoint 里自带的 `&` 不会污染 Deep Link 的参数（百分号编码正确）

---

## C. 部署

> **这一组的前 5 条在本地能验证到"流程正确"，最后 3 条只有在真实仓库上才算数。**

### C1 工作流结构

- [ ] `ci.yml` 的 `permissions` 是 `contents: read`
- [ ] `publish.yml` 拆成了 `prepare` / `persist` / `deploy` 三个 job
- [ ] 抓取不受信站点的那个 job **不持有**写权限 token
- [ ] `concurrency` 已设置，重复触发不会互相踩

### C2 状态持久化

- [ ] `prepare` 用 `actions/cache/restore` 恢复 `.work/state.json`，`restore-keys: radar-state-`
- [ ] `persist` 用 `actions/cache/save` 写回，key 是 `radar-state-${{ github.run_id }}`
- [ ] 首次运行时，state 缺失会**显式报错并加 `--init`**，而不是安静地当成空状态继续

### C3 提交策略

- [ ] 用 rebase-then-push，最多重试 3 次
- [ ] **绝不 force-push**。冲突要暴露出来，不能靠强推掩盖。

```bash
for attempt in 1 2 3; do
  if git pull --rebase --autostash origin "$BRANCH" \
     && git push origin "HEAD:$BRANCH"; then
    exit 0
  fi
  git rebase --abort 2>/dev/null || true
  sleep $((attempt * 5))
done
# 失败就失败，把 commit 留在本地
exit 1
```

### C4 Pages 设置

参考 [docs/github-pages.md](github-pages.md)。关键的几条：

- [ ] Settings → Pages → Source = **GitHub Actions**
- [ ] 第一次手动跑一次 publish，并且**勾上 force**

> 不勾 force 会拿到上游 304。条件请求返回 304 时没有响应体，解析器拿到空内容，结果是"构建成功但目录是空的"。这是分叉后最常见的坑，`docs/github-pages.md` 第 6 步专门解释了它。

- [ ] 如果站点不在域名根目录，`base_path` 设置正确（仓库名为 `xxx.github.io` 时是 `/`，否则是 `/<repo>`）
- [ ] 如果本机走了 Clash/Surge 之类的 DNS 代理，注意 `198.18.0.0/15` 会被安全校验拦下——此时才考虑 `FA_RADAR_ALLOW_DNS_PROXY=1`，**并且只在这个情况下**

### C5 密钥与权限

- [ ] 仓库里没有以任何形式提交过的密钥
- [ ] 工作流里没有把密钥写进 URL、日志或产物
- [ ] 抓取器**从不**携带密钥请求上游

---

### C6 真实部署（**需要真实目标仓库**）

- [ ] 有一个真实存在的目标仓库
- [ ] 在该仓库上手跑过一次 publish，三个 job 都成功
- [ ] 站点 URL **真的能打开**，且首页**有数据**（不是"构建成功但空目录"）
- [ ] 从公网打开时，抽查一个 provider 详情页，确认 `evidence` 链接可达
- [ ] 打开站点后能看到 `dataset_version` 与生成时间
- [ ] 连续跑两次，确认状态被持久化（第二次的来源状态出现 `not_modified`）
- [ ] 在真实 iPad 或浏览器设备模拟里打开一次

> **没有真实仓库时，C6 全部是"未验证"。** 任务书明确禁止在没有真实目标仓库的情况下声称站点已上线。交付时请照实写。

---

## D. 发布后

- [ ] 记下本次 `dataset_version`
- [ ] 记下本次 `change_count`
- [ ] 如果有来源进入 `failed`，记下是哪个、什么原因
- [ ] 如果本次是 `degraded` 发布，在 release notes 里写明

---

## 附：本地完整复现（无网络）

无法联网、或只想验证流水线本身时，走两个场景。

**场景 1：用 fixture 验证渲染**（有 3 个 provider，能看到真实布局）

```bash
python -m tests.validate_fixtures
python -m radar.export_public \
  --state tests/fixtures/state.minimal.json \
  --output .work/public-fixture \
  --base-path /
python -m radar.build_site \
  --data .work/public-fixture \
  --output .work/dist-fixture \
  --base-path /
test -f .work/dist-fixture/index.html && test -f .work/dist-fixture/directory.html && echo "pages ok"
python -m tests.scan_secrets .work/dist-fixture
```

**场景 2：用空 seed 验证空状态**（确认"还没有数据"这条路也走得通）

```bash
python -m radar.export_public \
  --state data/seed/state.empty.json \
  --output .work/public-empty \
  --base-path /
python -m radar.build_site \
  --data .work/public-empty \
  --output .work/dist-empty \
  --base-path /
```

- [ ] 两个场景都构建成功，各 8 个页面
- [ ] 场景 1 的 `provider_count` 是 3
- [ ] 场景 2 的 `provider_count` 是 0，**且首页明确说"还没有成功完成过一次采集"**，
      不是一片空白让人以为坏了

> **参数名**：`export_public` 用 `--output`；`build_site` 用 `--data` 指输入、
> `--output` 指输出。**没有 `--out`。** 它之所以"能用"，只是因为 argparse 允许
> 唯一前缀缩写——那不是真参数名，将来多一个 `--outdir` 就会歧义报错。
> 靠 `--help` 而不是靠记忆。
>
> **输出目录放在 `.work/` 下**：`.gitignore` 只忽略 `dist/`，
> 裸的 `dist-fixture` / `dist-empty` 会出现在 `git status` 里等着被误提交。
> 上面两个场景已经写好了，照着跑就不会踩。
>
> 注意：这里产出的是**基于 fixture 或空 seed** 的站点。它证明流水线是通的，
> **不证明**真实数据是对的。不要把它当成"站点已上线"。

**清理：**

```bash
rm -rf .work/public-fixture .work/public-empty .work/dist-fixture .work/dist-empty
```
