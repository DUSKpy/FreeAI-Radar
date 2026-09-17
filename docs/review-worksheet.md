# 人工核验工作表

本文件由 `python -m tests.review_worksheet` 生成，**不是**核验结果。它列出的是「该打开哪个页面、该确认哪一项」。

数据集 `sha256:db9a5f0a8ecbfc72fb39f5d3c1cbc146b98d6f6e7216b17259975ba7bfda6e36`，生成于 2026-09-17T11:45:09Z，共 **56 个提供商**。

| 现状 | 数量 |
| --- | --- |
| 完全没有官方来源佐证的提供商 | **55** |
| 三态字段仍为 `unknown` 的条目 | **128** |
| 已有官方页面佐证的 claim | **2** |

## 怎么用

1. 从下面挑一行，打开它的官方文档页。
2. **只看页面真的写了什么。** 页面没提的字段，只能填 `unknown` —— 「文档里没写」不等于「不需要」。
3. 按 `config/reviews.yaml` 顶部的字段说明写一条记录，`evidence_url` 指向你实际打开的那个页面。
4. 跑 `pytest -m "not network"` —— 核验层的 schema 与指纹会校验。

> **不要**为了减少这张表里的 `unknown` 而填 `not_need`。任务书把「把不知道说成不行」列为最严重的错误之一。

## 待核验提供商

按「最缺证据」排序。`三态待定` 是 `credit_card` / `phone_verification` / `registration` / `topup_required` 里仍无声明的项。

