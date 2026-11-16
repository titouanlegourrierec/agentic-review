"""Unit tests for the agentic-review scripts (standard library only, no network).

Run: python3 -m unittest discover -s <plugin>/tests -v
Each test builds a small synthetic review folder in a temporary directory and runs the scripts as
subprocesses with the current interpreter. Network scripts run with --offline on a pre-filled cache; the
Zotero audit runs against a local stub server.
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from typing import ClassVar

PLUGIN = Path(__file__).resolve().parent.parent
BIN = PLUGIN / "bin"
sys.path.insert(0, str(PLUGIN / "lib"))
import arlib

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def run(script, *args):
    p = subprocess.run(
        [sys.executable, str(BIN / script), *map(str, args)], capture_output=True, text=True, env=ENV, timeout=120
    )
    return p.returncode, p.stdout + p.stderr


def rec(key, title, **kw):
    r = {
        "key": key,
        "title": title,
        "authors": kw.pop("authors", "Smith J, Jones K, Brown L"),
        "first_author": kw.pop("first_author", "Smith"),
        "year": kw.pop("year", 2021),
        "venue": "Journal X",
        "venue_type": "journal",
        "doi": None,
        "arxiv_id": None,
        "source_of_record": "https://example.org/p",
        "code": None,
        "tier": "core",
        "family": "F1",
        "task": "reconstruction",
        "setting": None,
        "datasets": None,
        "baselines": None,
        "metrics": None,
        "one_line_claim": None,
        "key_results": None,
        "limitations": None,
        "evidence_depth": "abstract",
        "confidence": "medium",
        "flags": [],
    }
    r.update(kw)
    return r


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ar-test-"))
        self.dir = self.tmp / "my review"  # a space on purpose
        self.dir.mkdir()
        self.review = json.loads((PLUGIN / "templates" / "review.json").read_text(encoding="utf-8"))
        self.review["topic"] = "Test topic"
        self.review["zotero"].update({"collection": "Test collection", "tag": "test-tag"})
        self.save_review()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save_review(self):
        (self.dir / "review.json").write_text(json.dumps(self.review), encoding="utf-8")

    def state(self):
        return json.loads((self.dir / "state.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- arlib


class TestLib(unittest.TestCase):
    def test_validator(self):
        schema = {
            "type": "object",
            "required": ["a"],
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": ["string", "null"], "enum": ["x", None]},
                "c": {"type": "string", "pattern": "^ab", "minLength": 3},
                "d": {"type": "object", "properties": {"u": {"type": ["string", "null"], "pattern": "^https?://"}}},
                "e": {"type": "array", "items": {"type": "string"}},
            },
        }
        self.assertEqual(arlib.validate({"a": 1, "b": None, "c": "abc", "d": {"u": None}, "e": ["q"]}, schema), [])
        errs = dict(arlib.validate({"a": True, "b": "y", "c": "ab", "d": {"u": "ftp://x"}, "e": [1], "z": 0}, schema))
        self.assertIn("a", errs)  # bool is not an integer
        self.assertIn("b", errs)  # enum
        self.assertIn("c", errs)  # minLength
        self.assertIn("d.u", errs)  # nested pattern
        self.assertIn("e[0]", errs)  # array items
        self.assertNotIn("z", errs)  # unknown properties allowed
        self.assertEqual(dict(arlib.validate({}, schema)), {"a": "required field missing"})

    def test_identifiers(self):
        self.assertEqual(arlib.norm_doi("https://doi.org/10.1000/ABC"), "10.1000/abc")
        self.assertEqual(arlib.clean_doi("https://doi.org/10.1000/ABC"), "10.1000/ABC")
        self.assertEqual(arlib.norm_arxiv("https://arxiv.org/abs/2101.00001v3"), "2101.00001")
        self.assertEqual(arlib.record_ids({"doi": "10.48550/arXiv.2101.00001"}), {("arxiv", "2101.00001")})
        self.assertEqual(arlib.family_codes("F3 (cascade); F10,F3"), ["F3", "F10"])
        self.assertEqual(arlib.unique_key("smith2021deep", {"smith2021deep"}), "smith2021deepb")
        self.assertEqual(arlib.make_key("Smith", 2021, "The deep prior"), "smith2021deep")
        self.assertEqual(arlib.map_tier(" Core "), "core")
        self.assertEqual(arlib.map_tier("legacy", {"tier_aliases": {"legacy": "core"}}), "core")

    def test_cite_year(self):
        self.assertEqual(arlib.cite_year({"year": 2020, "ref_check": {"year_vor": 2021}}, 2026), 2021)
        self.assertEqual(arlib.cite_year({"year": 2026, "ref_check": {"year_vor": 2027}}, 2026), 2026)
        self.assertEqual(arlib.cite_year({"year": 2020, "cite_year": 2019, "ref_check": {"year_vor": 2021}}), 2019)

    def test_rate_limit(self):
        import time

        arlib.MIN_INTERVAL["rate.test"] = 0.3
        t0 = time.monotonic()
        arlib._throttle("https://rate.test/a")
        arlib._throttle("https://rate.test/b")
        self.assertGreaterEqual(time.monotonic() - t0, 0.29)
        self.assertGreaterEqual(arlib.MIN_INTERVAL["export.arxiv.org"], 3.0)

    def test_http_offline_cache(self):
        with tempfile.TemporaryDirectory() as d:
            url = "https://api.crossref.org/works/10.1/x"
            with self.assertRaises(arlib.OfflineMiss):
                arlib.http_get(url, d, offline=True)
            arlib.cache_path(d, url).write_bytes(b"cached")
            self.assertEqual(arlib.http_get(url, d, offline=True), b"cached")
            arlib.cache_path(d, url + "/404").write_bytes(arlib.NOT_FOUND)
            self.assertIsNone(arlib.http_get(url + "/404", d, offline=True))
        self.assertNotIn("@", arlib.USER_AGENT)


# --------------------------------------------------------------------------- ar-state


class TestState(ReviewCase):
    def test_init_and_refuse_reinit(self):
        code, out = run("ar-state", self.dir, "init")
        self.assertEqual(code, 0, out)
        st = self.state()
        self.assertEqual(st["phase"], 0)
        self.assertEqual(set(st["checkpoints"]), {"1", "2", "3", "4"})
        self.assertTrue(all(c["status"] == "pending" for c in st["checkpoints"].values()))
        self.assertEqual(list(st["phases"]), ["0", "1", "2", "3", "3b", "4", "5", "6", "7"])
        code, _ = run("ar-state", self.dir, "init")
        self.assertEqual(code, 1)
        self.assertEqual(run("ar-state", self.dir, "init", "--force")[0], 0)

    def test_transitions_checkpoints_and_require(self):
        run("ar-state", self.dir, "init")
        self.assertEqual(run("ar-state", self.dir, "phase", "0", "done")[0], 0)
        code, out = run("ar-state", self.dir, "next")
        self.assertTrue(out.startswith("checkpoint 1"), out)
        code, out = run("ar-state", self.dir, "require", "1")
        self.assertEqual(code, 1)
        self.assertIn("not approved", out)
        code, out = run("ar-state", self.dir, "phase", "1", "running")  # recorded, with a warning
        self.assertEqual(code, 0)
        self.assertIn("warning: checkpoint 1", out)
        run("ar-state", self.dir, "phase", "1", "pending")
        self.assertEqual(run("ar-state", self.dir, "checkpoint", "1", "approve", "--note", "ok")[0], 0)
        self.assertEqual(run("ar-state", self.dir, "require", "1")[0], 0)
        self.assertEqual(run("ar-state", self.dir, "phase", "1", "running")[0], 0)
        self.assertEqual(self.state()["phase"], 1)
        self.assertEqual(run("ar-state", self.dir, "phase", "1", "done")[0], 0)
        self.assertEqual(run("ar-state", self.dir, "phase", "2", "running")[0], 0)
        code, out = run("ar-state", self.dir, "next", "--json")
        self.assertEqual(json.loads(out)["next"], "2")  # running, checkpoint 2 inside
        self.assertIn("checkpoint 2 pending", json.loads(out)["text"])
        self.assertIn("warning: checkpoint 2", run("ar-state", self.dir, "phase", "2", "done")[1])
        run("ar-state", self.dir, "phase", "2", "running")
        run("ar-state", self.dir, "checkpoint", "2", "approve")
        self.assertEqual(run("ar-state", self.dir, "phase", "2", "done")[0], 0)
        code, out = run("ar-state", self.dir, "next", "--json")
        self.assertEqual(json.loads(out)["next"], "3")
        run("ar-state", self.dir, "checkpoint", "2", "reset")
        self.assertEqual(run("ar-state", self.dir, "require", "2")[0], 1)
        st = self.state()
        self.assertEqual(st["checkpoints"]["1"]["note"], "ok")
        self.assertRegex(st["checkpoints"]["1"]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")
        self.assertTrue(len(st["log"]) >= 8)

    def test_next_skips_disabled_phases(self):
        self.review["zotero"]["enabled"] = False
        self.review["code_audit"]["enabled"] = True
        self.save_review()
        run("ar-state", self.dir, "init")
        run("ar-state", self.dir, "checkpoint", "1", "approve")
        for ph in ("0", "1"):
            run("ar-state", self.dir, "phase", ph, "done")
        self.assertEqual(json.loads(run("ar-state", self.dir, "next", "--json")[1])["next"], "3")
        run("ar-state", self.dir, "phase", "3", "done")  # checkpoint 2 is moot without Zotero
        self.assertEqual(json.loads(run("ar-state", self.dir, "next", "--json")[1])["next"], "3b")
        run("ar-state", self.dir, "phase", "3b", "done")
        run("ar-state", self.dir, "phase", "4", "done")
        # The reading edition runs without Zotero too: 5 and 6 are skipped, 7 comes next.
        self.assertEqual(json.loads(run("ar-state", self.dir, "next", "--json")[1])["next"], "7")
        run("ar-state", self.dir, "phase", "7", "done")
        self.assertEqual(run("ar-state", self.dir, "next")[1].strip(), "done")
        self.assertIn("is disabled", run("ar-state", self.dir, "phase", "5", "running")[1])
        self.assertEqual(run("ar-state", self.dir, "phase", "5", "skipped")[0], 0)

    def test_agents_and_show(self):
        run("ar-state", self.dir, "init")
        run("ar-state", self.dir, "agent", "start", "D1", "discovery")
        run("ar-state", self.dir, "agent", "start", "D2", "discovery")
        run("ar-state", self.dir, "agent", "done", "D1", "discovery")
        run("ar-state", self.dir, "agent", "failed", "D2", "discovery")
        agents = {a["id"]: a for a in self.state()["agents"]}
        self.assertEqual(agents["D1"]["status"], "done")
        self.assertEqual(agents["D2"]["status"], "failed")
        self.assertIn("finished", agents["D1"])
        code, out = run("ar-state", self.dir, "show")
        self.assertEqual(code, 0)
        self.assertIn("1 done, 1 failed", out)
        self.assertIn("Next:", out)
        self.assertIn("next", json.loads(run("ar-state", self.dir, "show", "--json")[1]))

    def test_bad_usage(self):
        run("ar-state", self.dir, "init")
        self.assertEqual(run("ar-state", self.dir, "phase", "9", "done")[0], 2)
        self.assertEqual(run("ar-state", self.dir, "phase", "1", "finished")[0], 2)
        self.assertEqual(run("ar-state", self.dir, "checkpoint", "5", "approve")[0], 2)
        self.assertEqual(run("ar-state", self.tmp / "nope", "show")[0], 2)
        self.assertEqual(run("ar-state", self.dir, "--help")[0], 0)


# --------------------------------------------------------------------------- ar-validate


class TestValidate(ReviewCase):
    def test_clean_file(self):
        write_jsonl(
            self.dir / "1-discovery" / "D1_records.jsonl",
            [rec("smith2021deep", "Deep things", doi="10.1000/a"), rec("jones2020fast", "Fast things")],
        )
        code, out = run("ar-validate", self.dir, "1-discovery/D1_records.jsonl")
        self.assertEqual(code, 0, out)

    def test_errors_with_line_numbers(self):
        bad = rec("smith2021deep", "Deep things", tier="primary", year="2021", doi="doi.org/10.1/x")
        del bad["evidence_depth"]
        p = self.dir / "1-discovery" / "D1_records.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(
            json.dumps(rec("ok2020fine", "Fine paper")) + "\n" + json.dumps(bad) + "\n{not json\n", encoding="utf-8"
        )
        code, out = run("ar-validate", self.dir, "1-discovery/D1_records.jsonl")
        self.assertEqual(code, 1)
        self.assertIn("D1_records.jsonl:2 [smith2021deep]: tier", out)
        self.assertIn("year: expected integer or null", out)
        self.assertIn("evidence_depth: required field missing", out)
        self.assertIn("doi:", out)
        self.assertIn("D1_records.jsonl:3: invalid JSON", out)

    def test_duplicates_and_quiet(self):
        write_jsonl(self.dir / "a.jsonl", [rec("smith2021deep", "Deep", doi="10.1000/A", arxiv_id="2101.00001")])
        write_jsonl(
            self.dir / "b.jsonl",
            [
                rec("smith2021deep", "Deep again", doi="https://doi.org/10.1000/a"),
                rec("lee2021other", "Other", arxiv_id="2101.00001v2"),
            ],
        )
        code, out = run("ar-validate", self.dir, "a.jsonl", "b.jsonl")
        self.assertEqual(code, 1)
        self.assertIn("duplicate key", out)
        self.assertIn("DOI 10.1000/a also in", out)
        self.assertIn("arXiv id 2101.00001 also in", out)
        code, out = run("ar-validate", self.dir, "a.jsonl", "b.jsonl", "--quiet")
        self.assertEqual(code, 1)
        self.assertEqual(len(out.strip().splitlines()), 1)
        code, out = run("ar-validate", "--quiet", self.dir, "a.jsonl")
        self.assertEqual((code, out.strip()), (0, "ar-validate: OK (1 records, 1 files)"))

    def test_auxiliary_files(self):
        write_jsonl(
            self.dir / "3-analysis" / "background_refs.jsonl",
            [
                {
                    "key": "classic1990base",
                    "title": "A classic",
                    "year": 1990,
                    "doi": "10.1000/x",
                    "source_of_record": "https://example.org/c",
                }
            ],
        )
        write_jsonl(self.dir / "4-checks" / "rigor_scores.jsonl", [{"key": "smith2021deep", "total": 3}])
        write_jsonl(self.dir / "4-checks" / "code" / "repo_audit.jsonl", [{"key": "smith2021deep", "total": 3}])
        write_jsonl(
            self.dir / "4-checks" / "code" / "code_records.jsonl",
            [{"key": "smith2021deep", "code": {"url": "https://example.org/repo", "commit": "abc1234"}}],
        )
        write_jsonl(
            self.dir / "4-checks" / "claims_check_C2.jsonl",
            [{"claim_id": "C2-1", "paper_key": "smith2021deep", "verdict": "supported", "claim_text": "x"}],
        )
        code, out = run(
            "ar-validate",
            self.dir,
            "3-analysis/background_refs.jsonl",
            "4-checks/code/repo_audit.jsonl",
            "4-checks/code/code_records.jsonl",
            "4-checks/claims_check_C2.jsonl",
        )
        self.assertEqual(code, 0, out)
        write_jsonl(
            self.dir / "4-checks" / "code" / "code_records.jsonl",
            [{"key": "smith2021deep", "code": {"url": "github.com/x", "commit": "zz"}}],
        )
        code, out = run("ar-validate", self.dir, "4-checks/code/code_records.jsonl")
        self.assertEqual(code, 1)
        self.assertIn("code.url", out)
        self.assertIn("code.commit", out)
        code, out = run("ar-validate", self.dir, "4-checks/rigor_scores.jsonl")
        self.assertEqual(code, 1)
        self.assertIn("scores: required field missing", out)

    def test_review_schema_is_used(self):
        schema = arlib.base_schema()
        schema["properties"]["domain_field"] = {"type": "string", "enum": ["a", "b"]}
        (self.dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
        write_jsonl(self.dir / "x.jsonl", [rec("smith2021deep", "Deep", domain_field="c")])
        code, out = run("ar-validate", self.dir, "x.jsonl")
        self.assertEqual(code, 1)
        self.assertIn("domain_field", out)
        self.assertEqual(run("ar-validate", self.dir, "missing.jsonl")[0], 2)


# --------------------------------------------------------------------------- ar-merge


class TestMerge(ReviewCase):
    def test_dedup_by_doi_arxiv_title(self):
        d = self.dir / "1-discovery"
        write_jsonl(
            d / "D1_records.jsonl",
            [
                rec(
                    "smith2021deep",
                    "Deep priors for things",
                    doi="https://doi.org/10.1000/ABC",
                    datasets="set A",
                    evidence_depth="full-text",
                    flags=["x"],
                ),
                rec("lee2020arx", "Arxiv only paper", first_author="Lee", year=2020, arxiv_id="2001.00001v1"),
                rec(
                    "kim2019title",
                    "A Title-Only Paper on Sparse Things",
                    first_author="Kim",
                    year=2019,
                    tier="boundary",
                ),
                rec("solo2022alone", "Completely different work", first_author="Solo", year=2022),
            ],
        )
        write_jsonl(
            d / "D2_records.jsonl",
            [
                rec(
                    "smith2021deepb",
                    "Deep priors for things (extended)",
                    doi="10.1000/abc",
                    datasets="set B",
                    flags=["y"],
                    tier="boundary",
                ),
                rec("lee2020arxiv", "Arxiv-only paper", first_author="Lee", year=2020, doi="10.48550/arXiv.2001.00001"),
                rec(
                    "kim2019titleonly",
                    "A title-only paper on sparse things.",
                    first_author="Kim",
                    year=2019,
                    tier="boundary",
                    limitations="small data",
                ),
                rec("solo2022alone", "Yet another unrelated study", first_author="Solo", year=2022),
            ],
        )
        code, out = run("ar-merge", self.dir)
        self.assertEqual(code, 0, out)
        merged = {r["key"]: r for r in arlib.load_jsonl(self.dir / "2-merged" / "merged.jsonl")}
        self.assertEqual(len(merged), 5, list(merged))
        s = merged["smith2021deep"]
        self.assertEqual(s["found_by"], ["D1", "D2"])
        self.assertEqual(s["doi"], "10.1000/abc")
        self.assertEqual(s["datasets"], "set A || [D2] set B")
        self.assertEqual(s["flags"], ["x", "y"])
        self.assertTrue(any("tier conflict" in n for n in s["merge_notes"]))
        self.assertEqual(s["tier"], "core")
        # the D2 record has more filled fields (DOI, plus the arXiv id derived from its arXiv DOI): its key wins
        self.assertEqual(merged["lee2020arxiv"]["found_by"], ["D1", "D2"])
        self.assertEqual(merged["lee2020arxiv"]["arxiv_id"], "2001.00001")
        kim = merged["kim2019titleonly"]  # D2's copy has more filled fields, so its key is kept
        self.assertEqual(kim["limitations"], "small data")
        self.assertEqual(kim["found_by"], ["D1", "D2"])
        self.assertIn("solo2022aloneb", merged)  # same key, different paper -> suffix b
        report = (self.dir / "2-merged" / "merge_report.md").read_text(encoding="utf-8")
        self.assertIn("Input records: 8 from 2 files; unique after merge: 5", report)
        self.assertEqual(run("ar-validate", self.dir, "2-merged/merged.jsonl")[0], 0)

    def test_no_input(self):
        self.assertEqual(run("ar-merge", self.dir)[0], 1)


# --------------------------------------------------------------------------- counts, citemap, catalogue, index


def build_corpus(case):
    corpus = [
        rec(
            "smith2021deep",
            "Deep",
            family="F1,F2",
            doi="10.1000/a",
            ref_check={"status": "verified", "year_vor": 2022, "venue_vor": "Journal X"},
        ),
        rec(
            "jones2020fast",
            "Fast",
            authors="Jones K, Lee M",
            first_author="Jones",
            year=2020,
            tier="boundary",
            family="B",
        ),
        rec(
            "lee2019old",
            "Old",
            first_author="Lee",
            authors="Lee M",
            year=2019,
            tier="boundary",
            family="F2",
            arxiv_id="1901.00001",
        ),
        rec("smith2022deeper", "Deeper", family="F2", year=2022),
    ]
    omissions = [
        rec(
            "park2023new",
            "New",
            first_author="Park",
            authors="Park S, Kim T, Ahn H",
            year=2023,
            family="F3,F1",
            tier="core",
        )
    ]
    background = [
        {
            "key": "classic1990base",
            "title": "A classic",
            "authors": "Classic A",
            "year": 1990,
            "doi": "10.1002/(SICI)1-2(199911)42:5",
            "arxiv_id": None,
            "source_of_record": "https://example.org/c",
        }
    ]
    write_jsonl(case.dir / "2-merged" / "corpus.jsonl", corpus)
    write_jsonl(case.dir / "4-checks" / "omissions_checked.jsonl", omissions)
    write_jsonl(case.dir / "3-analysis" / "background_refs.jsonl", background)
    (case.dir / "5-final").mkdir(parents=True, exist_ok=True)
    (case.dir / "5-final" / "retiering.json").write_text(
        json.dumps({"lee2019old": {"tier": "core", "family": "F2,F3", "reason": "test"}}), encoding="utf-8"
    )


class TestCounts(ReviewCase):
    def test_counts_with_retiering(self):
        build_corpus(self)
        code, out = run("ar-count", self.dir)
        self.assertEqual(code, 0, out)
        c = json.loads((self.dir / "5-final" / "counts.json").read_text(encoding="utf-8"))
        self.assertEqual(c["records"], {"corpus": 4, "omissions": 1, "all": 5})
        self.assertEqual(c["papers_by_tier"], {"core": 4, "boundary": 1})
        self.assertEqual(c["by_tier_family"]["core"], {"F1": 2, "F2": 3, "F3": 2})
        self.assertEqual(c["by_tier_primary_family"]["core"], {"F1": 1, "F2": 2, "F3": 1})
        self.assertEqual(c["multi_family_papers_by_tier"]["core"], 3)
        self.assertEqual(c["by_source"]["omissions"]["papers_by_tier"], {"core": 1})
        self.assertEqual(c["retiered"], 1)

    def test_counts_problems(self):
        build_corpus(self)
        (self.dir / "5-final" / "retiering.json").write_text(
            json.dumps({"ghost2020none": {"tier": "core"}}), encoding="utf-8"
        )
        code, out = run("ar-count", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("ghost2020none", out)

    def test_citemap_catalogue_index(self):
        build_corpus(self)
        code, out = run("ar-citemap", self.dir)
        self.assertEqual(code, 0, out)
        cmap = arlib.load_citemap(self.dir)
        self.assertEqual(cmap["smith2021deep"]["cite_year"], "2022")  # version-of-record year
        self.assertEqual(cmap["jones2020fast"]["label"], "Jones and Lee, 2020")
        self.assertEqual(cmap["lee2019old"]["label"], "Lee, 2019")
        self.assertEqual(cmap["lee2019old"]["url"], "https://arxiv.org/abs/1901.00001")
        self.assertEqual(cmap["classic1990base"]["url"], "https://doi.org/10.1002/(SICI)1-2(199911)42:5")
        self.assertEqual(cmap["park2023new"]["source"], "omission")
        # same base label -> a, b in title order ("Deep" < "Deeper")
        self.assertEqual(cmap["smith2021deep"]["label"], "Smith et al., 2022a")
        self.assertEqual(cmap["smith2022deeper"]["label"], "Smith et al., 2022b")
        rubric = [{"id": "C1", "name": "Data", "scoring": "0-2"}, {"id": "C2", "name": "Stats", "scoring": "0-2"}]
        self.review.update(
            {"taxonomy": {"F1": "one", "F2": "two", "F3": "three", "B": "baseline"}, "rigor_rubric": rubric}
        )
        self.save_review()
        write_jsonl(
            self.dir / "4-checks" / "rigor_scores.jsonl",
            [
                {
                    "key": "smith2021deep",
                    "scores": {"C1": 2, "C2": None},
                    "total": 2,
                    "max_possible": 2,
                    "evidence_depth": "full-text",
                },
                {"key": "lee2019old", "scores": {"C1": 1, "C2": 0}, "total": 1, "max_possible": 4},
            ],
        )
        code, out = run("ar-catalogue", self.dir)
        self.assertEqual(code, 0, out)
        cat = (self.dir / "5-final" / "catalogue.md").read_text(encoding="utf-8")
        self.assertIn("## Core (4)", cat)
        self.assertIn("## Boundary (1)", cat)
        self.assertIn("Families: F1 one", cat)
        self.assertIn("(https://doi.org/10.1000/a)", cat)
        self.assertIn("† |", cat)
        rig = (self.dir / "5-final" / "rigor_table.md").read_text(encoding="utf-8")
        self.assertIn("| Paper | Read | C1 | C2 | Total |", rig)
        self.assertLess(rig.index("Smith et al., 2022"), rig.index("Lee, 2019"))
        self.assertIn("| 2 | – | 2/2 |", rig)
        code, out = run("ar-index", self.dir)
        self.assertEqual(code, 0, out)
        idx = (self.dir / "2-merged" / "corpus_index.md").read_text(encoding="utf-8")
        self.assertIn("| smith2021deep | core | F1,F2 | reconstruction | 2022 |", idx)


# --------------------------------------------------------------------------- ar-check-review and ar-packets


class TestReview(ReviewCase):
    def setUp(self):
        super().setUp()
        self.review["review_sections"] = [
            {"id": "s0", "heading": "Summary"},
            {"id": "s1", "heading": "Body"},
            {"id": "s2", "heading": "References"},
        ]
        self.save_review()
        build_corpus(self)
        run("ar-citemap", self.dir)
        self.cmap = arlib.load_citemap(self.dir)

    def link(self, key):
        return f"[{self.cmap[key]['label']}]({self.cmap[key]['url']})"

    def write_review(self, text):
        (self.dir / "5-final" / "review.md").write_text(text, encoding="utf-8")

    def good_text(self):
        return (
            f"<!-- section: s0 -->\n## Summary\n\nWe cite {self.link('smith2021deep')} and a "
            f"[project page](https://example.org/x).\n\n<!-- section: s1 -->\n## Body\n\n"
            f"| a | b |\n| --- | --- |\n| {self.link('jones2020fast')} | `x|y` |\n\n"
            f"Also {self.link('park2023new')}.\n\n"
            f"<!-- section: s2 -->\n## References\n\n- {self.link('smith2021deep')}\n"
        )

    def test_pass(self):
        self.write_review(self.good_text())
        code, out = run("ar-check-review", self.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)

    def test_marker_order(self):
        t = self.good_text().replace("<!-- section: s1 -->", "<!-- section: tmp -->")
        t = t.replace("<!-- section: s0 -->", "<!-- section: s1 -->").replace(
            "<!-- section: tmp -->", "<!-- section: s0 -->"
        )
        self.write_review(t)
        code, out = run("ar-check-review", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("out of order", out)
        self.write_review(self.good_text().replace("<!-- section: s2 -->\n", ""))
        code, out = run("ar-check-review", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("missing ['s2']", out)

    def test_bad_links(self):
        t = (
            self.good_text() + "\nWrong [Smith et al., 2022a](https://doi.org/10.9999/zzz) and "
            "[Nobody et al., 2017](https://example.org/n).\n"
        )
        self.write_review(t)
        code, out = run("ar-check-review", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("URL differs from the map", out)
        self.assertIn("not in the map", out)
        self.assertIn("Nobody et al., 2017", out)

    def test_bad_table(self):
        self.write_review(self.good_text().replace("| a | b |\n", "| a | b | c |\n"))
        code, out = run("ar-check-review", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("inconsistent column counts", out)

    def test_packets(self):
        self.write_review(self.good_text())
        write_jsonl(
            self.dir / "4-checks" / "claims_check.jsonl",
            [
                {
                    "claim_id": "C-1",
                    "paper_key": "smith2021deep",
                    "verdict": "supported",
                    "claim_text": "It works",
                    "evidence": "Table 2",
                    "correct_value": None,
                }
            ],
        )
        write_jsonl(
            self.dir / "4-checks" / "claims_check_C2.jsonl",
            [
                {
                    "claim_id": "C2-1",
                    "paper_key": "smith2021deep",
                    "verdict": "contradicted",
                    "claim_text": "It flies",
                    "evidence": "Fig. 3",
                    "correct_value": "it walks",
                }
            ],
        )
        write_jsonl(
            self.dir / "4-checks" / "rigor_scores.jsonl",
            [
                {
                    "key": "smith2021deep",
                    "scores": {"C1": 2},
                    "total": 2,
                    "max_possible": 2,
                    "red_flags": [],
                    "justifications": {"C1": "raw data"},
                }
            ],
        )
        code, out = run("ar-packets", self.dir)
        self.assertEqual(code, 0, out)
        files = sorted(p.name for p in (self.dir / "5-final" / "packets").iterdir())
        self.assertEqual(files, ["jones2020fast.md", "park2023new.md", "smith2021deep.md"])
        p = (self.dir / "5-final" / "packets" / "smith2021deep.md").read_text(encoding="utf-8")
        self.assertIn("- [Summary] We cite", p)
        self.assertNotIn("[References]", p)
        self.assertIn("C-1 [supported] It works", p)
        self.assertIn("C2-1 [contradicted] It flies", p)
        self.assertIn("## Rigor appraisal: 2/2", p)
        p = (self.dir / "5-final" / "packets" / "jones2020fast.md").read_text(encoding="utf-8")
        self.assertIn("- [Body] |", p)

    def test_packets_cover_background_references(self):
        write_jsonl(
            self.dir / "3-analysis" / "background_refs.jsonl",
            [
                {
                    "key": "ulyanov2020deep",
                    "title": "Deep Image Prior",
                    "authors": "Dmitry Ulyanov; Andrea Vedaldi",
                    "first_author": "Ulyanov",
                    "year": 2020,
                    "doi": "10.1007/s11263-020-01303-4",
                    "arxiv_id": "1711.10925",
                    "source_of_record": "https://api.crossref.org/works/10.1007/s11263-020-01303-4",
                }
            ],
        )
        run("ar-citemap", self.dir)
        self.cmap = arlib.load_citemap(self.dir)
        self.write_review(self.good_text().replace("Also ", f"Background {self.link('ulyanov2020deep')}. Also "))
        code, out = run("ar-packets", self.dir)
        self.assertEqual(code, 0, out)
        p = (self.dir / "5-final" / "packets" / "ulyanov2020deep.md").read_text(encoding="utf-8")
        self.assertIn("- Title: Deep Image Prior", p)
        self.assertIn("- Tier / family (after re-tiering): background / ", p)
        self.assertIn("- [Body] Background [Ulyanov", p)


# --------------------------------------------------------------------------- network scripts, offline

ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><id>http://arxiv.org/abs/1901.00001v2</id><title>Old  results
 revisited</title><published>2019-01-02T00:00:00Z</published>
 <author><name>Mia Lee</name></author></entry>
</feed>"""


