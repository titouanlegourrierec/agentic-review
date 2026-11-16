"""Tests for hooks/ar_hook.py, fed synthetic hook input on stdin. Standard library only.

Run: python3 -m unittest discover -s plugins/agentic-review/tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "ar_hook.py"


def run(mode, data):
    p = subprocess.run(
        [sys.executable, str(HOOK), mode], input=json.dumps(data), capture_output=True, text=True, timeout=30
    )
    return p.returncode, p.stdout, p.stderr


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.review = Path(self.tmp.name) / "my review"
        for d in ("1-discovery", "2-merged", "3-analysis", "4-checks", "5-final", ".cache", ".scripts"):
            (self.review / d).mkdir(parents=True)
        (self.review / "review.json").write_text("{}")
        (self.review / "state.json").write_text("{}")
        (self.review / "3-analysis" / "synthesis.md").write_text("draft")
        self.outside = Path(self.tmp.name) / "elsewhere"
        self.outside.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def pre(self, tool, tool_input, agent_type=None, cwd=None):
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
            "cwd": str(cwd or self.review),
        }
        if agent_type:
            data["agent_type"] = agent_type
            data["agent_id"] = "a1"
        return run("pre-tool", data)

    # --- scope: outside a review nothing is ever blocked
    def test_outside_review_is_silent(self):
        code, _out, _err = self.pre(
            "Bash", {"command": "curl 'https://api.unpaywall.org/v2/x?email=a@b.org'"}, cwd=self.outside
        )
        self.assertEqual(code, 0)
        self.assertFalse((self.outside / ".agentic-review").exists())

    # --- who reads what
    def test_rigor_checker_cannot_read_analysis(self):
        code, _, err = self.pre(
            "Read",
            {"file_path": str(self.review / "3-analysis" / "synthesis.md")},
            "agentic-review:rigor-checker",
        )
        self.assertEqual(code, 2)
        self.assertIn("3-analysis", err)

    def test_rigor_checker_can_read_corpus(self):
        code, _, _ = self.pre(
            "Read",
            {"file_path": str(self.review / "2-merged" / "corpus.jsonl")},
            "agentic-review:rigor-checker",
        )
        self.assertEqual(code, 0)

    def test_relative_path_and_bash_are_checked(self):
        code, _, _ = self.pre("Read", {"file_path": "3-analysis/synthesis.md"}, "agentic-review:omissions-checker")
        self.assertEqual(code, 2)
        code, _, _ = self.pre("Bash", {"command": "cat '3-analysis/synthesis.md'"}, "agentic-review:rigor-checker")
        self.assertEqual(code, 2)

    def test_search_covering_a_denied_folder_is_blocked(self):
        code, _, _ = self.pre("Grep", {"pattern": "PSNR", "path": str(self.review)}, "agentic-review:rigor-checker")
        self.assertEqual(code, 2)
        code, _, _ = self.pre(
            "Grep",
            {"pattern": "PSNR", "path": str(self.review / "2-merged")},
            "agentic-review:rigor-checker",
        )
        self.assertEqual(code, 0)

    def test_comparison_may_search_its_own_folder_but_not_read_synthesis(self):
        code, _, _ = self.pre(
            "Grep", {"pattern": "x", "path": str(self.review / "3-analysis")}, "agentic-review:comparison"
        )
        self.assertEqual(code, 0)
        code, _, _ = self.pre(
            "Read",
            {"file_path": str(self.review / "3-analysis" / "synthesis.md")},
            "agentic-review:comparison",
        )
        self.assertEqual(code, 2)

    def test_write_outside_own_folder_is_blocked(self):
        code, _, err = self.pre(
            "Write",
            {"file_path": str(self.review / "2-merged" / "corpus.jsonl"), "content": "x"},
            "agentic-review:synthesis",
        )
        self.assertEqual(code, 2)
        self.assertIn("may write only in", err)
        code, _, err = self.pre(
            "Write",
            {"file_path": str(self.review / "5-final" / "review.md"), "content": "x"},
            "agentic-review:synthesis",
        )
        self.assertEqual(code, 2)
        self.assertIn("may not write to 5-final", err)
        code, _, _ = self.pre(
            "Write",
            {"file_path": str(self.review / "review.json"), "content": "{}"},
            "agentic-review:lead-reviewer",
        )
        self.assertEqual(code, 2)
        code, _, _ = self.pre(
            "Write",
            {"file_path": str(self.review / "3-analysis" / "s.md"), "content": "x"},
            "agentic-review:synthesis",
        )
        self.assertEqual(code, 0)

    def test_main_session_and_other_agents_are_not_restricted(self):
        target = {"file_path": str(self.review / "3-analysis" / "synthesis.md")}
        self.assertEqual(self.pre("Read", target)[0], 0)
        self.assertEqual(self.pre("Read", target, "general-purpose")[0], 0)
        self.assertEqual(self.pre("Read", target, "other-plugin:rigor-checker")[0], 0)

    # --- outbound personal data
    def test_email_in_network_command_is_blocked_for_everyone(self):
        cmd = 'curl -s "https://api.unpaywall.org/v2/10.1/x?email=someone@example.org"'
        self.assertEqual(self.pre("Bash", {"command": cmd})[0], 2)
        self.assertEqual(self.pre("Bash", {"command": cmd}, "agentic-review:annotator")[0], 2)
        self.assertEqual(self.pre("WebFetch", {"url": "https://x.org/api?mailto=a@b.org", "prompt": "p"})[0], 2)

    # --- the user's Zotero library
    def test_zotero_deletions_are_refused_for_everyone(self):
        for tool in (
            "mcp__zotero__zotero_delete_item",
            "mcp__zotero__zotero_delete_annotation",
            "mcp__zotero__zotero_delete_collection",
            "mcp__zotero__zotero_remove_from_collection",
            "mcp__my-zotero__merge_duplicates",
            "mcp__zotero__zotero_empty_trash",
        ):
            with self.subTest(tool=tool):
                self.assertEqual(self.pre(tool, {"item_key": "ABCD1234"})[0], 2)
                self.assertEqual(self.pre(tool, {"item_key": "ABCD1234"}, "agentic-review:annotator")[0], 2)
        _code, _, err = self.pre("mcp__zotero__zotero_delete_annotation", {"key": "X"}, "agentic-review:annotator")
        self.assertIn("never deletes", err)

    def test_zotero_removal_through_inputs_is_refused(self):
        z = "mcp__zotero__zotero_"
        refused = [
            ("manage_note", {"action": "delete", "item_key": "A"}),
            ("set_item_collections", {"item_keys": "A", "remove_from": ["C1"]}),
            ("update_item", {"item_key": "A", "tags": ["x"]}),
            ("update_item", {"item_key": "A", "collections": ["C1"]}),
            ("update_item", {"item_key": "A", "remove_tags": ["x"]}),
            ("update_annotation", {"annotation_key": "A", "tags": ["x"]}),
            ("batch_update", {"query": "x", "remove_tags": ["y"]}),
            # empty replacements clear everything: they must be refused too
            ("update_item", {"item_key": "A", "tags": []}),
            ("update_item", {"item_key": "A", "collections": []}),
            ("update_item", {"item_key": "A", "collection_names": []}),
            ("update_annotation", {"annotation_key": "A", "tags": []}),
            ("update_item", {"item_key": "A", "creators": []}),
            ("update_item", {"item_key": "A", "fields": {"item_type": "preprint"}}),
            ("update_item", {"item_key": "A", "fields": '{"item_type": "preprint"}'}),
        ]
        allowed = [
            ("update_item", {"item_key": "A", "fields": {"doi": "10.1/x"}, "tags": None}),
            ("manage_note", {"action": "create", "item_key": "A", "note_text": "n"}),
            ("manage_note", {"action": "update", "item_key": "A", "note_text": "n"}),
            ("set_item_collections", {"item_keys": "A", "add_to": ["C1"]}),
            ("update_item", {"item_key": "A", "fields": {"title": "T"}, "add_tags": ["x"]}),
            ("update_annotation", {"annotation_key": "A", "comment": "c", "add_tags": ["x"]}),
            ("batch_update", {"item_keys": ["A"], "add_tags": ["y"]}),
        ]
        for name, ti in refused:
            with self.subTest(refused=name, ti=ti):
                code, _, err = self.pre(z + name, ti, "agentic-review:annotator")
                self.assertEqual(code, 2)
                self.assertIn("is refused", err)
        for name, ti in allowed:
            with self.subTest(allowed=name, ti=ti):
                self.assertEqual(self.pre(z + name, ti, "agentic-review:annotator")[0], 0)

    def test_guards_follow_the_session_when_claude_runs_in_a_parent_folder(self):
        parent = self.review.parent
        sid = "test-session-" + str(os.getpid()) + "-" + str(time.time())

        def pre(tool, ti, agent_type=None):
            data = {
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": ti,
                "cwd": str(parent),
                "session_id": sid,
            }
            if agent_type:
                data.update(agent_type=agent_type, agent_id="a9")
            return run("pre-tool", data)[0]

        try:
            # Before the session names the review, nothing ties it to one.
            self.assertEqual(pre("mcp__zotero__zotero_delete_item", {"item_key": "A"}), 0)
            # A command that names the review folder (quoted, with a space) ties the session to it ...
            self.assertEqual(pre("Bash", {"command": f'ar-state "{self.review}" show'}), 0)
            # ... and from then on every guard applies, for the main session and its agents.
            self.assertEqual(pre("mcp__zotero__zotero_delete_item", {"item_key": "A"}), 2)
            self.assertEqual(pre("WebFetch", {"url": "https://api.unpaywall.org/v2/x?email=a@b.org"}), 2)
            self.assertEqual(
                pre(
                    "Read",
                    {"file_path": str(self.review / "3-analysis" / "synthesis.md")},
                    "agentic-review:rigor-checker",
                ),
                2,
            )
            self.assertEqual(
                pre(
                    "Read",
                    {"file_path": str(self.review / "2-merged" / "x.jsonl")},
                    "agentic-review:rigor-checker",
                ),
                0,
            )
            # Another session is not affected.
            other = {
                "hook_event_name": "PreToolUse",
                "tool_name": "mcp__zotero__zotero_delete_item",
                "tool_input": {"item_key": "A"},
                "cwd": str(parent),
                "session_id": sid + "-other",
            }
            self.assertEqual(run("pre-tool", other)[0], 0)
        finally:
            f = Path(tempfile.gettempdir()) / "agentic-review-sessions" / sid
            if f.exists():
                f.unlink()

    def test_relative_review_folder_in_a_command_ties_the_session(self):
        parent = self.review.parent
        sid = "test-rel-" + str(os.getpid()) + "-" + str(time.time())
        base = {"hook_event_name": "PreToolUse", "cwd": str(parent), "session_id": sid}
        try:
            run("pre-tool", dict(base, tool_name="Bash", tool_input={"command": f'ar-state "{self.review.name}" show'}))
            code = run(
                "pre-tool", dict(base, tool_name="mcp__zotero__zotero_delete_item", tool_input={"item_key": "A"})
            )[0]
            self.assertEqual(code, 2)
        finally:
            f = Path(tempfile.gettempdir()) / "agentic-review-sessions" / sid
            if f.exists():
                f.unlink()

    def test_malformed_input_does_not_crash(self):
        for data in ([1, 2], {"tool_name": "Bash", "tool_input": "ls", "cwd": str(self.review)}):
            p = subprocess.run(
                [sys.executable, str(HOOK), "pre-tool"],
                input=json.dumps(data),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_zotero_add_needs_its_pdf_lookup_off(self):
        add = "mcp__zotero__zotero_add_item"
        code, _, err = self.pre(add, {"source": "10.1000/a", "source_type": "doi"}, "agentic-review:annotator")
        self.assertEqual(code, 2)
        self.assertIn('"attach_mode": "none"', err)
        self.assertEqual(self.pre(add, {"source": "10.1000/a", "attach_mode": "auto"})[0], 2)
        self.assertEqual(self.pre(add, {"source": "10.1000/a", "attach_mode": "none"})[0], 0)
        for tool in (
            "mcp__zotero__zotero_create_annotation",
            "mcp__zotero__zotero_attach_file",
            "mcp__zotero__zotero_search_items",
            "mcp__other__delete_file",
        ):
            with self.subTest(tool=tool):
                self.assertEqual(self.pre(tool, {"x": 1}, "agentic-review:annotator")[0], 0)

    def test_ordinary_commands_pass(self):
        self.assertEqual(self.pre("Bash", {"command": "git commit -m 'x' --author 'A <a@b.org>'"})[0], 0)
        self.assertEqual(
            self.pre("Bash", {"command": "curl -sL 'https://export.arxiv.org/api/query?id_list=2302.09244'"})[0], 0
        )
        self.assertEqual(self.pre("Bash", {"command": "npm view react@18.3.1"})[0], 0)

    # --- subagent stop validation
    def test_subagent_stop_blocks_once_on_invalid_jsonl(self):
        start = {
            "hook_event_name": "SubagentStart",
            "agent_type": "agentic-review:discovery",
            "agent_id": "d1",
            "cwd": str(self.review),
        }
        self.assertEqual(run("subagent-start", start)[0], 0)
        time.sleep(0.05)
        (self.review / "1-discovery" / "notes.jsonl").write_text('{"ok": 1}\n{broken\n')
        stop = dict(start, hook_event_name="SubagentStop")
        code, _, err = run("subagent-stop", stop)
        self.assertEqual(code, 2)
        self.assertIn("notes.jsonl:2", err)
        self.assertEqual(run("subagent-stop", stop)[0], 0, "second stop must not loop")

    def test_subagent_stop_ignores_untouched_files(self):
        (self.review / "1-discovery" / "old.jsonl").write_text("{broken\n")
        past = time.time() - 3600
        os.utime(self.review / "1-discovery" / "old.jsonl", (past, past))
        start = {"agent_type": "agentic-review:discovery", "agent_id": "d2", "cwd": str(self.review)}
        run("subagent-start", start)
        self.assertEqual(run("subagent-stop", start)[0], 0)

    def test_subagent_stop_runs_schema_validation_on_records(self):
        schema = Path(__file__).resolve().parent.parent / "templates" / "record.schema.json"
        (self.review / "schema.json").write_text(schema.read_text())
        good = {
            "key": "smith2021deep",
            "title": "Deep things",
            "year": 2021,
            "tier": "core",
            "family": "F1",
            "source_of_record": "https://arxiv.org/abs/2101.00001",
            "evidence_depth": "abstract",
        }
        bad = dict(good, key="lee2022fast")
        del bad["source_of_record"]
        start = {"agent_type": "agentic-review:discovery", "agent_id": "d3", "cwd": str(self.review)}
        run("subagent-start", start)
        time.sleep(0.05)
        records = self.review / "1-discovery" / "D1_records.jsonl"
        records.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n")
        code, _, err = run("subagent-stop", start)
        self.assertEqual(code, 2)
        self.assertIn("source_of_record", err)

        start = dict(start, agent_id="d4")
        run("subagent-start", start)
        time.sleep(0.05)
        records.write_text(json.dumps(good) + "\n")
        self.assertEqual(run("subagent-stop", start)[0], 0)

    def test_session_start_inside_and_outside_a_review(self):
        state_bin = Path(__file__).resolve().parent.parent / "bin" / "ar-state"
        (self.review / "state.json").unlink()
        subprocess.run([sys.executable, str(state_bin), str(self.review), "init"], capture_output=True, timeout=30)
        code, out, _ = run("session-start", {"hook_event_name": "SessionStart", "cwd": str(self.review)})
        self.assertEqual(code, 0)
        self.assertIn("/agentic-review:run", out)
        self.assertIn("protocol", out)
        code, out, _ = run("session-start", {"hook_event_name": "SessionStart", "cwd": str(self.outside)})
        self.assertEqual((code, out), (0, ""))

    def test_hook_log_records_first_sighting(self):
        self.pre("Read", {"file_path": str(self.review / "2-merged" / "x")}, "agentic-review:synthesis")
        seen = json.loads((self.review / ".agentic-review" / "seen_agent_types.json").read_text())
        self.assertIn("agentic-review:synthesis", seen)


if __name__ == "__main__":
    unittest.main()
