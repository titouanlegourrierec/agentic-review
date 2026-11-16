# Changelog

## [0.1.0]

First public release.

- Eight phases (0 to 7) run by 13 specialised agents, from the protocol to a reading edition, with four checkpoints where
  you decide; `mini` and `standard` scales; an optional autonomous mode that logs every decision.
- Independent checks: rigor scores, an omissions search with its own strategy, and every claim of the analysis
  checked against the papers.
- Zotero: one agent per cited paper files it, attaches a free PDF and highlights the passage behind each
  statement; late PDFs are annotated and re-checked with `/agentic-review:add-pdfs`.
- A reading edition (one offline page, citations that open their Zotero highlight, figures drawn from the review's
  numbers) and `/agentic-review:share`, a zip with the cited PDFs and a viewer for readers without Zotero.
- An optional code audit (`run 3b`): repositories, reproducibility scores, and the analysis checked against the
  code with links to the lines.
- Hooks that guard who reads what, block requests carrying an email address and refuse Zotero deletions.
