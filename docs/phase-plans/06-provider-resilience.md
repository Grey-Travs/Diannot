# Phase 06 — Provider Resilience: Adaptive Concurrency + Token Throttling + Circuit Breaker (doc Phase 5 remainder)

> Standalone plan for a fresh session. Execute, then run the loop (review → smoke-test → plan the
> next phase). Context: memory `diannot-prelaunch-loop` + the re-shared roadmap. **graphify-query the
> concurrency code FIRST** — line numbers below are from memory and may have drifted.

## Why this is next
The structuring engine's concurrency is a **fixed `2`** for both Claude and Gemini regardless of the
real, multi-bucket limits (requests/min, tokens/min, concurrency are separate ceilings). The ingestion-
robustness phase already did the *hard correctness* half of doc Phase 5 — typed errors, 503/quota drain
detection, bad-key eviction, `retryDelay` cooldowns, cross-engine failover, scaled timeouts. What
remains is the *adaptive* half: don't hammer a busy provider, don't sit idle when it's healthy, and stop
hammering a provider that's down. This is the next reliability item per the roadmap ("Phases 5–7 are the
next-most-important reliability") and matches the user's demonstrated reliability preference. It is
AI-autonomous with deterministic mocked-provider tests; one human live spot-check.

## What's already DONE (don't redo — verify with graphify first)
- Typed `GeminiRateLimited` / `GeminiKeyInvalid` (`providers.py`), drain detection (503 / RESOURCE_EXHAUSTED
  / quota, not just 429), **bad-key eviction** (`_DISABLED_SECONDS`), variable cooldown from parsed
  `retryDelay`, key-pool rotation (`_GeminiPool`).
- **Cross-engine failover**: whole-pool exhaustion → fall back Gemini→Claude (`_gen_text`/`_gen_vision`),
  degrade gracefully if Claude unusable.
- Vision **batching** (`_VISION_BATCH_PAGES=4`), bounded Claude vision (`asyncio.wait_for`), **scaled
  timeouts** (`_scaled_timeout`, 300→900s).
- Jittered backoff (`_sleep_before_retry`); `_PARALLEL["claude"]` lowered 6→2 (Opus rate-limit).

## What's NOT done (this phase)
1. **Adaptive concurrency** — replace the fixed `_PARALLEL` number with a limiter that *backs off* the
   concurrency on repeated 429/503 and *ramps up* when calls are clean, honoring the separate
   RPM/TPM/concurrency buckets. Keep a conservative floor (1) and a ceiling (the current 2, or a config
   value). Per-provider (the shared free Gemini key is tighter than a user's own Claude).
2. **Proactive token throttling** — estimate a request's token cost and throttle *before* a 429 fires,
   using returned rate-limit headers when present (Anthropic exposes per-bucket reset + `Retry-After`;
   Gemini's `retryDelay` is already parsed). A simple token-bucket / sliding-window per provider is
   enough; don't over-build.
3. **Circuit breaker** — if a provider returns sustained errors, trip a breaker (open → fail fast / route
   to the other engine for a cool-off window → half-open probe → close). "Retries handle individual
   failures; circuit breakers handle systemic failures." Compose with the existing cross-engine failover
   (the breaker decides *when* to stop trying a provider; failover decides *where* to go).

## Tasks
1. **Map the surface (graphify):** `graphify explain "structuring concurrency and the Gemini key pool"`,
   then read `structure.py` (`_PARALLEL`, the `ThreadPoolExecutor`/fan-out in `structure_text` /
   `_structure_image_batch_safe`, `_sleep_before_retry`, `_gen_text`/`_gen_vision`) and `providers.py`
   (`_GeminiPool`, `gemini_complete_pooled`, cooldown/eviction).
2. **Adaptive limiter:** a small per-provider controller object (NOT a closure capturing big scope — a
   class holding only the counters, per the efficiency rule) that yields the current max-concurrency.
   AIMD-style: multiplicative decrease on 429/503, additive increase on a clean streak. Feed it the typed
   error signals already raised. Thread it through the fan-out that currently reads `_PARALLEL`.
3. **Token-budget throttle:** estimate tokens (chars/4 heuristic is fine; reuse any existing token util),
   maintain a per-provider sliding-window budget, and `await`/sleep before a call that would exceed it.
   Honor `Retry-After` / `retryDelay` when present (already parsed for Gemini).
4. **Circuit breaker:** per-provider breaker with open/half-open/closed states + a cool-off; on open,
   short-circuit to the cross-engine failover path instead of sleeping-then-failing. Make sure a tripped
   breaker NEVER loses content — it must route to the existing degrade/preserve path, not raise.
5. **Tests (deterministic, mocked providers — NO live AI):**
   - Adaptive: simulate a burst of 429s → assert concurrency decreases; then clean calls → assert it
     ramps back up (bounded by floor/ceiling).
   - Throttle: a request that would exceed the window sleeps/defers (assert via a fake clock / monkeypatched
     sleep, like `test_structure_fallback.py::test_backoff_is_jittered`).
   - Breaker: sustained errors trip it; an open breaker fast-fails to failover and **never drops content**
     (assert the never-raise / `extraction_status` contract from the data-loss phases still holds).
   - Multi-bucket: a TPM-limit error and an RPM-limit error are handled distinctly (don't miscalculate the
     wait).

## Definition of Done
- Concurrency adapts under induced 429/503 (down then up), bounded by a floor/ceiling; no fixed `2`.
- A request is throttled *before* it would 429 when the token window is near-full.
- A provider returning sustained errors trips a breaker that routes to failover/degrade, never crashes,
  never loses content (the never-raise + `extraction_status` contracts still pass).
- All new tests deterministic + offline; full suite + the 5 browser smokes (run one-at-a-time) green.

## Owner split
- **AI-autonomous:** all code + deterministic mocked-provider tests.
- **Human:** one live load spot-check (e.g. a big multi-chunk import on the shared key) to confirm it
  *feels* resilient, not just unit-green.

## Cut-line / cautions
- Concurrency/rate-limit cautions in memory `claude-engine-gotchas` (Opus tight cap; ProcessError ≠
  RuntimeError; surface CLI stderr). Don't raise the Claude ceiling above 2 without evidence.
- These three tasks are independent — ship them as separate reviewable checkpoints (adaptive → throttle →
  breaker), cutting from the bottom if time-boxed. Adaptive concurrency alone is worthwhile.
- Do NOT over-build: a small AIMD limiter + token-bucket + 3-state breaker. No external deps.

## Alternative next phases (user re-steers each session)
- **Visual-regression golden** (the deferred STRETCH task from Phase 05) — human-gated golden image of a
  canonical note, pinned to Windows + tolerance. Guards *appearance*, not just *production*.
- **Accessibility** (doc Phase 10 half): contrast ≥4.5:1, color-not-alone for term-defs, keyboard/focus,
  alt text in the editor, dyslexia font/spacing toggle. Natural onboarding follow-on.
- **FSRS** scheduler (doc 8) — replace SM-2, keep it as a fallback.
- **Image occlusion** (doc 11) — highest-value study feature for anatomy/histology; bigger build.
- **Carryover cleanups:** `home.py` update + `settings.py` theme-create raw `{exc}` → `friendly_error`;
  the 2 deferred Phase-0 nits (`_do_update` UI-branch test, download progress bar); per-page text-vs-vision
  routing + confidence-based model escalation (doc Phase 9 remainder).
