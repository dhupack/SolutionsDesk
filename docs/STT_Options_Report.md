# Speech-to-Text (STT) Options for SolutionsDesk Voice — Report

**Date:** 2026-06-19
**Author:** generated for the SolutionsDesk Voice live-transcription feature

---

## 1. What you have today

| Aspect | Current implementation |
|---|---|
| **Engine** | OpenAI `gpt-4o-transcribe` (REST), via the server route `/api/transcribe` in `app_new.py` |
| **Mode** | **Chunk-and-wait, not true streaming.** The PyQt window (`online_mode.py`) uses voice-activity detection: it buffers speech, waits for a ~silence gap to mark "end of sentence," then uploads that whole clip and waits for the reply. |
| **Accuracy aid** | `WHISPER_PROMPT` biases the model toward Axestrack/logistics jargon (overspeeding, ePOD, geofencing, ADAS, …) |
| **Hosting** | Flask backend on Render **free tier (512 MB RAM)**. `torch`/`transformers` are deliberately blocked at startup to save ~190 MB. |
| **Cost** | `gpt-4o-transcribe` = **$0.006/min ≈ $0.36/hr** of audio |

### The real bottleneck
Your accuracy is already good (gpt-4o-transcribe is a strong model). The weakness for "live transcript" is **latency and the chunked UX**: words don't appear *as you speak* — they appear one sentence at a time after a pause + upload + round-trip. Tools marketed for "fast live transcript" (Parakeet, Deepgram, AssemblyAI) solve this with a **WebSocket stream** that returns partial words in ~300 ms.

### Important clarification — "like Claude itself"
**Anthropic / Claude has no speech-to-text API.** Claude is text/vision only. Your architecture is already the correct pattern: a dedicated STT engine feeds text into the LLM (RAG) layer. So "better STT" = swapping the *transcription* engine, not the LLM.

---

## 2. The candidates

Two families to choose from:

- **A. Cloud streaming APIs** — managed, WebSocket, true live partials. Best fit for your Render-hosted, low-RAM backend. (Deepgram, AssemblyAI, Speechmatics, Gladia, OpenAI Realtime.)
- **B. Self-hosted open models** — Parakeet, Whisper. Cheapest per-hour at scale, full privacy, **but need a GPU** — they will *not* run on the current 512 MB Render free tier.

### Pricing & capability comparison (June 2026)

| Engine | Real-time? | Latency | Price (real-time) | Accuracy (English) | Custom vocab? | Notes |
|---|---|---|---|---|---|---|
| **OpenAI `gpt-4o-transcribe`** *(current)* | Chunked / batch | sentence-level (~1–3 s after pause) | **$0.006/min = $0.36/hr** | Excellent | Prompt hint (~224 tok) | What you run now. Simple REST. |
| **OpenAI `gpt-4o-mini-transcribe`** | Chunked / batch | same | **$0.003/min = $0.18/hr** | Very good | Prompt hint | Half the cost, small accuracy drop. |
| **OpenAI Realtime (gpt-realtime transcribe)** | ✅ true stream | low (~hundreds ms) | ~$0.017/min ≈ **$1.02/hr** | Excellent | Prompt hint | True streaming but the priciest option. |
| **Deepgram Nova-3** | ✅ true stream | **~300 ms** | **$0.0077/min = $0.46/hr** (PAYG); ~$0.39/hr committed | Excellent | ✅ **Keyterm prompting** (great for jargon) | Billed per-second. $200 free credit. Industry default for live. |
| **AssemblyAI Universal-Streaming** | ✅ true stream | **~300 ms** | **$0.15/hr** (!) base; Universal-3 Pro $0.45/hr | Very good → Excellent (Pro) | ✅ word boost | Cheapest *streaming* option. +10% in-region from 2026-07-01 (use `model_region:"global"` to avoid). |
| **Speechmatics** | ✅ true stream | low | **from $0.24/hr** | Excellent (strong on accents) | ✅ custom dictionary | Enterprise-leaning; strong multilingual/accent handling. |
| **Gladia Solaria-1** | ✅ true stream | low | **$0.55/hr** PAYG; from $0.25/hr growth | Very good | ✅ | 100+ languages, bundled diarization, native code-switching (good if Hindi+English mix matters). |
| **Groq `whisper-large-v3-turbo`** | ❌ batch only (ultra-fast) | 1 hr audio in ~10–15 s | **$0.04/hr** | Very good | Prompt hint | Astonishingly cheap + fast for *file* transcription, but **no native live streaming** — same chunk-and-wait UX as today, just cheaper. |
| **NVIDIA Parakeet-TDT 0.6B (self-host)** | ✅ (with streaming setup) | very low on GPU | **$0 license** + GPU infra | ~6% WER, top-tier | ✅ full control | CC-BY-4.0, multilingual (v3, 25 langs). 1 hr in ~1 s on GPU. **Needs a GPU host — won't fit current Render free tier.** |

---

## 3. What other platforms / products actually use

