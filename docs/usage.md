# Usage

## Install

```bash
claude plugin marketplace add titouanlegourrierec/agentic-review
claude plugin install agentic-review@agentic-review
```

Inside a session, `/plugin marketplace add …` and `/plugin install …` do the same. Without access to GitHub from Claude
Code, download the zip of a [release](https://github.com/titouanlegourrierec/agentic-review/releases),
unzip it where it can stay, and run the same two commands with `./agentic-review-<version>` as the
marketplace. To try a local copy without
installing it: `claude --plugin-dir ./plugins/agentic-review`.

Requirements: Claude Code and Python 3.9+ (standard library only). Optional:
- **Zotero 7** with a Zotero MCP server that can add items, attach files, read PDF pages and create annotations
  and notes, such as [zotero-mcp](https://github.com/54yyyu/zotero-mcp). Without Zotero, phases 2, 5 and 6 are
  skipped, agents read free full texts online, and the reading edition links to DOI and arXiv pages.
- **The GitHub CLI** (`gh`), signed in, for the code audit (the public API works, rate-limited).
- **Chrome**, which remembers the permission to open `zotero://` links from the edition, and gives the figure
  agent PNG previews. **pandoc** is used when present; a built-in converter gives the same page.

## Commands

Run them in the review's folder. Commands that start agents run only when you type them.

| Command | What it does |
|---|---|
| `/agentic-review:new [--autonomous] [topic]` | Asks the settings, writes `review.json`, runs Phase 0 (protocol, tiers, taxonomy, schema, rubric), stops at checkpoint 1 |
| `/agentic-review:run` | Runs the next phases up to the next checkpoint; resumes an interrupted review |
| `/agentic-review:run 3` · `run 1:D3` | Reruns a phase, or one agent of it |
| `/agentic-review:run 3b [keys]` | The code audit alone, on some record keys or all, even when it is off in the settings |
| `/agentic-review:run 7 [--refresh]` | Builds or rebuilds the reading edition; `--refresh` rereads Zotero |
| `/agentic-review:status` | Where the review stands and what waits for you (read-only) |
| `/agentic-review:add-pdfs` | After you add PDFs to Zotero: annotates each one and re-checks every statement about it |
| `/agentic-review:share` | Packs the edition and the cited PDFs into one zip (asks which PDFs: arXiv only, all, or none) |

Before every fan-out the orchestrator says how many agents it will start and how long they should take, and asks
first above `limits.confirm_above_agents` (default 10).

## Settings

`/agentic-review:new` asks six things: the topic and question, the time window, Zotero or not, the code audit and
the language, the scale (`standard` or `mini`) and the mode. Then, before you approve checkpoint 1:

- **The protocol** (`PROTOCOL.md`, `schema.json`) holds the tiers, taxonomy, record fields, rigor rubric and evidence
  rules. Every agent reads it, so a change there reaches the whole team.
- **`review.json`** holds the rest: `review_sections` (the review's sections and their order), `targets` (the size
  of each stage), `models` (a model per role), `limits` (annotators in parallel, the fan-out that asks first),
  `edition` (title, port, number of figures).
- **`.agentic-review/access.json`** in the review folder replaces the plugin's
  [access rules](../plugins/agentic-review/hooks/access.json) for that review.

## Autonomous mode

`/agentic-review:new --autonomous <topic and settings>` (or "autonomous" when `/new` asks the mode) runs the whole
review to the reading edition without asking anything. The orchestrator checks the protocol and the annotation
pilot itself, approves checkpoints 1 to 3, continues with the free PDFs, and logs each decision it takes for you in
`autonomous_log.md`. It never adds late PDFs or shares PDFs for you. Claude Code still asks for tool permissions
unless your settings allow them; for an unattended run, use a folder of its own and, for example,
`claude -p "/agentic-review:new --autonomous …" --permission-mode acceptEdits`.

## What you get

| Path | Content |
|---|---|
| `5-final/review.md` | The critical review, with inline citations |
| `5-final/catalogue.md`, `rigor_table.md`, `references.bib` | Every paper, the rigor scores, the BibTeX file |
| `7-edition/index.html` | The reading edition, with launchers that serve it from localhost |
| `7-edition/<name>-share.zip` | The package to share, from `/agentic-review:share` |
| `4-checks/` | The independent checks: rigor, omissions, claim verdicts, and `code/` for the code audit |
| Zotero | A collection per review, a subcollection per family, highlights in five colours, one note per paper |

## Sharing

Citations in the edition open Zotero, so they work only on your computer. `/agentic-review:share` copies the cited
papers' PDFs from your Zotero storage into a zip with the page and a PDF.js viewer: colleagues unzip it and run the
launcher, and each citation opens the PDF at its highlight, with its note. Whoever shares the zip is responsible for
the right to share the PDFs in it; the default includes arXiv preprints only.
