# Status

Version 0.3.1. The plugin is young: one `mini` review has run end to end through it, with and without Zotero.

## Verified

- **Scripts against the original run.** On a copy of the run this method came from, the scripts reproduce its
  outputs: the merge (193 records → 171 unique, the same 21 groups), the tier and family counts, 295 of 296
  citation-map rows, the 151 annotation packets, and a reading edition with the same 758 citations and links.
- **A mini review, end to end** (no Zotero, no code audit): 9 agents, 62 papers, 48 claims checked against the papers
  (37 supported, 8 partly, 3 contradicted), a 3,970-word review that passes `ar-check-review`, in 94 minutes. The
  hooks blocked no legitimate read.
- **Zotero phases, on the same review**: 39 core papers imported without duplicates, 33 free PDFs attached, 42 papers
  annotated (357 highlights in the five colours, one note each) by a pilot then 47 workflow agents; the run found
  and corrected two errors in the review. Nothing that existed in the library changed. Clicked `zotero://` links
  open in Zotero.
- **Hooks, live**: an independence breach blocked (a checker reading `3-analysis/`), Zotero deletions refused from
  the orchestrator, from a note's `delete` action and from a workflow agent.
- **Figures**: the six figures of the original review redrawn as specifications pass the number check and open the
  same 49 Zotero passages; on the mini review, the figure designer drew two charts, then a custom one, that pass it.
- **Code audit**, on three papers: two repositories found and pinned, scored 8/16 and 5/16; 22 claims checked
  (10 conform, 7 differ, 5 not found); one difference checked by hand at the audited commit.
- **Shared package**: built with every PDF (420 MB, 44 PDFs) and with arXiv preprints only (65 MB, 13 PDFs); the
  viewer draws the highlights and scrolls to the cited one.
- **Packaging**: the manifests validate, the plugin loads 5 commands, 13 agents and 4 hooks, and the unit tests
  pass on Python 3.9 and newer.

## Not yet verified

- A `standard`-scale review, Phase 6 (`/agentic-review:add-pdfs`), and the code audit on a whole corpus.
- Zotero set up by `/agentic-review:new` with its checkpoints answered in an interactive session; a paper already in
  your library reused by an annotator; two reviews sharing one PDF.
- Autonomous mode end to end.
- The live CrossRef, arXiv and doi.org lookups (tested offline, with a cache and a stub server).
- `run 3b` and `run 7` since the code audit and the edition became phases of `/run` (their steps are unchanged).
- Windows (the hooks call `python3`), Safari, and the viewer on very large PDFs.

## Not included

- Running papers' code: the code audit reads code only.
- Scheduled updates of a living review.