- **Voice agents & meeting assistants (Otter, Fireflies, voice-agent startups):** mostly **Deepgram** or **AssemblyAI** streaming — they're the de-facto standard for low-latency live captions.
- **Privacy-sensitive / high-volume / on-prem:** **self-hosted Parakeet or Whisper** on their own GPUs (e.g. AWS Batch, Northflank, Modal).
- **Multilingual / code-switching (e.g. Hindi+English in one sentence):** **Gladia** or **Speechmatics**.
- **Cheapest batch/file transcription:** **Groq Whisper Turbo** ($0.04/hr) — used where real-time isn't required.

---

## 4. Recommendations for SolutionsDesk Voice

Given your constraints (Render free tier, low RAM, logistics jargon, a sales rep needing answers fast during a live call):

### 🥇 Recommended: **Deepgram Nova-3 streaming**
- True live WebSocket transcript (~300 ms) — words appear as you speak, far better UX than the current pause-and-upload.
- **Keyterm prompting** is purpose-built for your jargon problem (overspeeding, ePOD, ADAS) and is more reliable than the current free-text Whisper prompt.
- $0.46/hr is only marginally more than your current $0.36/hr, with a much better live experience. $200 free credit to trial.
- Architecture fit: the **client** opens the Deepgram WebSocket directly (keep the key behind your backend via a short-lived token), so your 512 MB Render box does no audio work — it just keeps serving RAG.

### 🥈 Cheapest streaming upgrade: **AssemblyAI Universal-Streaming — $0.15/hr**
- ~⅓ the cost of today *and* true streaming. Use Universal-3 Pro ($0.45/hr) if base accuracy isn't enough.

### 🥉 Cheapest overall, keep current UX: **Groq Whisper Turbo — $0.04/hr**
- If you don't want to re-architect to streaming, just swap the backend call from OpenAI to Groq: ~9× cheaper, even faster file turnaround. Same "one sentence at a time" feel as today. Lowest-effort change.

### Not recommended right now: **self-hosted Parakeet**
- Best long-term cost & privacy, genuinely fastest, but it needs a **GPU host** — incompatible with your current Render free tier (where you've already stripped torch to fit 512 MB). Revisit only if you move to a GPU instance (Modal/Runpod/Northflank) and volume is high enough to justify it.

---

## 5. Suggested next step

| If your priority is… | Do this | Effort |
|---|---|---|
| Best live UX + jargon accuracy | Move client to **Deepgram Nova-3** WebSocket | Medium (client rewrite of capture loop, token endpoint) |
| Lowest cost with streaming | **AssemblyAI Universal-Streaming** | Medium |
| Lowest effort, big cost cut | Swap `/api/transcribe` to **Groq Whisper Turbo** | Low (change URL + key + model in `app_new.py`) |
| Privacy / on-prem at scale | **Parakeet on a GPU host** | High (new infra) |

A pragmatic two-phase path: **(1)** today, point `/api/transcribe` at Groq for an instant ~9× cost cut with zero UX change; **(2)** when you want true live captions, build a Deepgram streaming client.

---

## Sources

- [Deepgram Pricing 2026 (diyai.io)](https://diyai.io/ai-tools/speech-to-text/deepgram-pricing-2026/) · [Deepgram Nova-3 announcement](https://deepgram.com/learn/introducing-nova-3-speech-to-text-api) · [Deepgram per-minute breakdown](https://brasstranscripts.com/blog/deepgram-pricing-per-minute-2025-real-time-vs-batch)
- [AssemblyAI pricing](https://www.assemblyai.com/pricing) · [Universal-Streaming](https://www.assemblyai.com/universal-streaming) · [Universal-3 Pro Streaming](https://www.assemblyai.com/blog/universal-3-pro-streaming)
- [OpenAI API pricing](https://openai.com/api/pricing/) · [OpenAI Transcribe & Whisper pricing (costgoat, Jun 2026)](https://costgoat.com/pricing/openai-transcription)
- [Groq Whisper Large v3 Turbo](https://groq.com/blog/whisper-large-v3-turbo-now-available-on-groq-combining-speed-quality-for-speech-recognition) · [Whisper API pricing comparison (TokenMix)](https://tokenmix.ai/blog/whisper-api-pricing)
- [NVIDIA Parakeet-TDT (NVIDIA dev blog)](https://developer.nvidia.com/blog/turbocharge-asr-accuracy-and-speed-with-nvidia-nemo-parakeet-tdt) · [Best open-source STT 2026 (Northflank)](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks) · [Parakeet at scale on AWS Batch](https://aws.amazon.com/blogs/machine-learning/cost-effective-multilingual-audio-transcription-at-scale-with-parakeet-tdt-and-aws-batch/)
- [Speechmatics vs Gladia (Gladia)](https://www.gladia.io/blog/speechmatics-vs-gladia) · [Gladia pricing](https://www.gladia.io/pricing) · [Best real-time STT for meeting assistants 2026](https://www.gladia.io/blog/best-real-time-stt-models-for-meeting-assistants-2026)
