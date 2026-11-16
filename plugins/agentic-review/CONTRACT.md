# agentic-review contract

The single source of truth for file names, folder layout, the record schema and the command-line scripts. Skills,
agents, hooks, workflows and scripts must all follow it. Change it here first.

## 1. The review folder

A review lives in its own folder, best opened as the session's working directory. Everything the plugin writes for
that review goes inside it. The hooks find the review from the working directory, from a file a call touches, or
from an absolute path a Bash command names; once a call of a session belongs to a review, the whole session (its
agents included) stays tied to it, so the guards also hold when Claude was started in a parent folder.

```
<review>/
├── review.json            settings (written by /agentic-review:new, edited by the user)
├── state.json             progress: phases, checkpoints, agents (written only through `ar-state`)
├── PROTOCOL.md            binding protocol every agent reads first (Phase 0)
├── schema.json            record schema of this review (Phase 0, extends templates/record.schema.json)
├── 1-discovery/           <ID>_records.jsonl, <ID>_notes.md, citation_candidates.jsonl
├── 2-merged/              merged.jsonl, merge_report.md, corpus.jsonl, refcheck_report.md, corpus_index.md,
│                          taxonomy.md (refined taxonomy, optional)
├── 3-analysis/            synthesis.md, background_refs.jsonl, comparison.md, comparison_class.jsonl
├── 4-checks/              rigor_scores.jsonl, rigor_report.md,
│                          omissions.jsonl, omissions_checked.jsonl, omissions_report.md,
│                          claims_check.jsonl, claims_report.md,
│                          code/ (code_records_<ID>.jsonl … per agent; joined by ar-code into
│                                 code_records.jsonl, repo_audit.jsonl, paper_code.jsonl; code_report.md)
├── 5-final/               review.md, lead_notes.md, retiering.json, counts.json, citation_map.tsv,
│                          catalogue.md, rigor_table.md, references.bib,
│                          ANNOTATION_GUIDE.md, packets/<key>.md, annotation_worklist.json, annotation_results.json,
│                          key_points.json, figures/ (figures.json, diagram .svg files, preview/)
├── 6-late/                <key>.json (late full-text verdicts)
├── 7-edition/             index.html, the launchers, README.md, zotero_snapshot.json (Zotero mode),
│                          <storage_key>-share.zip (ar-share)
├── .cache/<agent-id>/     downloaded API responses and PDFs (data, never executed)
├── .scripts/<agent-id>/   throwaway scripts written by agents
└── .agentic-review/       hook diagnostics (hooks.log) and the access table override (access.json)
```

Paths contain spaces on many systems: always quote them.

## 2. review.json

Written by `/agentic-review:new` from `templates/review.json`. Fields:

| Field | Meaning |
|---|---|
| `topic`, `question`, `time_window`, `scope_notes`, `language` | The settings of the original prompt |
| `tiers` | Always `["core", "boundary", "adjacent"]` |
| `scale` | `standard` or `mini`: picks the default targets (skills/run/phases.md) and scales `ar-estimate` |
| `autonomy` | `interactive` (default: the user approves checkpoints 1–3) or `autonomous` (set only by the user at setup: the orchestrator approves them with `ar-state … --auto`, runs to the reading edition and logs its decisions in `autonomous_log.md`) |
| `targets` | Optional overrides of those targets, e.g. `{"discovery_records": "20-30", "lead_words": "5000-6000"}` |
| `zotero.enabled`, `zotero.collection`, `zotero.tag`, `zotero.note_title` | Phases 2, 5 and 6 need Zotero; `enabled: false` skips them. Phase 7 runs either way: with Zotero, citations open the highlighted passage; without, the paper's DOI or arXiv page |
| `code_audit.enabled` | Runs the three code agents between Phase 3 and Phase 4 |
| `edition.title`, `edition.port`, `edition.storage_key` | The reading edition (Phase 7); optional `edition.kicker`, `footer`, `glossary`, `unnumbered`, `references_heading`, `limit_words`, `pilot` (see the Phase 7 section of skills/run/phases.md) |
| `review_sections` | Ordered section ids and headings the lead reviewer must write (checked by `ar-check-review`) |
| `models` | Optional model per role, passed to the Agent tool (`inherit` when absent) |
| `limits` | `annotators_parallel`, `confirm_above_agents` (sizes are `targets`) |
| `discovery_slices` | Written at checkpoint 1: `[{"id": "D1", "slice": "…", "owns_citation_chase": true}, …]` |

