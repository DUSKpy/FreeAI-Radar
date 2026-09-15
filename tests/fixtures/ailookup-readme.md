# Free LLM API Resources

> Exact free-tier limits pulled from official docs. Verified **March 29, 2026**.
>
> If the docs publish exact limits, they're listed. If they don't, we say so.
> Please don't abuse these services, or we lose them.

---

## Quick comparison

A rough guide, not apples-to-apples. Providers measure free usage in different ways. See each section for the exact numbers and catches.

| Provider | Best free model | Approx. daily budget | OpenAI SDK | CC req? | Trains? |
|:---|:---|:---|:---:|:---:|:---:|
| [Groq](#groq) | Llama 3.3 70B | ~1K req/day | Yes | No | Unknown |
| [Cerebras](#cerebras) | GPT-OSS-120B | ~14.4K req/day | Yes | No | Unknown |
| [SambaNova](#sambanova) | DeepSeek-R1 | 20 req/day | Yes | No | Unknown |
| [Google AI Studio](#google-ai-studio) | Gemini 2.5 Pro | ~dashboard-only | Yes | No | Free only |
| [OpenRouter](#openrouter) | `:free` variants | 50 to 1K req/day | Yes | No | No |
| [Z.AI](#zai) | GLM-4.7-Flash | Not published | Yes | No | Unknown |
| [Cloudflare Workers AI](#cloudflare-workers-ai) | Various | 10K neurons/day | Workers | No | Unknown |
| [NVIDIA NIM](#nvidia-nim) | Various | Not published | Yes | No | No |
| [Cohere](#cohere) | Command A / R / R+ | ~33 calls/day | No | No | Unknown |

---

## Groq

No credit card for the free path · OpenAI SDK compatible · Global  
Last verified: **2026-03-29**

Groq publishes a per-model matrix using `RPM`, `RPD`, `TPM`, and `TPD`. Limits are per-org, not per-key.

| Model | RPM | RPD | TPM | TPD |
|:---|---:|---:|---:|---:|
| llama-3.3-70b-versatile | 30 | 1,000 | 12,000 | 100,000 |
| llama-3.1-8b-instant | 30 | 14,400 | 6,000 | 500,000 |
| meta-llama/llama-4-scout-17b-16e-instruct | 30 | 1,000 | 30,000 | 500,000 |
| qwen/qwen3-32b | 60 | 1,000 | 6,000 | 500,000 |
| moonshotai/kimi-k2-instruct | 60 | 1,000 | 10,000 | 300,000 |
| moonshotai/kimi-k2-instruct-0905 | 60 | 1,000 | 10,000 | 300,000 |
| openai/gpt-oss-120b | 30 | 1,000 | 8,000 | 200,000 |
| openai/gpt-oss-20b | 30 | 1,000 | 8,000 | 200,000 |
| openai/gpt-oss-safeguard-20b | 30 | 1,000 | 8,000 | 200,000 |
| allam-2-7b | 30 | 7,000 | 6,000 | 500,000 |
| groq/compound | 30 | 250 | 70,000 | — |
| groq/compound-mini | 30 | 250 | 70,000 | — |

**Audio models** use extra audio-duration limits:

| Model | RPM | RPD | Audio sec/hr | Audio sec/day |
|:---|---:|---:|---:|---:|
| whisper-large-v3 | 20 | 2,000 | 7,200 | 28,800 |
| whisper-large-v3-turbo | 20 | 2,000 | 7,200 | 28,800 |

> Groq calls this a high-level summary. Exact live limits can vary. Check your account limits page for your org’s current values.

<details>
<summary>Paid pricing</summary>

| Model | Input | Output |
|:---|---:|---:|
| GPT-OSS-20B | $0.075 / 1M | $0.30 / 1M |
| GPT-OSS-120B | $0.15 / 1M | $0.60 / 1M |
| Kimi K2-0905 | $1.00 / 1M | $3.00 / 1M |
| Llama 4 Scout | $0.11 / 1M | $0.34 / 1M |
| Qwen3 32B | $0.29 / 1M | $0.59 / 1M |
| Llama 3.3 70B | $0.59 / 1M | $0.79 / 1M |
| Llama 3.1 8B | $0.05 / 1M | $0.08 / 1M |
| Whisper V3 Large | $0.111 / hr | — |
| Whisper Large v3 Turbo | $0.04 / hr | — |

</details>

[Rate limits](https://console.groq.com/docs/rate-limits) · [Pricing](https://groq.com/pricing/) · [Models](https://console.groq.com/docs/models)

---

## Cerebras

No credit card for the free path · OpenAI SDK compatible · Global  
Last verified: **2026-03-29**

Cerebras publishes `RPM`, `RPH`, `RPD`, `TPM`, `TPH`, and `TPD`.

| Model | RPM | RPH | RPD | TPM | TPH | TPD |
|:---|---:|---:|---:|---:|---:|---:|
| gpt-oss-120b | 30 | 900 | 14,400 | 64,000 | 1,000,000 | 1,000,000 |
| llama3.1-8b | 30 | 900 | 14,400 | 60,000 | 1,000,000 | 1,000,000 |
| qwen-3-235b-a22b-instruct-2507 | 30 | 900 | 14,400 | 60,000 | 1,000,000 | 1,000,000 |
| zai-glm-4.7 | 10 | 100 | 100 | 60,000 | 1,000,000 | 1,000,000 |

<details>
<summary>Paid pricing</summary>

| Model | Input | Output |
|:---|---:|---:|
| gpt-oss-120b | $0.35 / 1M | $0.75 / 1M |
| llama3.1-8b | $0.10 / 1M | $0.10 / 1M |
| qwen-3-235b-a22b-instruct-2507 | $0.60 / 1M | $1.20 / 1M |
| zai-glm-4.7 | $2.25 / 1M | $2.75 / 1M |

Pay-as-you-go tier limits after billing is linked:

| Model | TPM | RPM |
|:---|---:|---:|
| gpt-oss-120b | 1,000,000 | 1,000 |
| llama3.1-8b | 2,000,000 | 2,000 |
| qwen-3-235b-a22b-instruct-2507 | 500,000 | 500 |
| zai-glm-4.7 | 500,000 | 500 |

</details>

[Rate limits](https://inference-docs.cerebras.ai/support/rate-limits) · [Pricing](https://www.cerebras.ai/pricing)

---

## SambaNova

No credit card for the free tier · OpenAI SDK compatible · Global  
Last verified: **2026-03-29**

SambaNova uses flat free-tier limits: every free model gets **20 RPM · 20 RPD · 200,000 TPD**.

| Model |
|:---|
| DeepSeek-R1-0528 |
| DeepSeek-R1-Distill-Llama-70B |
| DeepSeek-V3-0324 |
| DeepSeek-V3.1 |
| Meta-Llama-3.3-70B-Instruct |
| Meta-Llama-3.1-8B-Instruct |
| Llama-4-Maverick-17B-128E-Instruct |
| gpt-oss-120b |
| Qwen3-235B-A22B-Instruct-2507 |
| Qwen3-32B |
| Llama-3.3-Swallow-70B-Instruct-v0.4 |
| E5-Mistral-7B-Instruct |
| Whisper-Large-v3 |

> Developer tier, with a payment method linked, publishes a shared 20M tokens/day budget across models.

<details>
<summary>Paid pricing</summary>

| Model | Input | Output |
|:---|---:|---:|
| DeepSeek-R1-0528 | $5.00 / 1M | $7.00 / 1M |
| DeepSeek-V3-0324 | $3.00 / 1M | $4.50 / 1M |
| DeepSeek-V3.1 | $3.00 / 1M | $4.50 / 1M |
| Meta-Llama-3.3-70B-Instruct | $0.60 / 1M | $1.20 / 1M |
| Llama-4-Maverick-17B-128E-Instruct | $0.63 / 1M | $1.80 / 1M |
| Qwen3-235B | $0.40 / 1M | $0.80 / 1M |
| Qwen3-32B | $0.40 / 1M | $0.80 / 1M |
| gpt-oss-120b | $0.22 / 1M | $0.59 / 1M |
| Meta-Llama-3.1-8B-Instruct | $0.10 / 1M | $0.20 / 1M |
| E5-Mistral-7B-Instruct | $0.13 / 1M | $0.00 / 1M |

</details>

[Rate limits](https://docs.sambanova.ai/docs/en/models/rate-limits) · [Pricing](https://cloud.sambanova.ai/plans/pricing)

---

## Google AI Studio

No credit card for the free tier · OpenAI SDK compatible  
Last verified: **2026-03-29**

Google’s pricing page confirms which models are free on the Gemini Developer API and says Google AI Studio usage is free of charge in supported regions. Google’s rate-limits page does **not** publish a stable public `RPM` / `RPD` / `TPM` table for each free model; it tells you to check the AI Studio dashboard instead.

**Stable models** with `Free of charge` input and output on the pricing page:

| Model | Free on pricing page | Public free RPM/RPD table | Notes |
|:---|:---:|:---:|:---|
| Gemini 2.5 Pro | Yes | No | 1M context. Paid pricing is public. |
| Gemini 2.5 Flash | Yes | No | Search and Maps free allowances are public. |
| Gemini 2.5 Flash-Lite | Yes | No | Highest public free grounding allowance in the 2.5 family. |
| Gemini 2.0 Flash | Yes | No | Free input/output on pricing page. |
| Gemini 2.0 Flash-Lite | Yes | No | Free input/output on pricing page. |

**Preview models** with `Free of charge` input and output on the pricing page:

| Model | Free on pricing page | Public free RPM/RPD table | Notes |
|:---|:---:|:---:|:---|
| Gemini 3 Flash Preview | Yes | No | Context caching also free on the pricing page. |
| Gemini 3.1 Flash-Lite Preview | Yes | No | Public paid pricing is listed. |
| Gemini 3.1 Flash Live Preview | Yes | No | Live audio model. |
| Gemini 2.5 Flash Native Audio | Yes | No | Free live API input/output on pricing page. |
| Gemini 2.5 Flash Preview TTS | Yes | No | Free text-in / audio-out on pricing page. |

**Not free** on the pricing page:

Gemini 3.1 Pro Preview · Gemini 3 Pro Image Preview · Gemini 3.1 Flash Image Preview

**Public free-tier extras** that Google does publish:

| Feature | Free tier |
|:---|:---|
| Google Search grounding on Gemini 2.5 Flash / Flash-Lite | 500 RPD shared |
| Google Maps grounding on Gemini 2.5 Flash / Flash-Lite | 500 RPD |
| Gemini 3 Search / Maps grounding | Not available on free tier |
| Code execution | Free of charge |
| URL context | Free of charge |
| File search | Free of charge |
| Batch API | Not available on free tier |

> Catch: free-tier content may be used to improve Google products. Paid-tier Gemini Developer API content is not used to improve products. Google has also changed free quotas without much warning before, so treat dashboard-only limits as unstable.

<details>
<summary>Paid pricing</summary>

| Model | Input | Output |
|:---|:---|:---|
| Gemini 3.1 Pro Preview | $2.00 / 1M up to 200K, $4.00 / 1M above 200K | $12.00 / 1M up to 200K, $18.00 / 1M above 200K |
| Gemini 3 Flash Preview | $0.50 / 1M text-image-video, $1.00 / 1M audio | $3.00 / 1M |
| Gemini 3.1 Flash-Lite Preview | $0.25 / 1M text-image-video, $0.50 / 1M audio | $1.50 / 1M |
| Gemini 2.5 Pro | $1.25 / 1M up to 200K, $2.50 / 1M above 200K | $10.00 / 1M up to 200K, $15.00 / 1M above 200K |
| Gemini 2.5 Flash | $0.30 / 1M text-image-video, $1.00 / 1M audio | $2.50 / 1M |
| Gemini 2.5 Flash-Lite | $0.10 / 1M text-image-video, $0.30 / 1M audio | $0.40 / 1M |

Paid grounding extras:

| Feature | Paid tier |
|:---|:---|
| Google Search grounding on Gemini 2.5 Flash / Flash-Lite | 1,500 RPD free, then $35 / 1,000 grounded prompts |
| Google Maps grounding on Gemini 2.5 Flash / Flash-Lite | 1,500 RPD free, then $25 / 1,000 grounded prompts |
| Google Search grounding on Gemini 2.5 Pro | 1,500 RPD free, then $35 / 1,000 grounded prompts |
| Google Maps grounding on Gemini 2.5 Pro | 10,000 RPD free, then $25 / 1,000 grounded prompts |
| Gemini 3 Search / Maps grounding | 5,000 prompts/month free, then $14 / 1,000 search queries |

</details>

[Pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) · [Billing](https://ai.google.dev/gemini-api/docs/billing) · [OpenAI compat](https://ai.google.dev/gemini-api/docs/openai)

---

## OpenRouter

No credit card for the free plan · No training on your data · OpenAI SDK compatible · Global  
Last verified: **2026-03-29**

OpenRouter measures free usage in `RPM` and `RPD`. All `:free` variants share the same core free limits.

| Limit | Value |
|:---|:---|
| RPM | 20 |
| RPD if lifetime purchased credits < $10 | 50 |
| RPD if lifetime purchased credits >= $10 | 1,000 |

The live free catalog changes. The pricing page currently advertises **25+ free models** rather than a fixed permanent set.

> Catch: free model availability shifts with provider supply. Failed requests still count toward the daily free quota, and free models can return `402` if your account balance is negative.

<details>
<summary>Paid pricing</summary>

Pay-as-you-go is provider price plus a 5.5% platform fee. OpenRouter says the model catalog price is what you pay for the underlying model.

</details>

[Limits](https://openrouter.ai/docs/api/reference/limits) · [Pricing](https://openrouter.ai/pricing) · [Free models](https://openrouter.ai/collections/free-models)

---

## Z.AI

No credit card for the free models · OpenAI SDK compatible · Global  
Last verified: **2026-03-29**

Z.AI publishes specific always-free Flash models and also marks several larger API models as `Limited-time Free`, but it does **not** publish a stable public numeric `RPM` / `RPD` table for the always-free API models.

| Model | Input | Cached input | Output |
|:---|:---:|:---:|:---:|
| GLM-4.7-Flash | Free | Free | Free |
| GLM-4.5-Flash | Free | Free | Free |
| GLM-4.6V-Flash | Free | Free | Free |

> Catch: the public rate-limits page is concurrency-based and the scraped output did not expose a stable numeric table for the always-free models. Cached hits are billed at 1/5 of original price on paid models, and cache storage is currently free.

<details>
<summary>Paid models</summary>

| Model | Input | Cached | Output |
|:---|---:|---:|---:|
| GLM-5 | $1.00 / 1M | $0.20 / 1M | $3.20 / 1M |
| GLM-5-Turbo | $1.20 / 1M | $0.24 / 1M | $4.00 / 1M |
| GLM-5-Code | $1.20 / 1M | $0.30 / 1M | $5.00 / 1M |
| GLM-4.7 | $0.60 / 1M | $0.11 / 1M | $2.20 / 1M |
| GLM-4.7-FlashX | $0.07 / 1M | $0.01 / 1M | $0.40 / 1M |
| GLM-4.5-Air | $0.20 / 1M | $0.03 / 1M | $1.10 / 1M |
| GLM-4.6V | $0.30 / 1M | $0.05 / 1M | $0.90 / 1M |

Built-in tools:

| Tool | Price |
|:---|---:|
| Web Search | $0.01 / use |

</details>

[Pricing](https://docs.z.ai/guides/overview/pricing) · [Rate limits](https://z.ai/manage-apikey/rate-limits)

---

## Cloudflare Workers AI

No credit card on Workers Free · Global  
Last verified: **2026-03-29**

Cloudflare doesn’t use request counts as the main free budget. It uses **Neurons**, a unit of GPU compute.

| Free budget | Reset |
|:---|:---|
| 10,000 Neurons/day | 00:00 UTC daily |

**Per-task rate limits**:

| Task type | RPM |
|:---|---:|
| Text Generation | 300 |
| Automatic Speech Recognition | 720 |
| Text Embeddings | 3,000 |
| Text-to-Image | 720 |

> Catch: the real free limit is the shared Neuron budget, not a fixed number of requests. Different models burn very different amounts of Neurons.

<details>
<summary>Paid pricing</summary>

| Item | Price |
|:---|:---|
| Base platform | $0.011 / 1K Neurons |
| @cf/openai/gpt-oss-120b | $0.350 / 1M input, $0.750 / 1M output |
| @cf/zai-org/glm-4.7-flash | $0.060 / 1M input, $0.400 / 1M output |
| @cf/nvidia/nemotron-3-120b-a12b | $0.500 / 1M input, $1.500 / 1M output |

</details>

[Pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) · [Limits](https://developers.cloudflare.com/workers-ai/platform/limits/)

---

## NVIDIA NIM

Free via Developer Program · OpenAI SDK compatible  
Last verified: **2026-03-29**

NVIDIA documents free hosted access for prototyping through the Developer Program and downloadable NIM microservices for research and development on up to 16 GPUs.

**NVIDIA does not publish a stable public per-model free quota table.**

> Catch: useful for prototyping and testing, but production use moves into NVIDIA AI Enterprise pricing.

<details>
<summary>Paid path</summary>

Production use requires NVIDIA AI Enterprise. The product docs describe this as starting at about `$4,500 / GPU / year`, or roughly `$1 / GPU / hour` in cloud environments.

</details>

[Product](https://docs.api.nvidia.com/nim/docs/product) · [Run anywhere](https://docs.api.nvidia.com/nim/docs/run-anywhere)

---

## Cohere

No credit card for the trial key · Cohere SDK first · Global  
Last verified: **2026-03-29**

Cohere uses a shared monthly API-call pool, plus per-endpoint rate limits.

**Trial key:** `1,000 API calls / month` total.

| Endpoint | Trial RPM | Production RPM |
|:---|---:|---:|
| Command A / Command A Reasoning / Command A Vision / Command A Translate | 20 | — |
| Command R+ | 20 | 500 |
| Command R | 20 | 500 |
| Command R7B | 20 | 500 |
| Audio Transcriptions | 5 | — |
| Embed | 2,000 inputs/min | 2,000 inputs/min |
| Embed Images | 5 inputs/min | 400 inputs/min |
| EmbedJob | 5 | 50 |
| Rerank | 10 | 1,000 |
| Tokenize | 100 | 2,000 |

> Catch: for Rerank, one search is one query with up to 100 docs. Long docs above 500 tokens get chunked, and each chunk counts.

<details>
<summary>Paid pricing</summary>

| Model | Input | Output |
|:---|---:|---:|
| Command | $1.00 / 1M | $2.00 / 1M |
| Command-light | $0.30 / 1M | $0.60 / 1M |
| Command R 03-2024 | $0.50 / 1M | $1.50 / 1M |
| Command R+ 04-2024 | $3.00 / 1M | $15.00 / 1M |
| Command R+ 08-2024 | $2.50 / 1M | $10.00 / 1M |
| Aya Expanse 8B / 32B | $0.50 / 1M | $1.50 / 1M |

</details>

[Rate limits](https://docs.cohere.com/docs/rate-limits) · [Pricing](https://cohere.com/pricing)

---

## Search, crawl, and extraction APIs

These are not hosted LLM inference providers. Their limit shapes are completely different, so they get their own section.

### Tavily

Last verified: **2026-03-29**

**1,000 credits/month** (renewing)

| Limit | Value |
|:---|:---|
| Dev keys | 100 RPM |
| Production keys | 1,000 RPM |
| Crawl | 100 RPM |
| Research | 20 RPM |

| Operation | Credits per call |
|:---|:---|
| Search basic | 1 / request |
| Search advanced | 2 / request |
| Extract basic | 1 / 5 successful URLs |
| Extract advanced | 2 / 5 successful URLs |
| Map regular | 1 / 10 pages |
| Map with instructions | 2 / 10 pages |
| Research pro | 15 to 250 / request |
| Research mini | 4 to 110 / request |

[Credits](https://docs.tavily.com/documentation/api-credits) · [Rate limits](https://docs.tavily.com/documentation/rate-limits)

### Exa

Last verified: **2026-03-29**

**1,000 requests/month** (renewing)

| Operation | Paid price |
|:---|:---|
| Search (<=10 results) | $7 / 1K requests |
| Search extra results | +$1 / 1K requests per result above 10 |
| Deep Search | $12 / 1K requests |
| Answer | $5 / 1K requests |
| Monitors | $15 / 1K requests |
| Contents | $1 / 1K pages per content type |

[Pricing](https://exa.ai/pricing)

### Firecrawl

Last verified: **2026-03-29**

**500 one-time credits** (not renewing)

| Operation | Credits | RPM |
|:---|:---|---:|
| Scrape | 1 / page | 10 |
| Crawl | 1 / page | 1 |
| Map | 1 / call | 10 |
| Search | 2 / 10 results | 5 |
| Browser | 2 / browser minute | — |

Extras: `PDF +1/page`, `JSON extraction +4/page`, `enhanced mode +4/page`, `ZDR +1/page`

[Pricing](https://www.firecrawl.dev/pricing) · [Rate limits](https://docs.firecrawl.dev/rate-limits)

---

## Trial credits and recurring tiny credits

These are not permanently free inference tiers.

| Provider | Offer | Duration | Catch |
|:---|:---|:---|:---|
| Google Cloud | $300 credit | 90 days | Credit card required |
| Vertex AI Express | Free express mode | 90 days | New Google Cloud users only; quota-limited |
| Fireworks | $1 credit | Until spent | 10 RPM without payment method |
| Inference.net | $25 credit | Until spent | Credit-limited, not a free tier |
| Hugging Face Inference Providers | $0.10 / month | Recurring | Routed requests only; subject to change |
| Vercel AI Gateway | $5 / month | Recurring | Free credit ends after first top-up |
| Alibaba Cloud Model Studio | Per-model free token pool | 30 to 90 days | Singapore region only |

---

## Self-hosted

Free software. You provide the hardware.

| Tool | What it is |
|:---|:---|
| [Ollama](https://ollama.com/) | Run models locally with one command |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | C/C++ inference engine |
| [LM Studio](https://lmstudio.ai/) | Desktop GUI |
| [vLLM](https://github.com/vllm-project/vllm) | High-throughput serving |
| [Jan](https://jan.ai/) | Local-first desktop assistant |
| [LocalAI](https://localai.io/) | OpenAI-compatible local server |

---

## Terms

`RPM` = requests/minute · `RPD` = requests/day · `RPH` = requests/hour · `TPM` = tokens/minute · `TPD` = tokens/day · `TPH` = tokens/hour · `ASH` = audio sec/hour · `ASD` = audio sec/day · `Neurons` = Cloudflare GPU compute unit

---

## Selection rules

1. Exact public numbers over breadth.
2. If docs publish limits, list them.
3. If docs don't publish limits, say so.
4. Don't infer requests from tokens or tokens from credits.
5. Each provider gets its own table shape instead of one forced universal schema.
