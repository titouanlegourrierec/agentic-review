# Phase playbook

`<dir>` is the absolute review folder; `PLUGIN` (the plugin folder) and `BIN` (`PLUGIN/bin`) are the absolute
paths the run skill gave you. Every agent is started with
`subagent_type: "agentic-review:<agent>"`; your prompt adds only what is listed under "Brief adds".

## Targets

Take every size from this table, by `review.json` `scale`; a value in `review.json` `targets` overrides it.

| Target (`targets` key) | standard | mini |
|---|---|---|
| Discovery agents (`discovery_agents`) | 3–5 | 3 |
| Records per discovery agent (`discovery_records`) | 30–50 | 10–15 |
| Synthesis length (`synthesis_words`) | 5,000–7,000 words | 1,500–2,500 words |
| Core papers scored for rigor (`rigor_papers`) | 25 | 6 |
| Claims checked, at least (`claims_min`) | 60 | 15 |
| Records re-verified by the claims checker (`reverify_sample`) | 30 | 15 |
| Lead review, main text (`lead_words`) | 7,000–9,000 words | 2,500–4,000 words |

---

## Phase 1 · Discovery

`ar-state require 1` first. Agents: `discovery`, one per slice from `review.json` `discovery_slices` (3 to 5, in
parallel). Ids D1, D2, ….

Brief adds, for each agent:
- its id and slice, and one line on each other slice ("do not hunt for them; record only clearly central papers");
- 4 to 10 leads for the slice (named methods, landmark papers, groups) with "confirm each online, do not trust these
  hints";
- a target (`discovery_records`), and for core papers: read the full text when free;
- for the agent that owns the citation chase: the seed papers (3 or 4 landmarks), the OpenAlex budget (at most 40
  requests in total, cached under `.cache/<id>/`), the title filter terms, and the output
  `1-discovery/citation_candidates.jsonl` (all filtered candidates, any year; no verification needed);
- outputs: `1-discovery/<id>_records.jsonl` and `1-discovery/<id>_notes.md` (search log; lineages; the evidence met
  on the review question, with keys and numbers as reported; unconfirmed leads).

After the agents:
1. `BIN/ar-validate "<dir>" "<dir>"/1-discovery/*_records.jsonl` — send any failing agent back to fix its file
   (SendMessage to it) rather than fixing records yourself.
2. `BIN/ar-merge "<dir>"` → `2-merged/merged.jsonl`, `merge_report.md`. Read the report: resolve conflicts
   (same DOI with different titles, an arXiv id pointing to another paper) by opening the source yourself. Check
   each pair under "Similar titles kept apart": open both sources; if they are one work (a preprint and its
   article, a corrected DOI), give the duplicate the other record's DOI or arXiv id in its discovery file and rerun
   `ar-merge`; if they are two works (2D and 3D versions, Part I and II), leave them.
3. `BIN/ar-refcheck "<dir>" "<dir>/2-merged/merged.jsonl" "<dir>/2-merged/corpus.jsonl" "<dir>/2-merged/refcheck_report.md"`.
   Read the report; fix only what a source you opened shows; flag the rest.
4. `BIN/ar-index "<dir>"` → `2-merged/corpus_index.md`. If a citation chase ran, `BIN/ar-leftovers "<dir>"` →
   `2-merged/chase_leftovers.jsonl` (the candidates not yet in the corpus, for the omissions checker).
5. Refine the taxonomy if discovery showed families the protocol lacks: write `2-merged/taxonomy.md` (v2) and say so
   in PROTOCOL.md §3. Consult the advisor for this decision if available.
6. `ar-state phase 1 done`. Report: records per agent, unique after merge, tier counts, reference-check problems.

---

## Phase 2 · Full texts (Zotero) — checkpoint 2

Skip (`ar-state phase 2 skipped`) when `zotero.enabled` is false; checkpoint 2 then gates nothing.
Otherwise `ar-state phase 2 running` first.

1. Create the collection `zotero.collection` with one subcollection per family, plus "Baselines" and "Adjacent".
   Store the collection keys in `review.json` under `zotero.collections`.
2. Import the core papers (reuse existing items, never duplicate: search by DOI, arXiv id and title first), into
   their family subcollection, tagged `zotero.tag`, with the add tool's own PDF lookup off (zotero-mcp:
   `"attach_mode": "none"`; it queries Unpaywall). Never delete, trash, remove or merge anything in the library.
