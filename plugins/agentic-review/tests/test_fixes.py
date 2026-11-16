"""Regression tests for the defects the first mini-review revealed. Standard library only."""

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
BIN = PLUGIN / "bin"
HOOK = PLUGIN / "hooks" / "ar_hook.py"


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(BIN / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def run(*args, stdin=None):
    p = subprocess.run([sys.executable, *map(str, args)], input=stdin, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


class CitationLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = load_script("ar-citemap")

    def label(self, authors, first_author=None, year=2023):
        r = {"authors": authors, "year": year}
        if first_author is not None:
            r["first_author"] = first_author
        return self.cm.base_label(r)

    def test_formats_agents_write(self):
        cases = [
            ("Feng R, Wu Q, Zhang Y", None, "Feng et al., 2023"),  # the contract's format
            ("Ruimin Feng; Qing Wu; Yuyao Zhang; Hongjiang Wei", "Ruimin Feng", "Feng et al., 2023"),
            ("Ruimin Feng; Qing Wu; Yuyao Zhang", "Feng", "Feng et al., 2023"),
            ("Lixuan Rao; A B; C D; E F; G H", None, "Rao et al., 2023"),
            ("Smith, John; Jones, Kate", None, "Smith and Jones, 2023"),
            ("Smith, John and Jones, Kate", None, "Smith and Jones, 2023"),
            ("Hongze Yu, Jeffrey A. Fessler, Yun Jiang", None, "Yu et al., 2023"),
            ("van der Berg K, Li X", None, "van der Berg and Li, 2023"),
            ("Ludwig van Beethoven", None, "van Beethoven, 2023"),
            ("Suresh Paul J, Doe J, Roe R", None, "Suresh Paul et al., 2023"),
            ("Mildenhall B, Srinivasan PP, et al.", None, "Mildenhall et al., 2023"),
            ("Ulyanov D, Vedaldi A, Lempitsky V", "Ulyanov", "Ulyanov et al., 2023"),
            ("Eo T", "Eo", "Eo, 2023"),
        ]
        for authors, fa, want in cases:
            with self.subTest(authors=authors):
                self.assertEqual(self.label(authors, fa), want)


class CrossrefYear(unittest.TestCase):
    def test_earliest_date_and_conference_start(self):
        rc = load_script("ar-refcheck")
        online_then_issue = {
            "published-online": {"date-parts": [[2022, 3, 1]]},
            "published-print": {"date-parts": [[2024, 1]]},
            "issued": {"date-parts": [[2022, 3]]},
        }
        self.assertEqual(rc.crossref_year(online_then_issue), 2022)
        proceedings = {
            "published-print": {"date-parts": [[2026, 1]]},
            "issued": {"date-parts": [[2026]]},
            "event": {"start": {"date-parts": [[2025, 9, 23]]}},
        }
        self.assertEqual(rc.crossref_year(proceedings), 2025)
        self.assertIsNone(rc.crossref_year({}))


class StateAndEstimate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        review = json.loads((PLUGIN / "templates" / "review.json").read_text())
        review["zotero"]["enabled"] = False
        review["scale"] = "mini"
        (self.dir / "review.json").write_text(json.dumps(review))
        run(BIN / "ar-state", self.dir, "init")

    def tearDown(self):
        self.tmp.cleanup()

    def test_zotero_checkpoints_not_needed_without_zotero(self):
        _code, out = run(BIN / "ar-state", self.dir, "show")
        self.assertIn("2 not needed (zotero.enabled is false)", out)
        self.assertIn("1 pending", out)
        self.assertEqual(run(BIN / "ar-state", self.dir, "require", "2")[0], 0)
        self.assertEqual(run(BIN / "ar-state", self.dir, "require", "1")[0], 1)

    def test_mini_scale_reduces_whole_corpus_roles_only(self):
        _code, out = run(BIN / "ar-estimate", self.dir, "1", "discovery", "--json")
        est = json.loads(out)
        self.assertAlmostEqual(est["wall_minutes"][0], 19.2, places=1)  # 55 min x 0.35
        self.assertIn("mini", est["source"])
        _code, out = run(BIN / "ar-estimate", self.dir, "1", "annotator", "--json")
        self.assertEqual(json.loads(out)["wall_minutes"], [2.0, 6.0])  # per-paper roles are not scaled


class HookOwnFiles(unittest.TestCase):
    """Two discovery agents in parallel: each is validated on its own files only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.review = Path(self.tmp.name)
        (self.review / "1-discovery").mkdir()
        (self.review / "review.json").write_text("{}")
        (self.review / "state.json").write_text("{}")
        (self.review / "schema.json").write_text((PLUGIN / "templates" / "record.schema.json").read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, mode, **data):
        data.setdefault("cwd", str(self.review))
        return run(HOOK, mode, stdin=json.dumps(data))[0]

    def test_parallel_agents(self):
        good = {
            "key": "smith2021deep",
            "title": "Deep things",
            "year": 2021,
            "tier": "core",
            "family": "F1",
            "source_of_record": "https://arxiv.org/abs/2101.00001",
            "evidence_depth": "abstract",
        }
        bad = {"key": "lee2022fast", "title": "Fast"}
        d1 = {"agent_type": "agentic-review:discovery", "agent_id": "d1"}
        d2 = {"agent_type": "agentic-review:discovery", "agent_id": "d2"}
        self.hook("subagent-start", **d1)
        self.hook("subagent-start", **d2)
        time.sleep(0.05)
        f1 = self.review / "1-discovery" / "D1_records.jsonl"
        self.assertEqual(
            self.hook("pre-tool", tool_name="Write", tool_input={"file_path": str(f1), "content": ""}, **d1), 0
        )
        f1.write_text(json.dumps(good) + "\n")
        self.assertEqual(
            self.hook(
                "pre-tool",
                tool_name="Bash",
                tool_input={"command": "python3 add.py >> 1-discovery/D2_records.jsonl"},
                **d2,
            ),
            0,
        )
        (self.review / "1-discovery" / "D2_records.jsonl").write_text(json.dumps(bad) + "\n")
        agents = json.loads((self.review / ".agentic-review" / "agents.json").read_text())
        self.assertEqual(agents["d1"]["files"], ["1-discovery/D1_records.jsonl"])
        self.assertEqual(agents["d2"]["files"], ["1-discovery/D2_records.jsonl"])
        self.assertEqual(self.hook("subagent-stop", **d1), 0, "D1 must not be blocked by D2's file")
        self.assertEqual(self.hook("subagent-stop", **d2), 2)


class Relabel(unittest.TestCase):
    def test_labels_follow_the_map_by_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "5-final").mkdir()
            (d / "review.json").write_text("{}")
            (d / "5-final" / "citation_map.tsv").write_text(
                "key\tlabel\turl\tsource\ttier\tfamily\tcite_year\ttitle\n"
                "feng2023scan\tFeng et al., 2023\thttps://doi.org/10.1/x\tcorpus\tcore\tF1\t2023\tT\n"
            )
            (d / "5-final" / "review.md").write_text(
                "A ([Ruimin Feng, 2023](https://doi.org/10.1/x)) and [other](https://example.org/y).\n"
            )
            code, out = run(BIN / "ar-relabel", d)
            self.assertEqual(code, 1, out)  # one link is not in the map
            text = (d / "5-final" / "review.md").read_text()
            self.assertIn("[Feng et al., 2023](https://doi.org/10.1/x)", text)
            self.assertIn("[other](https://example.org/y)", text)
            self.assertTrue((d / "5-final" / "review.before_relabel.md").exists())


# --------------------------------------------------------------------------- defects of the Zotero run

HARNESS = """
let live = 0, peak = 0, calls = 0
const agent = async (prompt, opts) => {
  live++; calls++; peak = Math.max(peak, live)
  await new Promise((r) => setTimeout(r, 3 + (calls % 4)))
  live--
  return { key: opts.label, status: 'done', yellow: 1, blue: 0, green: 0, red: 0, purple: 0, unsupported: [],
           issues: '', confirmed: 1, upgraded: 0, corrected: 0, highlights: 1 }
}
const pipeline = (items, ...stages) => Promise.all(items.map(async (item, i) => {
  let v = item
  for (const s of stages) v = await s(v, item, i)
  return v
}))
const phase = () => {}, log = () => {}
const args = __ARGS__
const body = async () => {
__SRC__
}
body().then((r) => console.log(JSON.stringify({ peak, calls, returned: r.summary.returned })))
"""


@unittest.skipUnless(__import__("shutil").which("node"), "node is not installed")
class WorkflowPacing(unittest.TestCase):
    """The annotate and late-pdfs workflows run at most `parallel` agents at once (limits.annotators_parallel)."""

    def run_workflow(self, name, args):
        src = (PLUGIN / "workflows" / name).read_text(encoding="utf-8").replace("export const meta", "const meta")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "wf.mjs"
            f.write_text(HARNESS.replace("__ARGS__", json.dumps(args)).replace("__SRC__", src), encoding="utf-8")
            p = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def test_parallel_limit(self):
        keys = [f"paper{i}" for i in range(23)]
        for name in ("annotate.js", "late-pdfs.js"):
            for parallel, peak in ((3, 3), (1, 1), (None, 8)):
                with self.subTest(workflow=name, parallel=parallel):
                    args = {"review_dir": "/tmp/r", "keys": keys}
                    if parallel is not None:
                        args["parallel"] = parallel
                    out = self.run_workflow(name, args)
                    self.assertEqual(out["calls"], 23)
                    self.assertEqual(out["returned"], 23)
                    self.assertEqual(out["peak"], peak)


if __name__ == "__main__":
    unittest.main()
