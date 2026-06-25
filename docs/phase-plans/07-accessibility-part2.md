# Phase 07 — Accessibility part 2 + Privacy (rest of doc Phase 10)

> Standalone plan. Execute, then run the loop (review → smoke-test → plan next). Phase 10 part 1 (contrast
> audit + alt text) is DONE; this is the remaining, mostly design-/browser-gated half. graphify-first.

## Why
Part 1 locked in WCAG AA contrast (and fixed two sub-AA themes) and wired alt text. The remaining a11y
gaps are real but each touches either **the look** (human-owned visual judgment) or the **browser-only
studio UI** (needs a real-browser smoke), so they were split out. Plus the privacy disclosure the doc
asks for. Lower-stakes than reliability work — cut freely.

## Tasks (each independent; cut from the bottom)
1. **Color-not-alone for callouts (WCAG 1.4.1) — DESIGN-GATED.** A `tutor_tip` / `key_points` / `warning`
   callout is distinguished only by color + border. Add a non-color cue (a per-variant icon and/or a
   default label like "⚠ Warning" when no title) in BOTH pack templates' callout macro + base.css. **This
   changes the rendered look** — the #1 priority — so propose 1–2 options and get the user's visual
   sign-off before committing (aesthetic study-notes usually DO have callout icons, so this is likely
   design-positive, but confirm). Term-definitions already satisfy 1.4.1 (bold + em-dash are non-color cues).
2. **Dyslexia-friendly / readability toggle.** A render option (settings or per-note) that (a) increases
   line-spacing/letter-spacing (WCAG 1.4.12 Text Spacing) and (b) optionally swaps body to a dyslexia-
   friendly font. OpenDyslexic is SIL OFL → bundle it like the other fonts (`assets/fonts/` + a pack/flag).
   Keep it OFF by default (don't disturb the default look). Test: rendered HTML includes the spacing/font
   when the flag is on, not when off.
3. **Studio keyboard / focus / ARIA — BROWSER-ONLY.** Audit the NiceGUI studio for: visible focus ring,
   logical tab order, no keyboard traps, ARIA labels on icon-only buttons (the editor has many icon
   buttons with only tooltips). NiceGUI/Quasar is fairly accessible by default; the gap is icon-only
   controls. Add `aria-label`/`.props('aria-label=…')` where a control is icon-only. Guard with a real-
   browser smoke (the `tests/test_*_smoke.py` harness): tab through the editor, assert focus is visible and
   the key controls are reachable + labelled.
4. **Automated a11y check in CI (optional).** Run an axe-core pass over a rendered note's HTML (e.g. via
   the Playwright `ui-smoke` job injecting axe and asserting no critical violations). Note: automated tools
   catch ~30–40% of issues — pair with the manual tasks above, don't over-trust a green axe run.
5. **Privacy disclosure + opt-in telemetry.** A plain-language statement (Settings/About) of what leaves
   the device: only the AI-structuring text sent to the chosen provider/proxy, plus the one-time Chromium
   download. There is currently **no telemetry** — keep it that way, or if any is ever added it must be
   **opt-in** + anonymized + clearly explained. This is mostly copy + a Settings line; low effort, high trust.

## Definition of Done
- Callouts convey variant without relying on color alone (with user-approved visual treatment).
- A readability/dyslexia toggle works and is tested; OFF by default.
- Icon-only studio controls have accessible names; a smoke proves keyboard reachability + visible focus.
- Privacy disclosure is visible in the app; telemetry (if any) is opt-in.

## Owner split
- **AI-autonomous:** dyslexia toggle + font bundling, ARIA labels, the keyboard smoke, axe-in-CI, privacy copy.
- **Human:** approve the callout visual treatment (task 1) and the dyslexia font choice; eyeball the toggle.

## Notes
- Carryover from part 1 to keep visible: the `quality`/`skeletal` theme `primary` was darkened to clear AA
  (`#B8860B→#8F6808`, `#6B7A45→#5F6E3C`) — confirm those still look right when you next eyeball the themes.
- Don't regress the default look: every new a11y feature here is OFF/opt-in by default except the (approved)
  callout cue.

## Alternative next phases (user re-steers)
- **Provider resilience** (`docs/phase-plans/06-provider-resilience.md`, already written): adaptive
  concurrency + token throttling + circuit breaker. Pure reliability.
- FSRS (doc 8); image occlusion (doc 11); export visual-regression golden (deferred from 05); carryover
  cleanups (home.py/settings raw `{exc}` → friendly_error; the 2 Phase-0 nits).
