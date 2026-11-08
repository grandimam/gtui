# gtui

**Design intelligence engine.** Point it at an application, get back a portable, evidence-backed
description of its *design language* — not just tokens — and hand that to a coding agent to apply
to your own app.

```bash
gtui capture https://linear.app          # explore, screenshot, measure (CSS + CDP), record states
gtui inspect linear                      # palette, type scale, spacing, recipes, principles, confidence
gtui preview linear                      # kitchen-sink HTML of the profile, no target app needed
gtui apply linear --target ./my-app      # analyze target, write hand-off bundle for your coding agent
gtui evaluate linear --url http://localhost:3000   # score the restyled app against the profile
```

> Status: v0.1 vertical slice. Deterministic capture → inference → IR → exports → hand-off → evaluation
> all work end to end. Multimodal critique, autonomous model-guided exploration, source-repo adapter,
> registry and native adapters are next (see Roadmap).

## What it produces

A **profile** — small, portable, framework-independent — stored once per machine under `~/.gtui/profiles/<name>/`:

```
aesthetic.json      the Aesthetic IR: tokens, component recipes, principles, character, confidence, unknowns
design.md           the same thing in prose, written for a coding agent
tokens.json         tokens only
components.json     recipes only
manifest.json       name, version, schema, source, coverage, confidence
exports/
  tailwind.css      Tailwind v4 @theme  (--color-surface-base, --text-sm, --radius-md, --ease-standard …)
  shadcn.css        shadcn/ui variables (--background, --primary, --muted-foreground, --ring, --radius …)
  theme.css         plain CSS custom properties
  tokens.dtcg.json  W3C Design Tokens (Style Dictionary, Tokens Studio, Figma)
  preview.html      kitchen sink rendered from the profile
```

Everything in the IR is **evidence-backed** (observation ids + coverage-based confidence) and anything
not observed is an explicit `unknown` — never invented.

## How it works

1. **Capture** (`src/gtui/adapters/web`). Playwright drives Chromium; a DOM walker records every visible
   element's computed styles, bounds, role and landmark region. The Chrome DevTools Protocol adds what
   computed styles lose: the *authored* `var(--token)` names behind each property
   (`CSS.getMatchedStylesForNode`), the source's own `:root` token definitions, and hover / focus-visible
   styling via `CSS.forcePseudoState` — no clicks, no form input, nothing destructive. The explorer only
   follows GET links, scores them for expected design information gain, and skips pages that add no
   new style signatures.
2. **Infer** (`src/gtui/inference`). Color roles come from *usage* (area-weighted surfaces, text
   contrast tiers, interactive backgrounds, borders, focus rings), never from hue alone. Type scale,
   spacing grid, radii, shadows, motion are histograms with adherence metrics. Component recipes
   (button variants, input, card, nav item, link, badge, headings) are expressed in token roles with
   observed state deltas. Character and principles are derived from those, each with the metric that
   justified it.
3. **Represent** (`src/gtui/ir`). Semantic names inside (`surface.raised`, `text.secondary`,
   `accent.primary`); every category maps 1:1 onto a Tailwind v4 namespace and, where one exists, a
   shadcn variable — so export is mechanical and the agent never has to learn gtui's vocabulary.
4. **Transfer** (`src/gtui/transfer`). gtui does **not** edit your code. `apply` detects the target's
   framework and styling dialect (Next/Vite, shadcn / Tailwind v4 / v3 / CSS), writes
   `.gtui/<profile>/` with the theme in that dialect, an ordered risk-rated `transfer-plan.json`, the
   constraints (preserve logic, IA, a11y; never copy brand assets) and a prompt — then your coding agent
   (Claude Code, Codex, …) does the editing it is already good at.
5. **Evaluate** (`src/gtui/evaluation`). Deterministic, reproducible compliance: palette, base surface,
   type scale, font family, spacing grid, radius scale, elevation strategy — with offenders and
   highest-impact recommendations. Perceptual critique layers on later.

## Install

```bash
uv sync --all-groups
uv run playwright install chromium
uv run gtui --help
```

Python 3.12+. `GTUI_HOME` overrides the store location (default `~/.gtui`).

## Capturing apps behind login

Don't bypass auth — **attach** to your own browser:

```bash
chrome --remote-debugging-port=9222      # log in yourself
gtui capture --connect localhost:9222 https://app.example.com --name example
```

gtui reuses your session read-only. Playwright storage state is also supported (`--storage-state`).

## Python API

```python
from gtui.api import capture, extract, evaluate

obs = await capture("https://example.com", name="example", max_pages=5)
profile = extract(obs)
print(profile.tokens.colors["accent.primary"].value, profile.principles[0].statement)
```

## Development

```bash
uv run pytest            # unit tests (synthetic observations) + integration test on tests/fixtures/site
uv run ruff check src tests && uv run ruff format src tests
```

`tests/fixtures/site` is a small, controlled dark/compact reference app; it doubles as the first
benchmark fixture.

## Roadmap

- Model-guided explorer (model as navigator, CDP as measurer)
- Multimodal visual critique in `evaluate`; refinement loop
- Source-repo adapter (Tailwind config / theme files / Storybook) as an augmenting evidence source
- `gtui export --format shadcn-components` (generated `cva` primitives from recipes)
- MCP server (`get_profile`, `plan_transfer`, `evaluate`) and profile registry (`install` / `publish`)
- Light/dark mode pairs, responsive variants, blending, native adapters

## License

MIT
