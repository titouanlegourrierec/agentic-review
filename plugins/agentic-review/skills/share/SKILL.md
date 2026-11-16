---
name: share
description: Package the reading edition with the cited papers' PDFs in one zip that colleagues can open without Zotero - citations open the PDF in a viewer that shows the review's highlights and scrolls to the cited passage. Asks which PDFs to include (arXiv preprints only, all, or none). Usage /agentic-review:share.
disable-model-invocation: true
---

# agentic-review: share the reading edition

You are the orchestrator. Scripts are in `${CLAUDE_PLUGIN_ROOT}/bin/` (if not substituted, Glob for
`**/bin/ar-state` under `~/.claude/plugins`). This command starts no agent and changes nothing in
Zotero: it copies PDFs from the Zotero storage folder into a zip.

1. The review folder must have `zotero.enabled` true and a Zotero reading edition
   (`7-edition/zotero_snapshot.json`). Without Zotero, `7-edition/index.html` is already shareable as it is (its
   citations open publisher pages): say so and stop. Without the snapshot, tell the user to run
   `/agentic-review:run 7` first and stop.
2. Count what each choice would include: `"${CLAUDE_PLUGIN_ROOT}/bin/ar-share" "<dir>" --dry-run`. If it says the
   storage folder is missing, ask the user for their Zotero data directory (Zotero › Settings › Advanced › Files and
   Folders) and pass it as `--zotero-dir`; you may save it in `review.json` under `zotero.data_dir`.
3. Ask with AskUserQuestion which PDFs go in, giving the counts and sizes from step 2, and say plainly that whoever
   shares the zip is responsible for the right to share these PDFs (publisher licences, institutional agreements):
   - **arXiv preprints only** (recommended): PDFs carrying arXiv's stamp; publishers' versions are left out and
     their citations open the publisher's page;
   - **all PDFs**: every PDF in Zotero for the cited papers;
   - **no PDF**: the page alone, with publisher links.
   Never choose for the user. In a headless run without AskUserQuestion, use `--pdfs arxiv` and say so.
4. Run `"${CLAUDE_PLUGIN_ROOT}/bin/ar-share" "<dir>" --pdfs <choice>`. It writes
   `7-edition/<storage_key>-share.zip`. Report its counts as printed: the size, PDFs included and left out, and how
   many cited papers open a PDF.
5. Tell the user how colleagues open it: unzip, then run the launcher in the folder (`open-in-chrome.command` on
   macOS, `open-in-browser.bat` on Windows, `open-in-browser.sh` on Linux; it needs Python 3, and the window stays
   open while they read). Citations then open the PDF in the package's viewer, which shows the review's highlights
   in their colours, scrolls to the cited one and shows its note. Double-clicking `index.html` also works without
   Python: citations then open the PDF in the browser's own reader at the cited page (Chrome and Firefox; Safari
   opens the first page), without the highlights in the PDF. Hovering a citation shows the highlighted passage and
   its note either way. Keep the folder together.
