# Architecture Diagrams

Visual companions to [`ARCHITECTURE.md`](../../ARCHITECTURE.md). One SVG per diagram, so each can be
embedded anywhere independently (GitHub README, LinkedIn post, slides, docs).

SVG is vector, so it stays crisp at any size and the text stays selectable.

## The diagrams

| # | File | What it shows |
|---|------|---------------|
| 00 | [`00-whole-project.svg`](00-whole-project.svg) | The full pipeline end to end — PDF in, proven metrics out, split into the **Reading** half and the **Proving** half |
| 01 | [`01-profiler.svg`](01-profiler.svg) | **Stage 1** — describe every page (size, orientation, text quality) |
| 02 | [`02-geometry.svg`](02-geometry.svg) | **Stage 2** — split two-up A3 sheets into clean logical pages |
| 03 | [`03-locator.svg`](03-locator.svg) | **Stage 3** — score pages to find BS / PL / CF, prefer consolidated |
| 04 | [`04-extractor.svg`](04-extractor.svg) | **Stage 4** — rebuild borderless table rows from word coordinates |
| 05 | [`05-normalizer.svg`](05-normalizer.svg) | **Stage 5** — parse numbers, drop ref columns, fuzzy-match labels |
| 06 | [`06-validator.svg`](06-validator.svg) | **Stage 6** — prove values with accounting identities (no ground truth) |
| 07 | [`07-deriver.svg`](07-deriver.svg) | **Stage 6b** — fill MISSING values the identities pin down exactly |
| 08 | [`08-writer.svg`](08-writer.svg) | **Stage 7** — Excel output with receipts, colour-coded by trust |
| 09 | [`09-pipeline.svg`](09-pipeline.svg) | **The conductor** — `run()` order + tracing + where to make changes |
| 10 | [`10-unit-detector.svg`](10-unit-detector.svg) | **Stage 1b** — detect scale (crore/million), currency, period columns |
| 11 | [`11-llm-fallback.svg`](11-llm-fallback.svg) | **Stage 6a** — LLM proposes a line, the validator decides (optional) |

## Viewing them together

Open [`index.html`](index.html) in a browser for a single scrolling gallery of all 12.

## Converting to PNG

If a place needs raster (some LinkedIn upload flows, older slide tools):

**Inkscape** (best quality)
```bash
inkscape 00-whole-project.svg --export-type=png --export-dpi=200
```

**ImageMagick**
```bash
magick -density 200 00-whole-project.svg 00-whole-project.png
```

**Browser** — open the SVG, zoom to taste, screenshot. Fine for a quick share.

Colours match the app's status fills: green VERIFIED · yellow PROBABLE · red FLAGGED · grey MISSING · blue DERIVED.