class TestNetworkOffline(ReviewCase):
    def crossref(self, title, year, family="Smith", doi="10.1000/a"):
        return json.dumps(
            {
                "message": {
                    "title": [title],
                    "published-print": {"date-parts": [[year, 1]]},
                    "container-title": ["Journal X"],
                    "author": [{"family": family}],
                    "DOI": doi,
                    "type": "journal-article",
                }
            }
        ).encode()

    def test_refcheck_with_prefilled_cache(self):
        cache = self.dir / ".cache" / "refcheck"
        cache.mkdir(parents=True)
        recs = [
            rec("smith2021deep", "Deep priors for things", doi="https://doi.org/10.1000/A"),
            rec("lee2019old", "Old results revisited", first_author="Lee", year=2019, arxiv_id="1901.00001"),
            rec("bad2020wrong", "Something else entirely", doi="10.1000/b"),
            rec("none2018noid", "A paper without identifiers", first_author="None", year=2018),
        ]
        write_jsonl(self.dir / "2-merged" / "merged.jsonl", recs)
        arlib.cache_path(cache, "https://api.crossref.org/works/10.1000/a").write_bytes(
            self.crossref("Deep Priors for Things", 2022)
        )
        arlib.cache_path(cache, "https://api.crossref.org/works/10.1000/b").write_bytes(
            self.crossref("Totally unrelated title here", 2020, doi="10.1000/b")
        )
        arlib.cache_path(cache, "https://export.arxiv.org/api/query?id_list=1901.00001&max_results=1").write_bytes(
            ATOM_FEED.encode()
        )
        code, out = run(
            "ar-refcheck",
            self.dir,
            "2-merged/merged.jsonl",
            "2-merged/corpus.jsonl",
            "2-merged/refcheck_report.md",
            "--offline",
        )
        self.assertEqual(code, 1, out)  # one mismatch, one unresolved
        got = {r["key"]: r for r in arlib.load_jsonl(self.dir / "2-merged" / "corpus.jsonl")}
        s = got["smith2021deep"]["ref_check"]
        self.assertEqual(s["status"], "verified")
        self.assertIn("year-differs(record 2021 vs crossref 2022)", s["checks"])
        self.assertEqual(s["year_vor"], 2022)
        self.assertEqual(got["smith2021deep"]["doi"], "10.1000/a")
        self.assertEqual(s["normalised"]["doi"], ["https://doi.org/10.1000/A", "10.1000/a"])
        self.assertEqual(got["lee2019old"]["ref_check"]["status"], "verified")
        self.assertEqual(got["bad2020wrong"]["ref_check"]["status"], "mismatch")
        self.assertNotIn("year_vor", got["bad2020wrong"]["ref_check"])
        self.assertEqual(got["none2018noid"]["ref_check"]["status"], "unresolved")
        self.assertIn("search-not-run(offline)", got["none2018noid"]["ref_check"]["checks"])
        report = (self.dir / "2-merged" / "refcheck_report.md").read_text(encoding="utf-8")
        self.assertIn("| bad2020wrong | mismatch |", report)
        self.assertFalse(any(cache.glob("*.tmp")))

    def test_refcheck_against_corpus(self):
        write_jsonl(self.dir / "2-merged" / "corpus.jsonl", [rec("smith2021deep", "Deep priors", doi="10.1000/a")])
        write_jsonl(
            self.dir / "4-checks" / "omissions.jsonl",
            [
                rec("dup2021same", "Something", doi="https://doi.org/10.1000/A"),
                rec("smith2021deep", "Another deep paper", year=2021),
                rec("near2021title", "Deep priors."),
            ],
        )
        _code, _out = run(
            "ar-refcheck",
            self.dir,
            "4-checks/omissions.jsonl",
            "4-checks/omissions_checked.jsonl",
            "4-checks/omissions_refcheck.md",
            "--offline",
            "--against",
            "2-merged/corpus.jsonl",
        )
        kept = arlib.load_jsonl(self.dir / "4-checks" / "omissions_checked.jsonl")
        self.assertEqual([r["key"] for r in kept], ["smith2021deepb"])
        self.assertEqual(kept[0]["found_by"], ["omissions"])
        rep = (self.dir / "4-checks" / "omissions_refcheck.md").read_text(encoding="utf-8")
        self.assertIn("dup2021same: doi 10.1000/a", rep)
        self.assertIn("near2021title: title", rep)

    def test_bib_with_prefilled_cache(self):
        build_corpus(self)
        cache = self.dir / ".cache" / "bib"
        cache.mkdir(parents=True)
        accept = {"Accept": "application/x-bibtex; charset=utf-8"}
        arlib.cache_path(cache, "https://doi.org/10.1000/a", accept).write_bytes(
            b"@article{Smith_2022, title={Deep <i>priors</i>}, author={Smith, J.}, year={2022}}"
        )
        arlib.cache_path(cache, "https://export.arxiv.org/api/query?id_list=1901.00001&max_results=1").write_bytes(
            ATOM_FEED.encode()
        )
        code, out = run("ar-bib", self.dir, "--offline")
        self.assertEqual(code, 0, out)
        bib = (self.dir / "5-final" / "references.bib").read_text(encoding="utf-8")
        self.assertIn("@article{smith2021deep,", bib)
        self.assertNotIn("<i>", bib)
        self.assertIn("@misc{lee2019old,", bib)
        self.assertIn("eprint = {1901.00001}", bib)
        self.assertIn("@misc{classic1990base,", bib)
        self.assertEqual(bib.count("\n@"), 6)
        self.assertIn('"Test topic"', bib)


