#!/usr/bin/env python3
"""agentic-review hooks.

Usage (JSON hook input on stdin):
  ar_hook.py pre-tool        PreToolUse: who-reads-what, write folders, no email in outbound requests,
                             no Zotero deletion, no Zotero add with the tool's own PDF lookup
  ar_hook.py subagent-start  SubagentStart: remember when each of this plugin's agents started
  ar_hook.py subagent-stop   SubagentStop: validate the JSONL files the agent wrote (blocks once at most)
  ar_hook.py session-start   SessionStart: one-paragraph status when the folder holds a review

Every mode exits 0 at once unless the call belongs to a review folder, i.e. a folder holding both review.json and
state.json: the working directory, a file the call touches, or an absolute path a Bash command names is inside one.
Once a call of a session has been tied to a review, the session stays tied to it (a small file per session in the
system's temporary folder), so the guards keep working when Claude was started in a parent folder. Exit 2 blocks the
tool call or the stop; stderr tells Claude why.
"""

import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
PREFIX = "agentic-review:"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_PARAM = re.compile(r"[?&;](?:email|mailto)=", re.I)
ZOTERO_DESTRUCTIVE = re.compile(r"delete|trash|remove|empty|merge|purge")
# Zotero tools that remove through an input (zotero-mcp names): replacing tags or collections drops the user's own.
# An input counts as soon as it is passed (an empty list included: `tags: []` or `collections: []` clears them all);
# only an absent key or null leaves things alone.
ZOTERO_REMOVING_INPUTS = {
    "set_item_collections": ("remove_from",),
    "update_item": ("remove_tags", "tags", "collections", "collection_names", "creators"),
    "update_annotation": ("remove_tags", "tags"),
    "batch_update": ("remove_tags", "remove_keys"),
}
# update_item `fields` that drop data: item_type migrates the item (type-specific fields are lost); creators replaces
# the author list.
ZOTERO_REMOVING_FIELDS = ("item_type", "itemType", "creators")
NETWORK = re.compile(r"https?://|\b(?:curl|wget|httpie|http|requests|urllib|httpx|aiohttp|Invoke-WebRequest)\b", re.I)
FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SEARCH_TOOLS = {"Grep", "Glob"}
# Files the end-of-agent check validates against a schema (ar-validate picks it by name).
RECORD_FILES = (
    "*_records.jsonl",
    "omissions.jsonl",
    "code_records_*.jsonl",
    "repo_audit_*.jsonl",
    "paper_code_*.jsonl",
)
MAX_STOP_BLOCKS = 1


def find_review(*starts):
    for start in starts:
        if not start:
            continue
        try:
            p = Path(start).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        for d in (p, *p.parents):
            if (d / "review.json").is_file() and (d / "state.json").is_file():
                return d
    return None


SESSIONS = Path(tempfile.gettempdir()) / "agentic-review-sessions"
ABS_TOKEN = re.compile(r"^(?:/|~/|[A-Za-z]:[\\/])")


def session_file(session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id or ""))[:120]
    return SESSIONS / safe if safe.strip("._") else None


def bound_review(session_id):
    """The review this session was tied to by an earlier call, if it still exists."""
    f = session_file(session_id)
    if f is None:
        return None
    try:
        d = Path(f.read_text(encoding="utf-8").strip())
    except OSError:
        return None
    return d if (d / "review.json").is_file() and (d / "state.json").is_file() else None


def bind_session(session_id, review):
    f = session_file(session_id)
    if f is None:
        return
    try:
        if f.is_file() and f.read_text(encoding="utf-8").strip() == str(review):
            return
        SESSIONS.mkdir(parents=True, exist_ok=True)
        f.write_text(str(review), encoding="utf-8")
    except OSError:
        pass


def command_paths(cmd, limit=40):
    """Absolute paths a shell command names (quoted paths with spaces included)."""
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        tokens = cmd.split()
    out = []
    for t in tokens:
        for part in re.split(r"[=:,;]", t) if not ABS_TOKEN.match(t) else [t]:
            if ABS_TOKEN.match(part):
                out.append(part)
        if len(out) >= limit:
            break
    return out


def relative_paths(cmd, cwd, limit=40):
    """Relative tokens of a shell command resolved against the working directory ('ar-state rev show' run from the
    folder that holds 'rev'). Only folders that exist directly below cwd are kept, so this stays cheap."""
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        tokens = cmd.split()
    out = []
    for t in tokens[:200]:
        if not t or t.startswith("-") or ABS_TOKEN.match(t) or len(t) > 300:
            continue
        head = t.split("/", 1)[0]
        if head in (".", "..") or not head:
            continue
        p = Path(cwd) / head
        try:
            if (p / "review.json").is_file():
                out.append(str(p))
        except OSError:
            continue
        if len(out) >= limit:
            break
    return out


