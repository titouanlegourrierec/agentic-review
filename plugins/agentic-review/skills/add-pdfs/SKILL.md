---
name: add-pdfs
description: After you add PDFs to Zotero for papers the review only knew from their abstract, annotate each new PDF and re-check every statement the review makes about it (confirmed, upgraded or corrected), then rebuild the review and its counts. Phase 6, checkpoint 4. Usage /agentic-review:add-pdfs.
disable-model-invocation: true
---

# agentic-review: late full texts (Phase 6)

You are the orchestrator. Scripts are in `${CLAUDE_PLUGIN_ROOT}/bin/` (if not substituted, Glob for
`**/bin/ar-state` under `~/.claude/plugins`). Read `${CLAUDE_PLUGIN_ROOT}/CONTRACT.md` if you have not.

1. The review folder must contain `review.json` with `zotero.enabled` true and Phase 5 done
   (`ar-state "<dir>" show`). Otherwise explain what is missing and stop. The user typing this command approves
   checkpoint 4 (they have added the PDFs they could): `ar-state "<dir>" checkpoint 4 approve --note "add-pdfs run"`,
   then `ar-state "<dir>" phase 6 running`.
2. Find the new full texts: for each cited paper listed in `5-final/papers_without_pdf.md` (and any cited paper whose
   record has `evidence_depth: "abstract"`), check in Zotero whether a PDF attachment now exists. List them with
   their item and attachment keys in `6-late/worklist.json`. If there are none, tell the user, mark Phase 6 done
   (step 8) and stop.
3. Tell the user how many papers and how long it takes (`ar-estimate "<dir>" <n> late-pdf-checker`). Ask before starting when it
   is above `limits.confirm_above_agents`.
4. Run one `late-pdf-checker` per paper: the `late-pdfs` workflow (Workflow tool, name `agentic-review:late-pdfs`;
   if the name is unknown, `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/late-pdfs.js"`) with args
   `{"review_dir": "<dir>", "keys": [...], "parallel": <limits.annotators_parallel>}`, or individual agents (`subagent_type: "agentic-review:late-pdf-checker"`)
   for one or two papers. Each writes `6-late/<key>.json` with a verdict per statement: confirmed, upgraded (a hedge
   from the abstract-only reading can now be settled) or corrected, each with a page and a short quote.
5. **Re-check every upgrade and correction yourself** in the PDF before editing anything. Reject flags the PDF does
   not support, and say so.
6. Apply the accepted changes to `5-final/review.md` by script (never by hand-editing many places): remove stale
   "abstract-only" hedges, apply corrections to every place that states the corrected claim (search the whole review
   for its key words and numbers: the Summary, tables and conclusions included, and `key_points.json`), update the records' `evidence_depth` and any rigor scores the full text
   changes. Append a dated changelog section to `5-final/lead_notes.md` listing every edit and its source.
7. Recompute: `ar-count`, `ar-check-review`, `ar-catalogue`, `ar-packets` (packets of the changed papers),
   `ar-zotero-audit`. Update `5-final/papers_without_pdf.md`.
8. `ar-state "<dir>" phase 6 done` (also when step 2 found no new PDF; a later run sets it running again).
   Report: papers checked, verdict counts, edits applied, flags rejected. If an edition exists, offer to rebuild it
   (`/agentic-review:run 7 --refresh`).