Optional fields the scripts read when present: `taxonomy` (family id → name), `rigor_rubric` (criterion id → name),
`display_fields` (extra columns of the corpus index and catalogue), `packet_fields` (record fields shown in
annotation packets), `estimates` (per-role duration and parallelism overrides for `ar-estimate`), `tier_aliases` (old tier
name → tier), `merge.concat_fields` (fields `ar-merge` concatenates instead of choosing one), `zotero.collection`
(a name or a collection key), `zotero.collections` and `zotero.tools` (written by the skills).

## 3. state.json

Only `ar-state` writes it. Shape:

```json
{
  "version": 1,
  "phase": "3",
  "phases": {"0": {"status": "done", "at": "2026-11-03T08:33"}},
  "checkpoints": {"1": {"status": "approved", "at": "…", "note": "…"}, "2": {"status": "pending"}},
  "agents": [{"id": "D1", "role": "discovery", "status": "done", "started": "…", "finished": "…"}],
  "log": [{"at": "…", "event": "…"}]
}
```

Phase ids are strings: `0` protocol, `1` discovery, `2` full texts, `3` analysis and checks, `3b` code audit
(optional), `4` lead review, `5` Zotero annotation, `6` late full texts, `7` reading edition.

Checkpoints and what they gate: **1** (end of Phase 0) gates every later phase; **2** (inside Phase 2) gates
Phase 3 when Zotero is enabled; **3** (the pilot inside Phase 5) gates the annotation fan-out; **4** (end of Phase 5)
gates Phase 6. `ar-state require <n>` and `ar-state next` are the gates; `ar-state phase` records a status and only
warns. Phases 2, 5 and 6 count as skipped when `zotero.enabled` is false, Phase 3b when `code_audit.enabled` is.

## 4. Records

One JSON object per line (JSONL, UTF-8), validated against `<review>/schema.json`. The base schema
(`templates/record.schema.json`) holds the fields every review needs. Phase 0 copies it and may add domain fields
(for example the data or acquisition setting of the field); it never removes base fields.

- `key`: first author's family name (lowercase ASCII) + the year of the paper's **first public version** (the
  preprint when there is one) + first significant title word, e.g. `smith2021deep`. Suffix `b`, `c`… on collision.
  Keys never change once written, even when the journal version appears later.
- `authors`: family name then initials, comma-separated, as listed: `"Smith J, van der Berg K, Li X"`; more than
  six authors: the first six, then `et al.`. `first_author`: the family name only (`"van der Berg"`).
- `year`: the year of the version the record describes. Citation labels use `cite_year` when set, else the
  version-of-record year found by `ar-refcheck` (the earliest of its online, print and conference dates), else
  `year`.
- `tier`: `core`, `boundary` or `adjacent`.
- `family`: one or more taxonomy ids separated by commas, e.g. `F3,F7`.
- `source_of_record`: a URL opened, or an API response received, in this session.
- `doi`, `arxiv_id`, `code.url`: `null` unless seen in a source. Never from memory.
- `evidence_depth`: `abstract`, `full-text` or `secondary`.
- Scripts may add their own objects (`ref_check`, `merge_notes`, `found_by`) but never edit an agent's fields.
  The one exception: `ar-refcheck` normalises `doi` and `arxiv_id` (URL prefixes, case, version suffix) and logs the
  original in `ref_check.normalised`. The version-of-record year and venue go in `ref_check.year_vor` and
  `ref_check.venue_vor`; an explicit `cite_year` on a record overrides the year used in citation labels.

`5-final/lead_notes.md` is shared: it starts with a section `## Orchestrator decisions`, which only the
orchestrator writes (decisions before the lead review, and changes after it, each dated); the lead reviewer keeps
that section as it is and writes its own sections below it.

When Claude Code refuses an agent's write of a report file ("Subagents should return findings as text…"), the
agent puts the report in its final message under `REPORT <path>`, and the orchestrator saves it to that path.

