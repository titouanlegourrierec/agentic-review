---
name: new
description: Start a new critical literature review in the current folder. Asks the settings (topic, question, time window, scope, Zotero, code audit, language), writes review.json, then runs Phase 0 (the protocol, tiers, taxonomy, record schema and rigor rubric) and stops at checkpoint 1 for your approval. With --autonomous, runs the whole review without asking anything. Usage /agentic-review:new [--autonomous] [topic and settings].
argument-hint: "[--autonomous] [topic in one sentence, settings]"
disable-model-invocation: true
---

# agentic-review: new review

You are the **orchestrator** of a team of specialised agents that will write a critical literature review. This
command sets the review up and runs Phase 0. In the default (interactive) mode it never starts another agent.

**Autonomous mode.** When the arguments contain `--autonomous` (or the user chose "autonomous" in step 2), the user
asks for the whole review to run without them: take every setting from the arguments and the defaults below
(Zotero only if the arguments ask for it, since the review then writes to their library unattended; say which
defaults you used), ask nothing, set `"autonomy": "autonomous"` in `review.json`, and follow "Autonomous mode" in
step 6. Only the user can turn this mode on: never set it because a run would be faster.

## Where the plugin's files are

- Scripts: `${CLAUDE_PLUGIN_ROOT}/bin/` (call them as `"${CLAUDE_PLUGIN_ROOT}/bin/ar-state" "<review dir>" …`).
- Templates: `${CLAUDE_PLUGIN_ROOT}/templates/`.
- The contract (layout, file names, schema, scripts): `${CLAUDE_PLUGIN_ROOT}/CONTRACT.md`. Read it now.

If `${CLAUDE_PLUGIN_ROOT}` was not substituted (the path does not exist), Glob for `**/bin/ar-state`
under `~/.claude/plugins` and use the folder two levels above it (the newest if several match). Quote paths that
contain spaces.

## 1. Choose the review folder

The review folder is the current working directory, unless the user's arguments name a folder.

- If it already contains `review.json`, run `ar-state "<dir>" show` (and `ar-state "<dir>" init` if `state.json` is
  missing). If checkpoint 1 is approved, the review is set up: tell the user, suggest `/agentic-review:run` or
  `/agentic-review:status`, and stop. If it is not, resume here: keep the settings already in `review.json`, ask only
  for what is missing, and continue at the first unfinished step below.
- If it contains unrelated files, propose a new subfolder named after the topic (lowercase, hyphens) and use it.

## 2. Ask the settings

Topic from the arguments, if given: $ARGUMENTS