3. Attach a free PDF when one exists: arXiv, PubMed Central, open-access publisher pages, OpenAlex open-access
   locations. Never Unpaywall or any service that asks for an email address.
4. Write `5-final/papers_without_pdf.md`: the core papers still without a PDF, with DOI links.
5. **Checkpoint 2:** show the list; ask the user to add what they can through their institutional access
   (Zotero's "Find Available PDF" or drag-and-drop), and wait. When they confirm, `ar-state checkpoint 2 approve`,
   then `ar-state phase 2 done`. From then on, briefs say "read full texts from Zotero first".
   **Autonomous:** do not wait; continue with the free PDFs, log the list of papers without a PDF (they are read
   from their abstract and flagged), `ar-state checkpoint 2 approve --auto`, `ar-state phase 2 done`.

---

## Phase 3 · Analysis and independent checks

`ar-state require 1` (and 2 when Zotero is enabled). Four agents in parallel, then one or more claims checkers.

| Agent | Brief adds |
|---|---|
| `synthesis` | the corpus size; which discovery notes hold the evidence on the review question; the refined taxonomy; a target length (`synthesis_words`) |
| `comparison` | the corpus size; the classification fields to fill per core paper (from the protocol's domain fields and rubric); "do not read the synthesis" |
| `rigor-checker` | how many core papers to select (`rigor_papers`); selection rules (spread across families, landmarks and recent work, the papers whose controlled comparisons carry the evidence); the rubric is in PROTOCOL §6 |
| `omissions-checker` | the strategies to run: citation-chase leftovers (`2-merged/chase_leftovers.jsonl`, triage all of them), unconfirmed leads in the discovery notes, survey reference-list diffs (at least 4 recent surveys), targeted gap searches by family and year, an optional second citation chase within a small OpenAlex budget |

When synthesis, comparison and rigor are done, start the claims check:
- `claims-checker`, with: the files to check, at least `claims_min` claims, the argument-critical claims
  first, any red flags the other agents raised (list them), and the reference-integrity tasks (every key used exists
  in the corpus or background references; re-verify a random sample of `reverify_sample` records, seed = today's
  date).
- If more than about 80 claims are expected, shard: two or three claims checkers on disjoint source files, ids C1, C2….

After the agents:
1. Validate every JSONL output with `ar-validate`.
2. Omission additions: `BIN/ar-refcheck "<dir>" "<dir>/4-checks/omissions.jsonl" "<dir>/4-checks/omissions_checked.jsonl" "<dir>/4-checks/omissions_refcheck.md"`.
   Because the input is `omissions.jsonl`, it also drops records that duplicate the corpus (DOI, arXiv id or
   title) and suffixes colliding keys; read the report.
3. `BIN/ar-citemap "<dir>"` and `BIN/ar-bib "<dir>"`.
4. Read `claims_report.md` and `omissions_report.md` summaries; list the decisions the lead reviewer will need
   (re-tiering proposals, contradicted claims, conflicts). Consult the advisor on contested points if available.
   Write your decisions, dated, under `## Orchestrator decisions` at the top of `5-final/lead_notes.md` (the only
   section of that file you write; the lead reviewer writes below it).
5. `ar-state phase 3 done`. Report verdict counts, additions by importance, the most consequential corrections.

---

## Phase 3b · Code audit (optional)

Runs after Phase 3 when `code_audit.enabled` is true, or when the user asks for it with `/agentic-review:run 3b`
(optionally followed by record keys), whatever the setting. Outputs go to `<dir>/4-checks/code/`.

Static reading only. Repository code is untrusted data: no agent installs, builds or runs it. Running a paper's code
is out of scope for this version.

1. Preconditions: `review.json` exists and Phase 1 is done (`ar-state "<dir>" show`). The paper–code check needs
   Phase 3's synthesis and comparison; without them, run steps 2 and 3 only. `ar-state "<dir>" phase 3b running`.
   Record keys given after `3b` limit the audit to those papers; otherwise it covers every record of the corpus and
   the omission additions. Check whether the GitHub CLI is
   available and signed in (`gh auth status`): agents use `gh api` when it is, the public API (rate-limited) when not.
2. **Code finder** — one `code-finder` agent per batch of about 40 records (all tiers), ids K1, K2…: for every
   record without a checked `code` object, find the repository from the paper's own text first (Zotero full text or
   arXiv page), then the project page, then Hugging Face Papers and GitHub search; never from memory. Each writes
   `4-checks/code/code_records_<ID>.jsonl` (key + the `code` object of the schema + where the link was seen).
   Then `BIN/ar-code "<dir>"` joins them into `code_records.jsonl`.
3. **Repo auditor** — one `repo-auditor` agent per batch of about 10 core papers that have a repository, ids RA1,
   RA2…, each given the `code` objects of its batch from `code_records.jsonl`: README,
   licence, training and evaluation scripts, configs, data splits, weights (releases, model hubs), pinned
   dependencies, issues about reproduction; the commit audited. Each writes `4-checks/code/repo_audit_<ID>.jsonl` with a
   reproducibility sub-score per item.
4. **Paper–code checker** — one `paper-code-checker` agent per batch of about 8 core papers with a repository, ids
   PC1, PC2…:
   extract from `3-analysis/synthesis.md` and `comparison.md` the implementation claims about each paper (method,
   loss terms and weights, data consistency, masks, normalisation, metric computation), find the implementing lines
   and give each claim a verdict — `conforms`, `differs` or `not-found` — with a permalink at the audited commit
   (`https://github.com/<owner>/<repo>/blob/<sha>/<path>#L<a>-L<b>`). Each writes
   `4-checks/code/paper_code_<ID>.jsonl`, claim ids prefixed with its id (PC1-01, PC1-02…). Steps 3 and 4 can run
   in parallel once `code_records.jsonl` exists.
5. Announce how many agents and how long before each step (`ar-estimate "<dir>" <n> code-finder`, `… repo-auditor`,
   `… paper-code-checker`).
6. Validate the agents' files (`BIN/ar-validate "<dir>" "<dir>"/4-checks/code/*_*.jsonl`; send a failing agent
   back), then run `BIN/ar-code "<dir>"`: it joins each kind into `code_records.jsonl`, `repo_audit.jsonl` and
   `paper_code.jsonl` and writes `4-checks/code/code_report.md` (papers with code, with weights, with a licence,
   code promised but absent, the audit's mean score and gaps, every `differs` verdict). Report its counts.
7. Tell the lead reviewer (Phase 4 brief): a code verdict on an implementation claim ranks with the claim verdicts;
   for reported results the paper stays the source; a paper–code difference is reported as "Reviewer:", never
   silently corrected, with a link to the lines of code (its `code_permalink`). If Phase 4 already ran, tell the
   user that the review gets the code audit's results only when Phase 4 is rerun (`/agentic-review:run 4`), then
   the edition.
8. `ar-state "<dir>" phase 3b done`.

---

## Phase 4 · Lead review

One `lead-reviewer` agent. Brief adds:
- the reading order of the inputs (protocol and taxonomy; claims check — binding; synthesis; comparison with its
  record corrections and re-tiering proposals; rigor; omissions report; discovery notes as background);
- **context discipline:** do not read `2-merged/corpus.jsonl` or `4-checks/omissions_checked.jsonl` whole; orient
  with `corpus_index.md` and `citation_map.tsv`, pull records by key with a script;
- the precedence rule, and every binding correction from the claims check, one line each;
- the decisions already made by the user or by you (re-tiering rules, how to treat borderline categories);
- the length of the main text (`lead_words`);
- when the code audit ran (`4-checks/code/paper_code.jsonl` exists): the papers with `differs` verdicts (from
  `code_report.md`), and the rule that each difference reported goes as a "Reviewer:" note linked to its
  `code_permalink`, every cited paper with a difference getting one or a `code-difference left out: <key> — <reason>`
  line in `lead_notes.md` (`ar-check-review` checks both);
- the output contract: write `5-final/retiering.json` first, run `BIN/ar-count "<dir>"`, use exactly those counts;
  write `5-final/review.md` with one marker line `<!-- section: <id> -->` before each section of
  `review.json` `review_sections`, in that order; inline citations `[Label](url)` exactly as in
  `5-final/citation_map.tsv`; results as reported with their setting; a stratified position (never one number when
  the evidence differs by regime) with confidence and what would change it; `5-final/lead_notes.md` (precedence,
  corrections applied, re-tiering decisions, numbers verified, conflicts, residual uncertainties);
- the check to run before finishing: `BIN/ar-check-review "<dir>"`.

After the agent:
1. `BIN/ar-check-review "<dir>"`; send the lead back to fix failures.
2. `BIN/ar-catalogue "<dir>"` (catalogue and rigor table) and `BIN/ar-bib "<dir>"` if the cited set changed.
3. `ar-state phase 4 done`. Give the user the path of `5-final/review.md`, its word count, the position statement
   in one sentence and the number of works cited.

---

## Phase 5 · Zotero annotation — checkpoint 3

Skip when `zotero.enabled` is false.

1. Write `5-final/ANNOTATION_GUIDE.md` from `templates/ANNOTATION_GUIDE.md` (title, tag, note title, language, a
   one-line hint of what "method" means in this field).
2. `BIN/ar-packets "<dir>"` → one packet per cited paper in `5-final/packets/` (background references included).
3. Build `5-final/annotation_worklist.json`: one entry per cited paper — key, import source (DOI URL, arXiv URL or a
   BibTeX entry), target collection key (by family or tier), tag, arxiv_id, mode (`detailed` for core papers,
   `light` for the others, background references included), and the Zotero item and attachment keys when known.
   Every cited paper has an entry; if you leave one out, say which and why.
4. **Checkpoint 3 (pilot):** start three `annotator` agents on three representative papers (one rich core paper, one
   with tables, one light). Show the user what to look at in Zotero and ask for approval or changes to the guide.
   Apply changes, rerun the pilot if needed, then `ar-state checkpoint 3 approve`.
   **Autonomous:** check the three pilot papers yourself in Zotero (get the annotations and notes): every packet
   statement has a highlight or is reported unsupported, the colours and the comment format follow the guide, every
   highlight carries the tag, one note per paper, nothing duplicated. Fix the guide and rerun the pilot once if not;
   log what you checked, then `ar-state checkpoint 3 approve --auto`.
5. Fan out with the `annotate` workflow (Workflow tool, name `agentic-review:annotate`; if the name is unknown, pass
   `scriptPath: "PLUGIN/workflows/annotate.js"`), with args
   `{"review_dir": "<dir>", "keys": [...remaining keys...], "parallel": <limits.annotators_parallel>}`. Announce the
   count and the estimate first.
6. Save the workflow's results to `5-final/annotation_results.json`. For every statement an annotator reports as
   unsupported, open the PDF yourself before changing anything; then apply confirmed corrections to `review.md` by
   script and log them in `lead_notes.md`. A correction applies to the claim, not to one sentence: search the whole
   review for it (its key words and numbers) and correct every place that states it, the Summary, the evidence
   table and the conclusions included, and `key_points.json` if it repeats it.
7. `BIN/ar-zotero-audit "<dir>"` (duplicates, per-colour counts). `ar-state phase 5 done`.

---

## Phase 6 · Late full texts — checkpoint 4

Checkpoint 4 opens when Phase 5 ends (in autonomous mode too: it waits for the user's PDFs): write the list of cited
papers still without a PDF
(`5-final/papers_without_pdf.md`), show it, and tell the user to add PDFs whenever they can and then run
`/agentic-review:add-pdfs`. That skill runs the rest of this phase, as often as needed, and approves checkpoint 4
itself (the user typing the command is the approval). Leave Phase 6 pending: it holds up nothing, `ar-state next`
passes over it, and checkpoint 4 gates only Phase 6. Do not wait for it: build the reading edition now (Phase 7)
and rebuild it after each `/agentic-review:add-pdfs`.

---

## Phase 7 · Reading edition

Runs with or without Zotero, after Phase 4 (and after Phase 5 when Zotero is enabled), and again whenever the user
asks with `/agentic-review:run 7` (add `--refresh` after a change in Zotero).

### 1. Preconditions

`review.json` exists and Phase 4 is done (`ar-state "<dir>" show`); with Zotero enabled, Phase 5 is done too.
`5-final/citation_map.tsv`, `references.bib`, `catalogue.md`, `rigor_table.md` are up to date (rerun `ar-citemap`,
`ar-bib`, `ar-catalogue` if the records changed). If `ar-citemap` changed labels, run `ar-relabel "<dir>"` so the
review's own text uses them too. `5-final/review.md` must then pass `ar-check-review "<dir>"`.
With Zotero: Zotero 7 must be running (`curl -s -m 3 http://localhost:23119/connector/ping`).

### 2. Write `5-final/key_points.json`

The headline numbers and the boxes at the top of each section. Read `review.md` and `counts.json`, then write:

```json
{
  "_subtitle": "One line: the question the review answers",
  "_tiles": [
    {"value": "62", "text": "papers catalogued, 42 of them core"},
    {"value": "48", "text": "claims checked against the papers: 37 supported, 8 partly, 3 contradicted"}
  ],
  "<exact heading of a review section>": ["2 to 4 bullets that restate the section's main findings"]
}
```

- 3 or 4 tiles; each number must appear in the review or in `counts.json` (the script refuses it otherwise).
- Key points restate their section; every number in them must appear in that section's text (refused otherwise).
- Headings must match the review's `##` headings exactly. Leave out References.

### 3. Figures

Skip this step when `edition.figures` is `false` in `review.json`. When `5-final/figures/figures.json` already exists
and `"BIN/ar-figures" check "<dir>"` prints `0 problems`, reuse it and go to step 4 (every
rebuild, for example after `/agentic-review:add-pdfs`, keeps the figures without a new agent). Otherwise (no
`figures.json`, a refused figure after a change to the review, or the user asks for new figures), start ONE
`agentic-review:figure-designer` agent; say so first (`ar-estimate "<dir>" 1 figure-designer`, about 10 minutes
on the first mini review). Its message gives:
- `$REVIEW` = the review folder and `$PLUGIN` = `PLUGIN`, as absolute paths;
- the number of figures to aim for: `edition.figures` when it is a number, else 1 to 2 for `scale: mini` and 3 to 6
  otherwise;
- that the review is final and that it writes only in `5-final/figures/`, plus its own scripts and the example
  gallery in `.scripts/` (where it computes a custom chart's coordinates).

It writes `5-final/figures/figures.json` (and diagram and custom SVGs), checks them with `ar-figures check` and looks at them
with `ar-figures preview --png`. When it reports, run `"BIN/ar-figures" check "<dir>"`
yourself: it must print `0 problems`. If a figure is still refused, send the agent back once with the messages; if it
stays refused, remove that figure from `figures.json` and say so. `5-final/figures/preview/` holds the agent's
previews; the page does not use them.

To remove the figures, delete `5-final/figures/figures.json`.

### 4. Build

`"BIN/ar-edition" "<dir>"` — Zotero mode when `zotero.enabled` is true (it reads the review's
collection and tag through Zotero's local API, read-only, and saves `7-edition/zotero_snapshot.json`), otherwise
`--no-zotero` behaviour. It writes `7-edition/index.html`, the launchers and a `README.md`. Citation labels on the
page always come from `citation_map.tsv` (matched by URL), so rerun `ar-citemap` first if the records changed.

The Zotero snapshot is reused when it exists: pass `--refresh` whenever the library changed since the last build
(always after `/agentic-review:add-pdfs` or new annotations).

Read its summary line (it counts the figures and the figure rows that open a paper). With Zotero, most citations
should open a highlight; many `pdf` or `doi` links mean the
annotation phase missed papers — say so. If it refuses a key point or a tile, fix `key_points.json` and rerun; if it refuses a figure, see step 3.
Exit 1 means a broken `zotero://` link or a missing input: fix it, never hand-edit the HTML.

### 5. Finish

`ar-state "<dir>" phase 7 done`. Tell the user:
- the page: `7-edition/index.html`, and its figures (one line each: what it shows);
- how to open it: double-click `index.html` (Safari asks before each Zotero link), or the launcher
  (`open-in-chrome.command` on macOS, `open-in-browser.sh` / `.bat` elsewhere), which serves the page from
  `http://localhost:<port>` so Chrome can remember "Always allow" for Zotero links; Zotero 7 must be open;
- without Zotero: citations open the DOI or arXiv page;
- PDF readers drop `zotero://` links, so there is no PDF edition.

Rebuild the page (`/agentic-review:run 7`) after every change to the review, for example after
`/agentic-review:add-pdfs` (with `--refresh`).

### Optional settings (`review.json`)

`edition.title`, `edition.port`, `edition.storage_key` (prefix of the page's saved settings and of the BibTeX file
name); `edition.kicker` and `edition.footer` (lines above the title and at the bottom); `edition.glossary`
(`[{"term", "pattern", "definition"}]`, terms explained on hover, added to the families of `taxonomy` and the
criteria of `rigor_rubric`); `edition.unnumbered` and `edition.references_heading`; `edition.limit_words` (words the
Zotero link chooser treats as limitations); `edition.figures` (a number of figures to aim for, or `false` for none).
