"""Build the human-review worksheet for the catalogue.

Why this exists
---------------
`config/reviews.yaml` is the only place a `directory` claim can be upgraded to
`official_confirmed`, and it is deliberately empty -- nobody has actually sat
down and checked the providers' own pages. That is an honest state, but it is
also a dead end: the file cannot be filled from the collected data, because the
collected data is exactly the thing under review.

What CAN be automated is the boring half: for every provider, which fields are
still `unknown`, which fields rest on a single directory source, and which URL
to open. That turns "go verify 56 providers" into a checklist with a link per
row, and it keeps the judgement where it belongs -- with a person reading the
official page.

Deliberately NOT automated: writing the review entries. A review asserts "I
looked at this page and it says X". Generating that from a fetch would be the
exact dishonesty the three-state rule exists to prevent.

Usage:
    python -m tests.review_worksheet            # writes docs/review-worksheet.md
    python -m tests.review_worksheet --print    # to stdout instead
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "public" / "data"

#: The fields a review is allowed to override, grouped by how they are checked.
#: The TriState group is the one that matters most: a page that does not mention
#: a requirement cannot be read as "not required".
TRISTATE_FIELDS = ("credit_card", "phone_verification", "registration", "topup_required")
FACT_FIELDS = ("base_url", "protocols", "quota", "conditions", "offer_type", "region")

#: Fields whose current value is already trustworthy enough to skip. A provider
#: whose protocol list was read off its own docs page is not a review target for
#: protocols; one that came from a directory listing is.
#:
#: The two values are what `radar.claims` actually emits -- `directory` for a
#: third-party listing, `official` for the provider's own page. Getting these
#: wrong is silent: an unknown string simply matches nothing, every claim looks
#: directory-sourced, and the worksheet reports "0 official claims" for a
#: catalogue that has 375 of them.
OFFICIAL_SOURCE_LEVELS = ("official",)


def latest_catalog() -> Path:
    """The most recently written catalogue.

    By mtime, not by name. The filename carries a content hash, so sorting by
    name picks whichever hash happens to sort last -- which is a different file
    from the newest one, and it silently produced a worksheet for a dataset two
    days old.
    """
    files = sorted(DATA.glob("catalog.*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        sys.exit(f"no catalogue under {DATA}; run export_public first")
    return files[-1]


def load() -> dict:
    return json.loads(latest_catalog().read_text(encoding="utf-8"))


def build(catalog: dict) -> list[dict]:
    by_provider: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for claim in catalog["claims"]:
        if claim["subject_type"] != "provider":
            continue
        by_provider[claim["subject_id"]][claim["field"]].append(claim)

    offers_by_provider: dict[str, list[dict]] = defaultdict(list)
    for offer in catalog["offers"]:
        offers_by_provider[offer["provider_id"]].append(offer)

    rows: list[dict] = []
    for provider in catalog["providers"]:
        pid = provider["id"]
        fields = by_provider.get(pid, {})
        claims = [c for group in fields.values() for c in group]

        # Which fields rest on a directory listing rather than the provider's
        # own page. Those are the ones a review can actually improve.
        directory_only: list[str] = []
        for name, group in fields.items():
            if all(c["evidence"]["source_level"] not in OFFICIAL_SOURCE_LEVELS for c in group):
                directory_only.append(name)

        # TriState fields with no claim at all are `unknown` by construction,
        # which is the state the worksheet is trying to reduce.
        absent = [f for f in TRISTATE_FIELDS if f not in fields]

        offers = offers_by_provider.get(pid, [])
        rows.append(
            {
                "slug": provider["slug"],
                "name": provider["name"],
                "docs_url": provider.get("docs_url"),
                "homepage_url": provider.get("homepage_url"),
                "signup_url": provider.get("signup_url"),
                "domain_verified": provider.get("domain_verified", False),
                "sources": sorted({c["evidence"]["source_id"] for c in claims}),
                "official_claims": sum(
                    1 for c in claims if c["evidence"]["source_level"] in OFFICIAL_SOURCE_LEVELS
                ),
                "directory_only": sorted(directory_only),
                "tristate_absent": absent,
                "offer_count": len(offers),
                "offer_types": sorted({o.get("offer_type") or "?" for o in offers}),
            }
        )

    # Most reviewable first: providers with no official evidence at all, then by
    # how many tri-state fields are still open.
    rows.sort(key=lambda r: (-len(r["tristate_absent"]), -len(r["directory_only"]), r["slug"]))
    return rows


#: Words that say nothing about identity. "Nebius AI Cloud" and "Nebius" are
#: the same company; "Mistral" and "Mistral La Plateforme" may or may not be.
#: What distinguishes a real pair is a DISTINCTIVE word in common, so these are
#: excluded from the overlap test -- otherwise every provider with "ai" in its
#: slug matches every other one.
GENERIC_SLUG_WORDS = frozenset(
    {
        "ai",
        "api",
        "cloud",
        "inference",
        "endpoints",
        "models",
        "model",
        "studio",
        "labs",
        "lab",
        "platform",
        "serverless",
        "generative",
        "free",
        "the",
        "and",
    }
)


def find_suspects(catalog: dict) -> dict[str, list[tuple[str, str]]]:
    """Providers that look like a mis-parse or a duplicate of another row.

    Both are judgements, not facts, so this only SURFACES them -- it does not
    fix anything. The alias table is the place to act, and its own header is
    explicit that normalising a name is not the same as merging two policies:
    two entries can be the same company and still deserve to stay apart (a
    platform vs a model family, a free tier vs a paid one). Only a person can
    tell which case a given pair is.
    """
    suspects: dict[str, list[tuple[str, str]]] = {"parsed": [], "duplicate": []}
    seen_pairs: set[tuple[str, str]] = set()

    slugs = {p["slug"] for p in catalog["providers"]}
    for provider in catalog["providers"]:
        name = provider["name"] or ""
        slug = provider["slug"]

        # A name that is really a page title or a whole directory line. The
        # tell is punctuation no product name contains: a pipe from an HTML
        # <title>, a warning emoji, a sentence with a price in it.
        if "|" in name or "⚠" in name or name.count(" ") > 5:
            suspects["parsed"].append((slug, name))
            continue

        # Does this slug look like another one?
        #
        # Two tests, because neither alone catches the pairs that are actually
        # in this catalogue:
        #   "grok-xai"             vs "xai"                     -- keyword subset
        #   "hugging-face-inference" vs "huggingface"            -- flat contains
        #   "ovh-ai-endpoints"     vs "ovhcloud-ai-endpoints"    -- neither alone
        # The keyword test ignores generic words, so sharing "ai" or "cloud" is
        # not evidence; the flat test compares the slugs with hyphens removed,
        # which is what makes "huggingface" find "hugging-face-inference".
        #
        # Not proof either way -- "Nebius" and "Nebius Token Factory" are
        # deliberately separate entries -- so this only surfaces a pair for a
        # person to look at.
        flat = slug.replace("-", "")
        words = {w for w in slug.split("-") if w not in GENERIC_SLUG_WORDS}
        for other in sorted(slugs, key=len, reverse=True):
            if other == slug:
                continue
            flat_other = other.replace("-", "")
            words_other = {w for w in other.split("-") if w not in GENERIC_SLUG_WORDS}
            same_family = (len(flat) >= 5 and len(flat_other) >= 4 and flat_other in flat) or (
                words and words_other and (words <= words_other or words_other <= words)
            )
            if same_family:
                # Report each pair once. Without this the list doubles, because
                # the test is symmetric: "xai" finds "grok-xai" and "grok-xai"
                # finds "xai", and both rows are the same question.
                pair = tuple(sorted((slug, other)))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    suspects["duplicate"].append((slug, other))
                break

    return suspects


def render(rows: list[dict], catalog: dict) -> str:
    total = len(rows)
    no_official = [r for r in rows if r["official_claims"] == 0]
    open_tristate = sum(len(r["tristate_absent"]) for r in rows)

    out: list[str] = []
    out.append("# 人工核验工作表")
    out.append("")
    out.append(
        "本文件由 `python -m tests.review_worksheet` 生成，**不是**核验结果。"
        "它列出的是「该打开哪个页面、该确认哪一项」。"
    )
    out.append("")
    out.append(
        f"数据集 `{catalog['dataset_version']}`，生成于 {catalog['generated_at']}，"
        f"共 **{total} 个提供商**。"
    )
    out.append("")
    out.append("| 现状 | 数量 |")
    out.append("| --- | --- |")
    out.append(f"| 完全没有官方来源佐证的提供商 | **{len(no_official)}** |")
    out.append(f"| 三态字段仍为 `unknown` 的条目 | **{open_tristate}** |")
    out.append(f"| 已有官方页面佐证的 claim | **{sum(r['official_claims'] for r in rows)}** |")
    out.append("")
    out.append("## 怎么用")
    out.append("")
    out.append("1. 从下面挑一行，打开它的官方文档页。")
    out.append(
        "2. **只看页面真的写了什么。** 页面没提的字段，只能填 `unknown` —— "
        "「文档里没写」不等于「不需要」。"
    )
    out.append(
        "3. 按 `config/reviews.yaml` 顶部的字段说明写一条记录，"
        "`evidence_url` 指向你实际打开的那个页面。"
    )
    out.append('4. 跑 `pytest -m "not network"` —— 核验层的 schema 与指纹会校验。')
    out.append("")
    out.append(
        "> **不要**为了减少这张表里的 `unknown` 而填 `not_need`。"
        "任务书把「把不知道说成不行」列为最严重的错误之一。"
    )
    out.append("")
    out.append("## 待核验提供商")
    out.append("")
    out.append(
        "按「最缺证据」排序。`三态待定` 是 `credit_card` / "
        "`phone_verification` / `registration` / `topup_required` 里仍无声明的项。"
    )
    out.append("")
    out.append("| # | 提供商 | 官方文档 | 三态待定 | 仅目录来源的字段 | 免费条目 | 来源数 |")
    out.append("| --- | --- | --- | --- | --- | --- | --- |")

    for i, r in enumerate(rows, 1):
        url = r["docs_url"] or r["homepage_url"] or r["signup_url"]
        link = f"[打开]({url})" if url else "**无链接**"
        tri = "、".join(f"`{f}`" for f in r["tristate_absent"]) or "—"
        dir_only = "、".join(f"`{f}`" for f in r["directory_only"][:4]) or "—"
        if len(r["directory_only"]) > 4:
            dir_only += f" 等 {len(r['directory_only'])} 项"
        out.append(
            f"| {i} | {r['name']} (`{r['slug']}`) | {link} | {tri} | {dir_only} | "
            f"{r['offer_count']} | {len(r['sources'])} |"
        )

    out.append("")
    out.append("## 没有官方来源的提供商")
    out.append("")
    out.append(
        "这些提供商的每一条 claim 都来自第三方整理列表。它们**不是**错的，"
        "只是没有被官方页面确认过 —— 页面上的信息状态应当显示为 `directory`。"
    )
    out.append("")
    for r in no_official:
        out.append(f"- `{r['slug']}` — {r['name']}（{r['offer_count']} 个免费条目）")

    suspects = find_suspects(catalog)
    out.append("")
    out.append("## 疑似解析错误")
    out.append("")
    out.append(
        "这些条目的**名字**不是服务名，而是抓取时把网页标题或目录整行当了进去。"
        "名字会直接显示在目录页上，所以值得修 —— 但修法在采集侧，不在本文件。"
    )
    out.append("")
    if suspects["parsed"]:
        out.append("| slug | 当前名字 | 看起来是 |")
        out.append("| --- | --- | --- |")
        for slug, name in suspects["parsed"]:
            out.append(f"| `{slug}` | `{name}` | 网页 `<title>` 或目录行原文 |")
    else:
        out.append("（无）")

    out.append("")
    out.append("## 疑似重复的提供商")
    out.append("")
    out.append(
        "两个 slug 看起来可能指同一家（一个有独特词包含在另一个里，"
        "或者去掉连字符后互相包含）。**这不一定是错的** —— "
        "别名表顶部写得很清楚：「归一 ≠ 合并」，同一集团下的平台与模型家族、"
        "免费档与付费档，都应当保持两条。"
    )
    out.append("")
    out.append(
        "所以这里只是把配对列出来让人看一眼。要不要归一由人判断，"
        "改的地方是 `config/aliases.yaml`。清单里出现误报是正常的 —— "
        "比如 `alibaba-cloud-model-studio` 与 `qwen-alibaba` 就在别名表里"
        "被明确写成「不归一」。"
    )
    out.append("")
    if suspects["duplicate"]:
        out.append("| 条目 | 可能是 | 备注 |")
        out.append("| --- | --- | --- |")
        for slug, other in suspects["duplicate"]:
            out.append(f"| `{slug}` | `{other}` | 需人工判断是否同一家 |")
    else:
        out.append("（无）")

    out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="to_stdout")
    parser.add_argument("--out", default=str(ROOT / "docs" / "review-worksheet.md"))
    args = parser.parse_args()

    catalog = load()
    text = render(build(catalog), catalog)

    if args.to_stdout:
        print(text)
        return

    Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