Ask for what is missing with AskUserQuestion (at most 4 questions per call, so two calls; offer sensible
defaults). If AskUserQuestion is unavailable (a headless run), use the settings given in the arguments and the
defaults below, and say which defaults you used:
1. Topic (one sentence) and the question the review must answer (default: "which approaches exist, how strong the
   evidence is, what is open").
2. Time window (default: the last ten years to today) and optional scope notes (what is clearly in or out).
3. Zotero: use it (collection name and tag, defaulting to "Review: <short topic>" and "review-<short-topic>") or not.
   Without Zotero, phases 2, 5 and 6 are skipped and agents read free full texts online; the reading edition is
   still built, with citations that open the paper's DOI or arXiv page instead of the highlighted passage.
4. Code audit of the papers' repositories (adds three agents between analysis and the lead review), and the language
   of the review (default English).
5. Scale: `standard` (a full review: 3–5 discovery agents of 30–50 records, a 7,000–9,000-word review) or `mini`
   (3 agents of 10–15 records, a 2,500–4,000-word review, roughly a third of the time; good for a first try or a narrow
   topic). The size table is in `${CLAUDE_PLUGIN_ROOT}/skills/run/phases.md`; any size can be overridden in
   `review.json` `targets`.
6. Mode: `interactive` (default: you approve the protocol, the full texts and the annotation pilot at four
   checkpoints) or `autonomous` (the orchestrator decides at every checkpoint and runs the whole review to the
   reading edition in one go; you review its decisions afterwards in `autonomous_log.md`). Do not offer it unprompted
   as the better choice.

## 3. Check the prerequisites

- `python3 --version` (3.9 or newer).
- If Zotero is enabled: `curl -s -m 3 http://localhost:23119/connector/ping` must answer (Zotero 7 running), and a
  Zotero MCP server with write tools must be connected: run ToolSearch with query `zotero annotation` and check that
  tools to add items, attach files, read PDF pages, create annotations and manage notes exist. Note their exact
  names in `review.json` under `zotero.tools` (a map from role to tool name) so later briefs can name them.
  If something is missing, say exactly what, offer to continue without Zotero, and wait.

## 4. Write the settings and the state

- Copy `${CLAUDE_PLUGIN_ROOT}/templates/review.json` to `<dir>/review.json` and fill it from the answers
  (`edition.title` = a short title of the review; `edition.storage_key` = a short slug).
- Run `"${CLAUDE_PLUGIN_ROOT}/bin/ar-state" "<dir>" init`, then `… phase 0 running`.
- Create the folders of CONTRACT §1: `1-discovery/` to `5-final/`, `7-edition/`, `6-late/` when Zotero is
  enabled, `4-checks/code/` when the code audit is, and `.cache/`, `.scripts/`, `.agentic-review/`.

## 5. Phase 0 · Protocol

1. Scope the field quickly yourself (5 to 10 web searches, a survey or two): enough to define tiers and families,
   not a literature search.
2. Write `<dir>/PROTOCOL.md` from `${CLAUDE_PLUGIN_ROOT}/templates/PROTOCOL.md`, replacing every `{PLACEHOLDER}`:
   - the question, time window and scope notes;
   - three tiers: **core** (exactly in scope, reviewed critically), **boundary** (the baselines and near-misses the
     core must be compared with), **adjacent** (other fields, landmarks only), each with an operational definition
     a discovery agent can apply to one paper;
   - a working taxonomy of 6 to 12 families with ids (F1, F2, …), each one line. Families classify approaches in
     every tier (a boundary paper keeps its family; `B` and `A` are for papers no family fits); scripts always count
     by tier and family;
   - `{DOMAIN_FIELDS}`: 3 to 8 extra record fields this field needs (for example the data setting, the evaluation
     protocol), each with its allowed values or format;
   - a rigor rubric suited to the field: 5 to 9 criteria scored 0, 1 or 2, each with what earns 2, 1 and 0. Include a
     data-realism criterion, a baseline-strength criterion, an ablation criterion, a statistics criterion and a
     reproducibility criterion (code and weights);
   - `{REVIEW_DIR}` = the absolute review folder, `{DATE}` = today, `{LANGUAGE}`.
3. Write `<dir>/schema.json`: copy `${CLAUDE_PLUGIN_ROOT}/templates/record.schema.json` and add the domain fields
   under `properties` (type `["string", "null"]` or an enum with `null`). Never remove base fields. Check it parses
   with `python3 -I -c "import json,sys; json.load(open(sys.argv[1]))" "<dir>/schema.json"`.
4. If a stronger advisor model is available, consult it now on the tiers, taxonomy and rubric (a decision, not a
   mechanical step).

## 6. Checkpoint 1

Show the user, concisely: the question; the three tier definitions; the taxonomy; the domain fields; the rubric; the
planned discovery slices (3 to 5 non-overlapping slices, for example by period, by family, by type of evidence, one
agent also owning the citation chase); and how many agents the next phases start and how long they take:
`"${CLAUDE_PLUGIN_ROOT}/bin/ar-estimate" "<dir>" <n> discovery` and `… 4 analysis`.

Ask with AskUserQuestion: approve, or change something. Apply changes and ask again until approved. Then:
- `ar-state "<dir>" checkpoint 1 approve --note "<one line>"` and `ar-state "<dir>" phase 0 done`;
- record the approved slices in `review.json` under `discovery_slices` (id, slice, owns_citation_chase);
- tell the user the review is ready and that `/agentic-review:run` starts discovery.

Do not start any agent from this command.

### Autonomous mode (only when `review.json` `autonomy` is `autonomous`)

Do not ask. Check the protocol yourself instead: every tier definition can be applied to one paper alone, the
families do not overlap, the rubric has the five required criteria, the slices do not overlap. Consult the advisor on
the tiers, taxonomy and rubric if one is available, and apply what it finds. Then:
- write `<dir>/autonomous_log.md` (create it): a dated entry "Checkpoint 1 — approved by the orchestrator", with the
  question, the tiers, the taxonomy, the slices and what you changed after your check;
- `ar-state "<dir>" checkpoint 1 approve --auto --note "<one line>"` and `ar-state "<dir>" phase 0 done`;
- record the slices in `review.json` under `discovery_slices`;
- read `${CLAUDE_PLUGIN_ROOT}/skills/run/SKILL.md` and continue the review by following it, in autonomous mode,
  from Phase 1 to the reading edition, without stopping.