# --------------------------------------------------------------------------- ar-zotero-audit (local stub)


class _Stub(http.server.BaseHTTPRequestHandler):
    routes: ClassVar[dict] = {}

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        key = u.path + ("?itemType=" + q["itemType"][0] if "itemType" in q else "")
        body = json.dumps(self.routes.get(key, [])).encode() if int(q.get("start", ["0"])[0]) == 0 else b"[]"
        self.send_response(200 if key in self.routes else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class TestZoteroAudit(ReviewCase):
    def test_audit_against_stub(self):
        api = "/api/users/0"

        def item(k, doi):
            return {
                "key": k,
                "data": {
                    "itemType": "journalArticle",
                    "title": f"Paper {k}",
                    "DOI": doi,
                    "tags": [{"tag": "test-tag"}] if k == "ITEM0001" else [],
                },
            }

        def ann(k):
            return {
                "key": k,
                "data": {
                    "parentItem": "PDF00001",
                    "annotationType": "highlight",
                    "annotationPageLabel": "3",
                    "annotationText": "same text",
                    "annotationComment": "",
                    "annotationColor": "#ffd400",
                },
            }

        _Stub.routes = {
            f"{api}/collections": [{"key": "COLL0001", "data": {"name": "Test collection", "parentCollection": False}}],
            f"{api}/collections/COLL0001/collections": [{"key": "COLL0002", "data": {"name": "Sub"}}],
            f"{api}/collections/COLL0002/collections": [],
            f"{api}/collections/COLL0001/items/top": [item("ITEM0001", "10.1/a")],
            f"{api}/collections/COLL0002/items/top": [item("ITEM0002", "10.1/A")],
            f"{api}/items?itemType=annotation": [ann("ANN00001"), ann("ANN00002")],
            f"{api}/items/ITEM0001/children": [
                {"key": "NOTE0001", "data": {"itemType": "note", "note": "<h1>Review notes</h1>"}},
                {"key": "PDF00001", "data": {"itemType": "attachment", "contentType": "application/pdf"}},
            ],
            f"{api}/items/ITEM0002/children": [],
        }
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Stub)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            code, out = run("ar-zotero-audit", self.dir, "--api", f"http://127.0.0.1:{srv.server_port}{api}")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(code, 1, out)  # duplicates found
        self.assertIn("items=2", out)
        self.assertIn("duplicate items: {'10.1/a': ['ITEM0001', 'ITEM0002']}", out)
        self.assertIn("duplicate annotations (1)", out)
        self.assertIn("items without the tag 'test-tag': ['ITEM0002']", out)
        csv_text = (self.dir / "5-final" / "zotero_audit.csv").read_text(encoding="utf-8")
        self.assertTrue(csv_text.startswith("item,collection,title,doi,has_tag,pdfs,review_notes,annotations,yellow"))
        self.assertIn("ITEM0001,Test collection,Paper ITEM0001,10.1/a,True,1,1,2,2", csv_text)

    def test_unreachable(self):
        code, out = run("ar-zotero-audit", self.dir, "--api", "http://127.0.0.1:9/api/users/0")
        self.assertEqual(code, 1)
        self.assertIn("cannot read Zotero", out)