| # | 提供商 | 官方文档 | 三态待定 | 仅目录来源的字段 | 免费条目 | 来源数 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Rate limits | Gemini API | Google AI for Developers (`rate-limits-gemini-api-google-ai-for-developers`) | **无链接** | `credit_card`、`phone_verification`、`registration`、`topup_required` | — | 26 | 1 |
| 2 | Cloudflare Workers AI (`cloudflare`) | [打开](https://dash.cloudflare.com/) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 7 | 2 |
| 3 | Cohere (`cohere`) | [打开](https://cohere.com/) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 7 | 2 |
| 4 | GitHub Models (`github-models`) | **无链接** | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 3 | 1 |
| 5 | Google AI Studio (`google-ai-studio`) | [打开](https://aistudio.google.com/) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 7 | 2 |
| 6 | Groq (`groq`) | [打开](https://console.groq.com/) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 7 | 2 |
| 7 | Hugging Face (`huggingface`) | **无链接** | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 3 | 1 |
| 8 | Kilo Code (`kilo-code`) | **无链接** | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 3 | 1 |
| 9 | LLM7.io (`llm7-io`) | [打开](https://llm7.io) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 5 | 2 |
| 10 | Mistral AI (`mistral`) | **无链接** | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 3 | 1 |
| 11 | Z AI (Zhipu AI) (`z-ai-zhipu-ai`) | **无链接** | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 7 项 | 3 | 1 |
| 12 | Hetzner Inference API (`hetzner-inference-api`) | [打开](https://experiments.hetzner.com/inference) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 13 | Hugging Face Inference (`hugging-face-inference`) | [打开](https://huggingface.co/inference-api/serverless) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 4 | 1 |
| 14 | Inference.net (`inference-net`) | [打开](https://inference.net/) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 3 | 1 |
| 15 | Nous Portal (`nous-portal`) | [打开](https://portal.nousresearch.com) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 16 | Pollinations.ai (`pollinations-ai`) | [打开](https://pollinations.ai) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 2 | 1 |
| 17 | Requesty (`requesty`) | [打开](https://requesty.ai/) | `phone_verification`、`registration`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 18 | Agnes AI (`agnes-ai`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 1 |
| 19 | AI21 Labs (`ai21-labs`) | [打开](https://docs.ai21.com/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 4 | 2 |
| 20 | Aion Labs (`aion-labs`) | [打开](https://www.aionlabs.ai/pricing/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 4 | 2 |
| 21 | Alibaba Cloud Model Studio (`alibaba-cloud-model-studio`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 1 |
| 22 | Cerebras (`cerebras`) | [打开](https://cerebras.ai/inference) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 7 | 2 |
| 23 | Chutes.ai (`chutes-ai`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 2 | 1 |
| 24 | DeepSeek (`deepseek`) | [打开](https://platform.deepseek.com/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 2 |
| 25 | Glhf.chat (`glhf-chat`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 2 | 1 |
| 26 | Grok (xAI) (`grok-xai`) | [打开](https://console.x.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 5 | 2 |
| 27 | Nebius (`nebius`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 1 | 1 |
| 28 | Nscale (`nscale`) | [打开](https://www.nscale.com/product/inference) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 2 |
| 29 | NVIDIA NIM (`nvidia`) | [打开](https://build.nvidia.com/explore/discover) | `registration`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 4 | 2 |
| 30 | Ollama Cloud (`ollama-cloud`) | [打开](https://ollama.com/cloud) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 7 | 2 |
| 31 | OpenCode Zen (`opencode-zen`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 1 |
| 32 | OpenRouter (`openrouter`) | [打开](https://openrouter.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 7 | 2 |
| 33 | OVHcloud AI Endpoints (`ovhcloud-ai-endpoints`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 1 |
| 34 | SambaNova (`sambanova`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 1 |
| 35 | xAI (`xai`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 8 项 | 3 | 1 |
| 36 | Cline (`cline`) | **无链接** | `phone_verification`、`topup_required` | `access_type`、`capabilities`、`credit_card`、`offer_type` 等 6 项 | 3 | 1 |
| 37 | Coze (`coze`) | [打开](https://www.coze.com/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 6 项 | 2 | 1 |
| 38 | Mistral (La Plateforme) (`mistral-la-plateforme`) | [打开](https://console.mistral.ai/) | `registration`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 6 项 | 4 | 1 |
| 39 | OVH AI Endpoints (`ovh-ai-endpoints`) | [打开](https://endpoints.ai.cloud.ovh.net/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 6 项 | 4 | 1 |
| 40 | Venice.ai (`venice-ai`) | [打开](https://venice.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 6 项 | 3 | 1 |
| 41 | Z.AI (GLM) (`z-ai-glm`) | [打开](https://z.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 6 项 | 2 | 1 |
| 42 | Cerebrium (`cerebrium`) | [打开](https://www.cerebrium.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 43 | DeepInfra (`deepinfra`) | [打开](https://deepinfra.com/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 44 | Fireworks AI (`fireworks`) | [打开](https://fireworks.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 45 | Friendli AI (`friendli-ai`) | [打开](https://friendli.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 46 | Hyperbolic (`hyperbolic`) | [打开](https://app.hyperbolic.xyz/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 47 | Nebius (Token Factory) (`nebius-token-factory`) | [打开](https://tokenfactory.nebius.com/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 48 | Novita AI (`novita-ai`) | [打开](https://novita.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 49 | Qwen (Alibaba) (`qwen-alibaba`) | [打开](https://bailian.console.alibabacloud.com/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 50 | Replicate (`replicate`) | [打开](https://replicate.com/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 51 | SambaNova Cloud (`sambanova-cloud`) | [打开](https://cloud.sambanova.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 52 | Scaleway Generative APIs (`scaleway`) | [打开](https://console.scaleway.com/generative-api/models) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 53 | Upstage (`upstage`) | [打开](https://console.upstage.ai/) | `phone_verification`、`topup_required` | `access_type`、`base_url`、`credit_card`、`offer_type` 等 5 项 | 1 | 1 |
| 54 | Together.AI ⚠️ free research models need a $5 minimum deposit (`together-ai-free-research-models-need-a-5-minimum-deposit`) | [打开](https://together.ai/) | `phone_verification`、`topup_required` | `access_type`、`credit_card`、`offer_type`、`registration` | 1 | 1 |
| 55 | ModelScope (`modelscope`) | [打开](https://modelscope.cn) | `topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 9 项 | 4 | 2 |
| 56 | SiliconFlow (`siliconflow`) | [打开](https://siliconflow.com/pricing) | `topup_required` | `access_type`、`base_url`、`capabilities`、`context_window_tokens` 等 9 项 | 4 | 2 |

## 没有官方来源的提供商

这些提供商的每一条 claim 都来自第三方整理列表。它们**不是**错的，只是没有被官方页面确认过 —— 页面上的信息状态应当显示为 `directory`。

- `cloudflare` — Cloudflare Workers AI（7 个免费条目）
- `cohere` — Cohere（7 个免费条目）
- `github-models` — GitHub Models（3 个免费条目）
- `google-ai-studio` — Google AI Studio（7 个免费条目）
- `groq` — Groq（7 个免费条目）
- `huggingface` — Hugging Face（3 个免费条目）
- `kilo-code` — Kilo Code（3 个免费条目）
- `llm7-io` — LLM7.io（5 个免费条目）
- `mistral` — Mistral AI（3 个免费条目）
- `z-ai-zhipu-ai` — Z AI (Zhipu AI)（3 个免费条目）
- `hetzner-inference-api` — Hetzner Inference API（1 个免费条目）
- `hugging-face-inference` — Hugging Face Inference（4 个免费条目）
- `inference-net` — Inference.net（3 个免费条目）
- `nous-portal` — Nous Portal（1 个免费条目）
- `pollinations-ai` — Pollinations.ai（2 个免费条目）
- `requesty` — Requesty（1 个免费条目）
- `agnes-ai` — Agnes AI（3 个免费条目）
- `ai21-labs` — AI21 Labs（4 个免费条目）
- `aion-labs` — Aion Labs（4 个免费条目）
- `alibaba-cloud-model-studio` — Alibaba Cloud Model Studio（3 个免费条目）
- `cerebras` — Cerebras（7 个免费条目）
- `chutes-ai` — Chutes.ai（2 个免费条目）
- `deepseek` — DeepSeek（3 个免费条目）
- `glhf-chat` — Glhf.chat（2 个免费条目）
- `grok-xai` — Grok (xAI)（5 个免费条目）
- `nebius` — Nebius（1 个免费条目）
- `nscale` — Nscale（3 个免费条目）
- `nvidia` — NVIDIA NIM（4 个免费条目）
- `ollama-cloud` — Ollama Cloud（7 个免费条目）
- `opencode-zen` — OpenCode Zen（3 个免费条目）
- `openrouter` — OpenRouter（7 个免费条目）
- `ovhcloud-ai-endpoints` — OVHcloud AI Endpoints（3 个免费条目）
- `sambanova` — SambaNova（3 个免费条目）
- `xai` — xAI（3 个免费条目）
- `cline` — Cline（3 个免费条目）
- `coze` — Coze（2 个免费条目）
- `mistral-la-plateforme` — Mistral (La Plateforme)（4 个免费条目）
- `ovh-ai-endpoints` — OVH AI Endpoints（4 个免费条目）
- `venice-ai` — Venice.ai（3 个免费条目）
- `z-ai-glm` — Z.AI (GLM)（2 个免费条目）
- `cerebrium` — Cerebrium（1 个免费条目）
- `deepinfra` — DeepInfra（1 个免费条目）
- `fireworks` — Fireworks AI（1 个免费条目）
- `friendli-ai` — Friendli AI（1 个免费条目）
- `hyperbolic` — Hyperbolic（1 个免费条目）
- `nebius-token-factory` — Nebius (Token Factory)（1 个免费条目）
- `novita-ai` — Novita AI（1 个免费条目）
- `qwen-alibaba` — Qwen (Alibaba)（1 个免费条目）
- `replicate` — Replicate（1 个免费条目）
- `sambanova-cloud` — SambaNova Cloud（1 个免费条目）
- `scaleway` — Scaleway Generative APIs（1 个免费条目）
- `upstage` — Upstage（1 个免费条目）
- `together-ai-free-research-models-need-a-5-minimum-deposit` — Together.AI ⚠️ free research models need a $5 minimum deposit（1 个免费条目）
- `modelscope` — ModelScope（4 个免费条目）
- `siliconflow` — SiliconFlow（4 个免费条目）

## 疑似解析错误

这些条目的**名字**不是服务名，而是抓取时把网页标题或目录整行当了进去。名字会直接显示在目录页上，所以值得修 —— 但修法在采集侧，不在本文件。

| slug | 当前名字 | 看起来是 |
| --- | --- | --- |
| `rate-limits-gemini-api-google-ai-for-developers` | `Rate limits | Gemini API | Google AI for Developers` | 网页 `<title>` 或目录行原文 |
| `together-ai-free-research-models-need-a-5-minimum-deposit` | `Together.AI ⚠️ free research models need a $5 minimum deposit` | 网页 `<title>` 或目录行原文 |

## 疑似重复的提供商

两个 slug 看起来可能指同一家（一个有独特词包含在另一个里，或者去掉连字符后互相包含）。**这不一定是错的** —— 别名表顶部写得很清楚：「归一 ≠ 合并」，同一集团下的平台与模型家族、免费档与付费档，都应当保持两条。

所以这里只是把配对列出来让人看一眼。要不要归一由人判断，改的地方是 `config/aliases.yaml`。清单里出现误报是正常的 —— 比如 `alibaba-cloud-model-studio` 与 `qwen-alibaba` 就在别名表里被明确写成「不归一」。

| 条目 | 可能是 | 备注 |
| --- | --- | --- |
| `alibaba-cloud-model-studio` | `qwen-alibaba` | 需人工判断是否同一家 |
| `google-ai-studio` | `rate-limits-gemini-api-google-ai-for-developers` | 需人工判断是否同一家 |
| `grok-xai` | `xai` | 需人工判断是否同一家 |
| `hugging-face-inference` | `huggingface` | 需人工判断是否同一家 |
| `mistral` | `mistral-la-plateforme` | 需人工判断是否同一家 |
| `nebius` | `nebius-token-factory` | 需人工判断是否同一家 |
| `sambanova` | `sambanova-cloud` | 需人工判断是否同一家 |