def review_for(data, ti=None):
    """The review a hook call belongs to: from the working directory, the paths the call names, or the review its
    session was tied to earlier. Ties the session to the review it finds."""
    ti = ti if ti is not None else {}
    starts = [data.get("cwd") or os.getcwd(), ti.get("file_path"), ti.get("notebook_path"), ti.get("path")]
    if data.get("tool_name") == "Bash":
        cmd = str(ti.get("command") or "")
        starts += command_paths(cmd)
        starts += relative_paths(cmd, data.get("cwd") or os.getcwd())
    review = find_review(*[s for s in starts if isinstance(s, str)])
    sid = data.get("session_id")
    if review is not None:
        if sid:
            bind_session(sid, review)
        return review
    return bound_review(sid) if sid else None


def role_of(agent_type, table):
    if not agent_type:
        return None
    if agent_type.startswith(PREFIX):
        name = agent_type[len(PREFIX) :]
        return name if name in table else None
    return agent_type if agent_type in table else None


def load_table(review):
    for path in (review / ".agentic-review" / "access.json", PLUGIN / "hooks" / "access.json"):
        try:
            table = json.loads(path.read_text(encoding="utf-8"))
            return {k: v for k, v in table.items() if not k.startswith("_")}
        except (OSError, ValueError):
            continue
    return {}


def meta_dir(review):
    d = review / ".agentic-review"
    with contextlib.suppress(OSError):
        d.mkdir(exist_ok=True)
    return d