# --------------------------------------------------------------------------- ar-estimate


class TestEstimate(ReviewCase):
    def test_defaults_and_overrides(self):
        code, out = run("ar-estimate", self.dir, "4", "discovery")
        self.assertEqual(code, 0, out)
        self.assertIn("wall time: 55 min", out)
        self.assertNotRegex(out, r"\$|cost|price")  # the plugin never talks about money
        code, out = run("ar-estimate", self.dir, "20", "annotator", "--json")
        e = json.loads(out)
        self.assertEqual((e["parallel"], e["waves"]), (8, 3))
        self.assertTrue(e["exceeds_confirm_limit"])  # 20 agents > the default of 10
        self.assertFalse(any("cost" in k for k in e))
        self.review["estimates"] = {"discovery": {"cost_usd": [10, 12], "minutes": 30}}  # old key ignored
        self.review["limits"]["confirm_above_agents"] = 30
        self.save_review()
        e = json.loads(run("ar-estimate", self.dir, "2", "discovery", "--json")[1])
        self.assertEqual(e["wall_minutes"], [30.0, 30.0])
        self.assertEqual(e["source"], "review.json estimates")
        self.assertFalse(
            json.loads(run("ar-estimate", self.dir, "20", "annotator", "--json")[1])["exceeds_confirm_limit"]
        )
        self.assertEqual(run("ar-estimate", self.dir, "2", "nobody")[0], 2)


class TestHelpAndHygiene(unittest.TestCase):
    SCRIPTS: ClassVar[list] = [
        "ar-state",
        "ar-validate",
        "ar-merge",
        "ar-refcheck",
        "ar-index",
        "ar-count",
        "ar-citemap",
        "ar-bib",
        "ar-check-review",
        "ar-catalogue",
        "ar-packets",
        "ar-estimate",
        "ar-zotero-audit",
        "ar-code",
        "ar-share",
    ]

    def test_every_script_has_help_and_shebang(self):
        for s in self.SCRIPTS:
            p = BIN / s
            self.assertTrue(os.access(p, os.X_OK), s)
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "#!/usr/bin/env python3", s)
            self.assertTrue(
                any(
                    'sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))' in ln for ln in lines[:25]
                ),
                s,
            )
            code, out = run(s, "--help")
            self.assertEqual(code, 0, s)
            self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()