Other files (one JSON object per line unless stated):
- `3-analysis/background_refs.jsonl`: key, title, authors, year, venue, doi, arxiv_id, source_of_record.
- `4-checks/rigor_scores.jsonl`: key, title, evidence_depth, scores {R1…Rn}, total, max_possible, justifications,
  claimed_gain, red_flags, source_urls.
- `4-checks/claims_check*.jsonl`: claim_id, source_file, location, claim_text, paper_key, verdict, correct_value,
  evidence, source_url.
- `5-final/retiering.json` (one object): `{"<key>": {"tier": "…", "family": "…", "reason": "…"}}`.
- `5-final/key_points.json` (one object, written by the orchestrator in Phase 7, optional): `"_subtitle"` (one
  line under the title), `"_tiles"` (3 or 4 headline numbers: `[{"value": "62", "text": "papers catalogued …"}]`),
  and one entry per review section heading with 2 to 4 bullets that restate the section. `ar-edition` refuses a
  key point whose numbers do not appear in its section, and a tile whose number appears neither in the review nor
  in `counts.json`.
- `5-final/figures/figures.json` (written by the figure-designer agent in Phase 7, optional): `{"figures": [...]}`,
  one entry per figure: `id`, `type` (dots, bars, columns, scatter, heatmap, diagram, custom), `title`, `caption`,
  `place` (`section`, `after`), optional `source`, `mention`, and the fields of the type; diagrams and custom charts
  name an `.svg` file of the same folder, and custom charts declare their `axes`. Format and rules: `templates/figures/GUIDE.md`. `ar-edition` and `ar-figures check`
  refuse a figure whose numbers appear neither in the review, `counts.json` nor the record of the paper on that
  row, that names an unknown key or heading, whose SVG leaves the allowlist (elements, attributes, colour classes), or (custom) whose annotated marks
  or ticks do not sit where their values belong on the declared axes.
- `4-checks/code/*.jsonl`: see the code agents' briefs.

## 5. Scripts (`bin/`)

Python 3.9+, standard library only. Each script takes the review folder as its first argument, prints a short
summary, writes only the files listed here, and exits 0 when fine, 1 when it found problems, 2 on bad usage.
Shared code lives in `lib/arlib.py`. Network scripts send a generic User-Agent and never an email address.