def log(review, **entry):
    entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        with open(meta_dir(review) / "hooks.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def log_first_sighting(review, data):
    """Record once per agent_type which keys the hook input carries (settles its exact shape on the first run)."""
    agent_type = data.get("agent_type") or "(main session)"
    seen_path = meta_dir(review) / "seen_agent_types.json"
    try:
        seen = json.loads(seen_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    if agent_type in seen:
        return
    seen[agent_type] = {"event": data.get("hook_event_name"), "keys": sorted(data.keys())}
    with contextlib.suppress(OSError):
        seen_path.write_text(json.dumps(seen, indent=1), encoding="utf-8")


def resolve(path, cwd):
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(cwd or ".") / p
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return p


def inside(child, parent):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def block(review, reason, **entry):
    log(review, decision="deny", reason=reason, **entry)
    sys.stderr.write(reason + "\n")
    sys.exit(2)


# ---------------------------------------------------------------- PreToolUse


def check_outbound(review, tool, ti, entry):
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if NETWORK.search(cmd) and (EMAIL.search(cmd) or EMAIL_PARAM.search(cmd)):
            block(
                review,
                "agentic-review: blocked a network command that carries an email address or an "
                "email/mailto parameter. The protocol forbids sending personal data to any website or API. "
                "Use a source that works without it (arXiv, CrossRef, OpenAlex open-access locations, "
                "PubMed Central, publisher pages).",
                **entry,
            )
    elif tool == "WebFetch":
        url = ti.get("url") or ""
        if EMAIL.search(url) or EMAIL_PARAM.search(url):
            block(
                review,
                "agentic-review: blocked a fetch whose URL carries an email address. The protocol forbids "
                "sending personal data to any website or API.",
                **entry,
            )


def check_zotero(review, tool, ti, entry):
    """The review only adds to the user's Zotero library: no tool that deletes, trashes, removes or merges, and
    zotero-mcp's add tool only with its own PDF lookup off (that lookup queries Unpaywall and other services)."""
    if not tool.startswith("mcp__") or "zotero" not in tool.lower():
        return
    name = tool.rsplit("__", 1)[-1].lower()
    removing = [
        k
        for suffix, keys in ZOTERO_REMOVING_INPUTS.items()
        if name.endswith(suffix)
        for k in keys
        if k in ti and ti[k] is not None
    ]
    if name.endswith("update_item"):
        fields = ti.get("fields")
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except ValueError:
                fields = {"_unparsed": fields} if any(f in fields for f in ZOTERO_REMOVING_FIELDS) else {}
                if fields:
                    removing.append("fields it cannot read")
        if isinstance(fields, dict):
            removing += [f"fields.{f}" for f in ZOTERO_REMOVING_FIELDS if fields.get(f) is not None]
    if name.endswith("manage_note") and str(ti.get("action", "")).lower() == "delete":
        removing.append('action "delete"')
    if ZOTERO_DESTRUCTIVE.search(name) or removing:
        how = f" with {', '.join(removing)}" if removing else ""
        block(
            review,
            f"agentic-review: {tool}{how} is refused. A review never deletes, trashes, removes or merges "
            "anything in the user's Zotero library, nor replaces an item's tags or collections (add them "
            "instead); if something is wrong there, say so in your report and leave it to the user.",
            **entry,
        )
    if name == "zotero_add_item" and str(ti.get("attach_mode", "")).lower() != "none":  # zotero-mcp only
        block(
            review,
            f'agentic-review: call {tool} with "attach_mode": "none". Its own PDF lookup queries '
            "Unpaywall and other services the protocol does not allow. Attach a PDF yourself from arXiv, "
            "PubMed Central or an open-access publisher page with the attach tool.",
            **entry,
        )


def check_access(review, role, rules, tool, ti, cwd, entry):
    deny = [(d, (review / d).resolve()) for d in rules.get("deny_read", [])]
    write = [(review / w).resolve() for w in rules.get("write", [])]

    if tool in FILE_TOOLS:
        raw = ti.get("file_path") or ti.get("notebook_path")
        if raw:
            target = resolve(raw, cwd)
            verb = "write to" if tool in WRITE_TOOLS else "read"
            for name, d in deny:
                if inside(target, d):
                    block(
                        review,
                        f"agentic-review: the {role} agent may not {verb} {name} (independence rule, "
                        f"CONTRACT §6). Work from the inputs your brief lists.",
                        **entry,
                    )
            if tool in WRITE_TOOLS and inside(target, review) and not any(inside(target, w) for w in write):
                allowed = ", ".join(rules.get("write", [])) or "nothing"
                block(
                    review,
                    f"agentic-review: the {role} agent may write only in: {allowed} "
                    f"(not {target.relative_to(review)}).",
                    **entry,
                )

    elif tool in SEARCH_TOOLS:
        base = resolve(ti.get("path") or cwd or review, cwd)
        text = " ".join(str(ti.get(k) or "") for k in ("pattern", "glob", "path"))
        for name, d in deny:
            if inside(base, d) or name in text:
                block(
                    review,
                    f"agentic-review: the {role} agent may not search {name} (independence rule).",
                    **entry,
                )
            if inside(d, base) and base != d and not Path(name).suffix:
                block(
                    review,
                    f"agentic-review: this search covers {name}, which the {role} agent may not read. "
                    f"Search a narrower folder (for example the one your brief names).",
                    **entry,
                )

    elif tool == "Bash":
        cmd = ti.get("command") or ""
        for name, _ in deny:
            if name in cmd:
                block(
                    review,
                    f"agentic-review: the {role} agent may not access {name} (independence rule, "
                    f"CONTRACT §6). Work from the inputs your brief lists.",
                    **entry,
                )


def pre_tool(data):
    cwd = data.get("cwd") or os.getcwd()
    ti = data.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    tool = data.get("tool_name") or ""
    review = review_for(data, ti)
    if review is None:
        return 0
    log_first_sighting(review, data)
    entry = {"event": "pre-tool", "tool": tool, "agent_type": data.get("agent_type"), "agent_id": data.get("agent_id")}
    check_outbound(review, tool, ti, entry)
    check_zotero(review, tool, ti, entry)
    table = load_table(review)
    role = role_of(data.get("agent_type"), table)
    if role:
        check_access(review, role, table[role], tool, ti, cwd, entry)
        files = written_files(review, table[role], tool, ti, cwd)
        if files:
            record_written(review, data.get("agent_id") or role, role, files)
    return 0


# ------------------------------------------------------------ Subagent start/stop


def agents_file(review):
    return meta_dir(review) / "agents.json"


def load_agents(review):
    try:
        return json.loads(agents_file(review).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_agents(review, agents):
    try:
        tmp = agents_file(review).with_suffix(".tmp")
        tmp.write_text(json.dumps(agents, indent=1), encoding="utf-8")
        os.replace(tmp, agents_file(review))
    except OSError:
        pass


def update_agents(review, change):
    """Read-modify-write agents.json under a lock: parallel agents fire hooks at the same time."""
    lock_path = meta_dir(review) / "agents.lock"
    try:
        import fcntl
    except ImportError:  # Windows: no lock
        fcntl = None
    try:
        with open(lock_path, "a") as lock:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_EX)
            agents = load_agents(review)
            result = change(agents)
            save_agents(review, agents)
            return result
    except OSError:
        return None


JSONL_TOKEN = re.compile(r"""[^\s'"<>|;&]+\.jsonl\b""")


def written_files(review, rules, tool, ti, cwd):
    """JSONL files inside the agent's write folders that this call writes (Write/Edit) or names (Bash)."""
    write = [(review / w).resolve() for w in rules.get("write", []) if not w.startswith(".")]
    if tool in WRITE_TOOLS:
        raw = [ti.get("file_path") or ti.get("notebook_path") or ""]
    elif tool == "Bash":
        raw = JSONL_TOKEN.findall(ti.get("command") or "")
    else:
        return []
    out = []
    for r in raw:
        if not r.endswith(".jsonl"):
            continue
        p = resolve(r, cwd)
        if any(inside(p, w) for w in write):
            out.append(str(p.relative_to(review)))
    return out


def record_written(review, agent_id, role, files):
    def change(agents):
        info = agents.setdefault(agent_id, {"role": role, "started": time.time(), "blocks": 0})
        known = set(info.get("files", []))
        info["files"] = sorted(known | set(files))

    update_agents(review, change)


def subagent_start(data):
    review = review_for(data)
    if review is None:
        return 0
    log_first_sighting(review, data)
    role = role_of(data.get("agent_type"), load_table(review))
    if not role:
        return 0
    key = data.get("agent_id") or role
    update_agents(
        review, lambda agents: agents.__setitem__(key, {"role": role, "started": time.time(), "blocks": 0, "files": []})
    )
    log(review, event="subagent-start", agent_type=data.get("agent_type"), agent_id=data.get("agent_id"))
    return 0


def jsonl_problems(path):
    problems = []
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as e:
                        problems.append(f"{path.name}:{n}: not valid JSON ({e.msg})")
    except OSError as e:
        problems.append(f"{path.name}: unreadable ({e})")
    return problems


def subagent_stop(data):
    review = review_for(data)
    if review is None:
        return 0
    table = load_table(review)
    role = role_of(data.get("agent_type"), table)
    if not role:
        return 0
    agents = load_agents(review)
    key = data.get("agent_id") or role
    info = agents.get(key, {"role": role, "started": 0, "blocks": 0})
    entry = {"event": "subagent-stop", "agent_type": data.get("agent_type"), "agent_id": data.get("agent_id")}
    if info.get("blocks", 0) >= MAX_STOP_BLOCKS:
        log(review, decision="allow", reason="block cap reached", **entry)
        return 0

    # The files this agent wrote: those its tool calls named (recorded by pre-tool), plus JSONL files changed in
    # its write folders since it started that no other agent named (scripts can write without naming a path).
    started = info.get("started", 0)
    mine = {review / f for f in info.get("files", [])}
    others = {review / f for k, a in agents.items() if k != key for f in a.get("files", [])}
    changed = set()
    for w in table[role].get("write", []):
        if w.startswith("."):
            continue
        folder = review / w
        if folder.is_dir():
            changed |= {p for p in folder.rglob("*.jsonl") if p.stat().st_mtime >= started}
    changed = sorted(p for p in (mine | (changed - others)) if p.is_file())
    if not changed:
        return 0

    problems = []
    for p in changed:
        problems += jsonl_problems(p)
    records = [p for p in changed if any(p.match(g) for g in RECORD_FILES)]
    validator = PLUGIN / "bin" / "ar-validate"
    if records and not problems and validator.is_file():
        try:
            out = subprocess.run(
                [sys.executable, str(validator), str(review), *map(str, records)],
                capture_output=True,
                text=True,
                timeout=50,
            )
            if out.returncode == 1:
                problems.append(out.stdout.strip()[-1500:] or "ar-validate reported errors")
        except (OSError, subprocess.SubprocessError):
            pass

    if not problems:
        log(review, decision="allow", files=[str(p.relative_to(review)) for p in changed], **entry)
        return 0

    def count_block(agents):
        a = agents.setdefault(key, info)
        a["blocks"] = a.get("blocks", 0) + 1

    update_agents(review, count_block)
    block(
        review,
        "agentic-review: some JSONL files written during your run do not validate. Fix the files you "
        "wrote (if a listed file belongs to another agent, leave it and say so in your final message), "
        "then finish:\n" + "\n".join(problems[:30]),
        **entry,
    )


# ---------------------------------------------------------------- SessionStart


def session_start(data):
    review = find_review(data.get("cwd") or os.getcwd())
    if review is None:
        return 0
    status = ""
    state_bin = PLUGIN / "bin" / "ar-state"
    if state_bin.is_file():
        try:
            out = subprocess.run(
                [sys.executable, str(state_bin), str(review), "show"], capture_output=True, text=True, timeout=8
            )
            status = out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            status = ""
    print(
        "This folder holds an agentic-review literature review (review.json, state.json). "
        "Continue it with /agentic-review:run; /agentic-review:status shows where it stands."
    )
    if status:
        print("\n".join(status.splitlines()[:12]))
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    handler = {
        "pre-tool": pre_tool,
        "subagent-start": subagent_start,
        "subagent-stop": subagent_stop,
        "session-start": session_start,
    }.get(mode)
    return handler(data) if handler else 0


if __name__ == "__main__":
    sys.exit(main())
