# `data/seed/`

这里放的是**冷启动用的种子状态**，不是数据。

## 只有一个文件

### `state.empty.json`

一个诚实的空状态。所有实体数组都是空的，`last_successful_collection_at` 和
`last_complete_collection_at` 都是 `null`——因为确实一次都没成功采集过。

它由 `radar.collect._empty_state()` 生成，不是手写的：

```bash
python -c "
import json, pathlib
from radar.collect import _empty_state
s = _empty_state()
pathlib.Path('data/seed/state.empty.json').write_text(
    json.dumps(s.model_dump(mode='json'), indent=2, ensure_ascii=False) + '\n',
    encoding='utf-8',
)
"
```

手写会漂移——字段一改，手写的种子就和代码对不上了。要改就走上面的生成命令。

## 它**不是**什么

**它不是一份可以充当真实目录的假数据。** 任务书在这一点上措辞很重：

> 没有真实数据可用时发布明确的"尚未成功采集"页面，不用 fixture 冒充真实目录。

所以：

- `tests/fixtures/state.minimal.json`（3 个 provider）只用**测试**，永远不进
  `data/`，也永远不会被 publish 工作流推到线上。
- `data/seed/state.empty.json` 是**空**的。用它构建出来的站点会显示"尚未成功采集"，
  这正是我们要的——它证明流水线是通的，同时如实告知"还没拿到数据"。
- 两者都不能拿来假装站点已经有内容。

## 什么时候用它

它存在的意义是让"第一次运行"这条路径**可测**：

```bash
# 从空状态走一遍完整流水线，确认每个环节都处理得了空目录
python -m radar.export_public \
  --state data/seed/state.empty.json \
  --output .work/public-empty \
  --base-path /

python -m radar.build_site \
  --data .work/public-empty \
  --out dist-empty \
  --base-path /
```

期望结果：构建成功，页面显示"尚未成功采集"，`provider_count` 是 `0`——
但这次 `0` 是**正确答案**，因为输入本来就是空的。

区分这两种 0 很重要：

| 情况 | `provider_count` | 含义 |
| --- | --- | --- |
| 空 seed 构建 | `0` | 正确。还没采集 |
| 真实 state 构建出 `0` | `0` | **故障**。数据在哪一步丢了 |

第二种曾经真的发生过——`load_versioned()` 把路径拼成了 `data/data/…`，
六个版本化文件全部静默加载成 `None`，退出码还是 0。见 `docs/release-checklist.md`
的 B1 项。

## 版本控制

这些文件**要提交**。它们是代码的一部分，不是产物。

`dist/`、`.work/`、`state.json` 都在 `.gitignore` 里——别把运行时状态提交上来。
真正跨运行持久化的状态走 `catalog-data` 分支，由 `persist` job 提交。
