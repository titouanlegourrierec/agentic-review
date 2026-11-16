---
name: status
description: Show where the literature review in the current folder stands - phase, checkpoints waiting for you, agents running or done, key counts and the next step. Read-only. Usage /agentic-review:status.
---

# agentic-review: status

Read-only: change nothing, start no agent.

1. The review folder is the current directory, or the folder named in the arguments ($ARGUMENTS). If it has no
   `review.json`, say there is no review here and that `/agentic-review:new` starts one. Stop.
2. Run `"${CLAUDE_PLUGIN_ROOT}/bin/ar-state" "<dir>" show` and `… next`. (If `${CLAUDE_PLUGIN_ROOT}` was not
   substituted, Glob for `**/bin/ar-state` under `~/.claude/plugins`.)
3. If `5-final/counts.json` exists, add the tier counts. If `4-checks/claims_check.jsonl` exists, count verdicts with
   a one-line `python3 -I` script.
4. Answer in a few lines: the phase, what waits for the user (a checkpoint and what it needs), and the next command:
   `/agentic-review:new` while Phase 0 is unfinished or checkpoint 1 is not approved; `/agentic-review:add-pdfs` for
   Phase 6; `/agentic-review:run 7` for Phase 7; `/agentic-review:run` otherwise.