| Script | Reads | Writes |
|---|---|---|
| `ar-state <dir> init\|show\|phase\|checkpoint\|agent\|require\|next …` | state.json | state.json |
| `ar-validate <dir> <file.jsonl>… [--quiet]` | schema.json (records); built-in shapes for the other JSONL files | — (report on stdout) |
| `ar-merge <dir>` | 1-discovery/*_records.jsonl | 2-merged/merged.jsonl, merge_report.md |
| `ar-refcheck <dir> <in.jsonl> <out.jsonl> <report.md> [--against corpus.jsonl] [--offline]` | CrossRef, arXiv (cached in .cache/refcheck/) | out.jsonl (adds `ref_check`), report; `--against` (automatic for omissions.jsonl) drops duplicates of the corpus |
| `ar-index <dir>` | 2-merged/corpus.jsonl | 2-merged/corpus_index.md |
| `ar-leftovers <dir>` | 1-discovery/citation_candidates.jsonl, 2-merged/corpus.jsonl | 2-merged/chase_leftovers.jsonl |
| `ar-count <dir>` | corpus.jsonl, omissions_checked.jsonl, retiering.json | 5-final/counts.json |
| `ar-citemap <dir>` | corpus, omissions, background refs | 5-final/citation_map.tsv |
| `ar-bib <dir> [--offline]` | the same three, doi.org and arXiv (cached in .cache/bib/) | 5-final/references.bib |
| `ar-check-review <dir> [--file F]` | 5-final/review.md, citation_map.tsv, review.json, 4-checks/code/paper_code.jsonl and lead_notes.md when the code audit ran (links to lines of code) | — (report on stdout) |
| `ar-relabel <dir> [--dry-run]` | 5-final/review.md, citation_map.tsv | review.md with labels from the map (matched by URL); previous version in review.before_relabel.md |
| `ar-share <dir> [--pdfs arxiv\|all\|none] [--dry-run]` | 7-edition/zotero_snapshot.json, the Zotero storage folder, the edition's inputs | 7-edition/<storage_key>-share.zip (index.html in share mode, papers/<key>.pdf, launchers, README) |
| `ar-catalogue <dir>` | corpus, omissions, retiering, rigor scores, citation map, 4-checks/code/code_records.jsonl (repositories and stars) | 5-final/catalogue.md, rigor_table.md |
| `ar-packets <dir>` | review.md, citation map, corpus, omissions, background references, retiering, comparison_class, claims_check, rigor_scores, schema.json | 5-final/packets/<key>.md |
| `ar-code <dir>` | 4-checks/code/*_<ID>.jsonl, corpus, omissions | 4-checks/code/code_records.jsonl, repo_audit.jsonl, paper_code.jsonl, code_report.md |
| `ar-estimate <dir> <n_agents> <role>` | review.json, past durations in state.json | — (estimate on stdout) |
| `ar-zotero-audit <dir>` | Zotero local API (read-only) | 5-final/zotero_audit.csv |
| `ar-edition <dir> [--snapshot F] [--no-zotero] [--refresh] [--out F]` | review.md, citation map, bib, catalogue, rigor table, counts, records, rigor scores, claim checks, key_points.json, figures/; Zotero local API (read-only) in Zotero mode | 7-edition/index.html, launchers, README.md, zotero_snapshot.json |
| `ar-figures check <dir>` · `preview <dir> [--png]` · `gallery [--out D] [--png]` | figures/, review.md, counts, records, rigor scores, claim checks, citation map; templates/figures/examples (gallery); Chrome or Chromium for `--png` | — · 5-final/figures/preview/ (index.html, <id>-light.png, <id>-dark.png) · the gallery folder |

Skills call scripts as `"${CLAUDE_PLUGIN_ROOT}/bin/<script>"` (the path is substituted when the skill loads).

## 6. Who reads what

Enforced by the `PreToolUse` hook from `hooks/access.json` (a review may override it with
`.agentic-review/access.json`). `deny_read` paths are relative to the review folder; `write` lists the only places
an agent may create or edit files.

This is a guard against mistakes, not a sandbox. File tools (Read, Write, Edit, Grep, Glob) are checked on their
resolved paths. Bash commands are checked only for the denied names written out in full: a wildcard
(`cat 3-*/synth*`), a recursive `grep -r .` or a script run from `.scripts/` can still open a denied file, and Bash
writes are not checked. The briefs tell agents to stay within their inputs; the hook catches the ordinary slips.

| Agent | May not read | May write |
|---|---|---|
| discovery | 2-merged, 3-analysis, 4-checks, 5-final | 1-discovery, .cache, .scripts |
| synthesis | 4-checks, 5-final | 3-analysis, .cache, .scripts |
| comparison | 4-checks, 5-final, 3-analysis/synthesis.md | 3-analysis, .cache, .scripts |
| rigor-checker | 3-analysis, 5-final | 4-checks, .cache, .scripts |
| omissions-checker | 3-analysis, 5-final | 4-checks, .cache, .scripts |
| claims-checker | 2-merged/merged.jsonl, 5-final | 4-checks, .cache, .scripts |
| code-finder | 3-analysis, 5-final | 4-checks/code, .cache, .scripts |
| repo-auditor | 3-analysis, 5-final | 4-checks/code, .cache, .scripts |
| paper-code-checker | 5-final | 4-checks/code, .cache, .scripts |
| lead-reviewer | — | 5-final, .scripts |
| annotator, late-pdf-checker | 3-analysis, 4-checks | 6-late, .scripts |
| figure-designer | — | 5-final/figures, .scripts |

The claims checker opens `3-analysis/` only to extract claims; it checks them against the papers.

The same hook guards the user's Zotero library for every caller, the orchestrator included: a Zotero tool whose
name says delete, trash, remove, empty, merge or purge is refused, so are the zotero-mcp calls that remove through
an input (a note's `delete` action, `remove_from`, `remove_tags`, `remove_keys`, replacing an item's tags,
collections or creators, an empty list included, or changing its item type), and zotero-mcp's add tool is refused unless
its own PDF lookup is off (`"attach_mode": "none"`), since that lookup queries Unpaywall. In the reading
edition, a highlight tagged for another review never counts as this review's, even on a shared PDF.
