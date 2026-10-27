# Tool feedback log

Feedback on Nebius Token Factory and the NVIDIA models, from building Rescue Scout (October 2026).
Each entry says what we tried, what happened, and what would have helped.

## What worked well

| Tool / model | What happened |
|---|---|
| Token Factory API | OpenAI-compatible, so the standard `openai` Python package worked with a base URL and key change. No GPU setup or deployment to get a robot loop running. |
| Token Factory model catalogue | Several open vision models behind one API made it easy to benchmark Nemotron against alternatives by changing one model id. |
| Pricing | Per-token pricing kept a full search run to around a penny, so we could test freely on Builder Program credits. |
| Nemotron 3.5 Super VL | Found the target in 12 of 13 floor-level photos with 0 false alarms in 21. Accurate image positions for where objects touch the floor. |
| Nemotron 3.5 Super VL | Good instruction-following on strict JSON output: 1 unparseable reply in 19 on the first run, 0 after we shortened the prompt. |

## Problems and suggested fixes

| Date | Tool / model | What happened | Suggested fix |
|---|---|---|---|
| 2026-10-27 | Token Factory | We planned around Nemotron 3 Nano Omni and Cosmos 3 Super Reasoner, then found both were Dedicated-only for our account. Our first test run failed on every call. | Make Public vs Dedicated availability obvious in the model list and in the API error ("model not available on public endpoints") instead of a generic failure. |
| 2026-10-27 | Nemotron 3.5 Super VL | Answers image positions on a 0–1000 scale even when the prompt asked for 0–100, and occasionally mixed the two. Our first distance readings were wrong until we noticed. | Document the coordinate convention the VL model uses, and recommend prompting on that scale. |
| 2026-10-27 | Nemotron 3.5 Super VL | First version took about 4 s per decision (2.4–8.9 s). A short prompt, 512 px images and asking for no reasoning brought it to about 1 s. | Document per-request controls for turning reasoning off on VL models, and publish typical latency for vision models; robotics users need this. |
| 2026-10-27 | All vision models tested | Without an explicit definition, every model (Nemotron, Gemma 3, MiniCPM-V) said "obstacle close" on 18–19 of 19 photos. | A prompting guide for robotics / spatial tasks would help: define distances, ask for positions rather than distances. |
| 2026-10-27 | Vision models generally | Distance estimates in metres from a single image were unreliable; image positions were reliable. We converted positions to distance with our own camera calibration. | A model or guide aimed at depth / distance from a single camera would make Nemotron much easier to use on robots. |

## Numbers

| Measure | Value |
|---|---|
| Nemotron 3.5 Super VL, avg time per decision (after tuning) | about 1.0 s |
| Nemotron 3.5 Super VL, avg time per decision (first version) | about 4.0 s |
| Target found / false alarms (34 photos) | 12/13 found, 0/21 false alarms |
| Unparseable JSON replies | 1 of 19 (first run), 0 of 34 (tuned) |
| Cost of a full search run | about 1–2p |
