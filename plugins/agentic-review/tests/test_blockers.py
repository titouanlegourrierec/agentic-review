"""Regression tests for the defects found by the pre-distribution audit (2026-11-16). Standard library only.

Hook guards when Claude runs in a parent folder and Zotero's empty replacements are in test_hooks.py; this file
covers the scripts: title merges, the BibTeX file, compound family names and the deferred Phase 6.
"""

import json
import re
import unittest

import test_scripts
from test_scripts import PLUGIN, ReviewCase, arlib, rec, run, write_jsonl


class TitleMerges(ReviewCase):
    def merged(self):
        code, out = run("ar-merge", self.dir)
        self.assertEqual(code, 0, out)
        return {r["key"]: r for r in arlib.load_jsonl(self.dir / "2-merged" / "merged.jsonl")}, out

    def test_similar_titles_with_different_dois_stay_apart(self):
        d = self.dir / "1-discovery"
        write_jsonl(
            d / "D1_records.jsonl",
            [
                rec("smith2023inr", "INR-based reconstruction of 2D cardiac MRI", doi="10.1000/aaa"),
                rec("doe2024part", "Neural fields for MRI, Part I", first_author="Doe", year=2024),
            ],
        )
        write_jsonl(
            d / "D2_records.jsonl",
            [
                rec("smith2023inrb", "INR-based reconstruction of 3D cardiac MRI", doi="10.1000/bbb"),
                rec("doe2024partb", "Neural fields for MRI, Part II", first_author="Doe", year=2024),
            ],
        )
        merged, out = self.merged()
        self.assertEqual(len(merged), 4, list(merged))
        self.assertIn("similar_kept_apart=2", out)
        report = (self.dir / "2-merged" / "merge_report.md").read_text(encoding="utf-8")
        self.assertIn("Similar titles kept apart", report)
        self.assertIn("10.1000/bbb", report)

    def test_title_chain_cannot_join_two_dois(self):
        d = self.dir / "1-discovery"
        write_jsonl(d / "D1_records.jsonl", [rec("a2021x", "Deep priors for sparse things", doi="10.1000/a")])
        write_jsonl(d / "D2_records.jsonl", [rec("b2021x", "Deep priors for sparse things.")])
        write_jsonl(d / "D3_records.jsonl", [rec("c2021x", "Deep priors for sparse things!", doi="10.1000/c")])
        merged, _ = self.merged()
        dois = sorted(r.get("doi") or "" for r in merged.values())
        self.assertEqual(len(merged), 2, list(merged))
        self.assertEqual(dois, ["10.1000/a", "10.1000/c"])

    def test_same_paper_found_as_preprint_and_article_still_merges(self):
        d = self.dir / "1-discovery"
        write_jsonl(d / "D1_records.jsonl", [rec("lee2021fast", "Fast neural fields for MRI", doi="10.1000/j")])
        write_jsonl(
            d / "D2_records.jsonl",
            [rec("lee2021fastb", "Fast Neural Fields for MRI", arxiv_id="2101.00001", year=2020)],
        )
        write_jsonl(d / "D3_records.jsonl", [rec("lee2021fastc", "Fäst neural fields for MRI")])
        merged, _ = self.merged()
        self.assertEqual(len(merged), 1, list(merged))

    def test_preprint_and_article_years_apart_still_merge(self):
        d = self.dir / "1-discovery"
        write_jsonl(
            d / "D1_records.jsonl", [rec("lee2024fast", "Fast neural fields for MRI", doi="10.1000/j", year=2024)]
        )
        write_jsonl(
            d / "D2_records.jsonl",
            [rec("lee2021fast", "Fast neural fields for MRI.", arxiv_id="2101.00001", year=2021)],
        )
        merged, _ = self.merged()
        self.assertEqual(len(merged), 1, list(merged))

    def test_title_only_match_needs_same_author_and_close_year(self):
        d = self.dir / "1-discovery"
        write_jsonl(d / "D1_records.jsonl", [rec("smith2015survey", "A survey of neural fields", year=2015)])
        write_jsonl(
            d / "D2_records.jsonl",
            [
                rec("smith2022survey", "A survey of neural fields", year=2022),
                rec(
                    "kim2015survey",
                    "A survey of neural fields.",
                    first_author="Kim",
                    authors="Kim A, Park B",
                    year=2015,
                ),
            ],
        )
        merged, _ = self.merged()
        self.assertEqual(len(merged), 3, list(merged))

    def test_text_year_does_not_crash(self):
        d = self.dir / "1-discovery"
        write_jsonl(
            d / "D1_records.jsonl",
            [rec("a2021one", "One paper", year="2021"), rec("b2020two", "Another paper entirely", year=2020)],
        )
        merged, _ = self.merged()
        self.assertEqual(len(merged), 2)

    def test_refcheck_keeps_an_omission_with_its_own_doi(self):
        write_jsonl(
            self.dir / "2-merged" / "corpus.jsonl",
            [rec("smith2023inr", "INR-based reconstruction of 2D cardiac MRI", doi="10.1000/aaa")],
        )
        write_jsonl(
            self.dir / "4-checks" / "omissions.jsonl",
            [rec("smith2023inr3d", "INR-based reconstruction of 3D cardiac MRI", doi="10.1000/bbb")],
        )
        run(
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
        self.assertEqual([r["key"] for r in kept], ["smith2023inr3d"])


DOI_BIB = (
    b"@article{Qian_2025, title={cMeta-INR: cohort-informed learning for volumetric Mri estimation}, "
    b"volume={71}, url={http://dx.doi.org/10.1088/1361-6560/ae29e2}, DOI={10.1088/1361-6560/ae29e2}, "
    b"journal={Physics in Medicine &amp;amp; Biology}, publisher={IOP Publishing}, "
    b"author={Qian, Xiaoxue and Zhang, You}, year={2024}, month=sept, pages={015003} }"
)


class Bibliography(ReviewCase):
    def build(self, records):
        write_jsonl(self.dir / "2-merged" / "corpus.jsonl", records)
        code, out = run("ar-bib", self.dir, "--offline")
        self.assertEqual(code, 0, out)
        text = (self.dir / "5-final" / "references.bib").read_text(encoding="utf-8")
        return {m.group(1): m.group(0) for m in re.finditer(r"^@\w+\{([^,]+),.*?(?=^@|\Z)", text, re.M | re.S)}

    def test_publisher_entry_is_cleaned(self):
        cache = self.dir / ".cache" / "bib"
        cache.mkdir(parents=True)
        accept = {"Accept": "application/x-bibtex; charset=utf-8"}
        arlib.cache_path(cache, "https://doi.org/10.1088/1361-6560/ae29e2", accept).write_bytes(DOI_BIB)
        entries = self.build(
            [
                rec(
                    "qian2025cmeta",
                    "cMeta-INR: cohort-informed learning for volumetric MRI estimation",
                    doi="10.1088/1361-6560/ae29e2",
                    year=2025,
                )
            ]
        )
        e = entries["qian2025cmeta"]
        self.assertNotIn("&amp;", e)
        self.assertIn(r"Physics in Medicine \& Biology", e)
        self.assertIn("{cMeta-INR}", e)
        self.assertIn("{MRI}", e)  # the record's casing, protected
        self.assertIn("year={2024}", e)  # DOI entries keep the publisher's year
        self.assertIn("month=sep", e)
        self.assertIn("url={http://dx.doi.org/10.1088/1361-6560/ae29e2}", e)

    def test_record_entry_escapes_and_names(self):
        entries = self.build(
            [
                rec(
                    "feng2023fast",
                    "Fast {unbalanced 100% & a_b MRI",
                    authors="Ruimin Feng; Qing Wu; Yuyao Zhang",
                    first_author="Feng",
                    year=2023,
                    source_of_record="https://example.org/a_b",
                ),
                rec(
                    "alhajhemidi2024cine",
                    "CineJENSE",
                    authors="Ziad Al-Haj Hemidi, Nora Vogt, et al.",
                    first_author="Hemidi",
                    year=2024,
                ),
            ]
        )
        f = entries["feng2023fast"]
        self.assertIn(r"Fast \{unbalanced 100\% \& a\_b {MRI}", f)
        self.assertIn("author = {Feng, Ruimin and Wu, Qing and Zhang, Yuyao}", f)
        self.assertIn("url = {https://example.org/a_b}", f)
        h = entries["alhajhemidi2024cine"]
        self.assertIn("author = {Al-Haj Hemidi, Ziad and Vogt, Nora and others}", h)
        self.assertEqual(f.count("{") - f.count(r"\{"), f.count("}") - f.count(r"\}"))


class CompoundNames(unittest.TestCase):
    def test_family_name_from_crossref_or_key(self):
        cases = [
            (
                {
                    "key": "alhajhemidi2025priiner",
                    "authors": "Ziad Al-Haj Hemidi, Eytan Kats, Mattias P. Heinrich",
                    "first_author": "Hemidi",
                },
                "Al-Haj Hemidi",
            ),
            (
                {
                    "key": "x2024y",
                    "authors": "Ziad Al-Haj Hemidi; Nora Vogt",
                    "ref_check": {"crossref": {"first_author": "Al-Haj Hemidi"}},
                },
                "Al-Haj Hemidi",
            ),
            ({"key": "shen2022nerp", "authors": "Liyue Shen, John Pauly, Lei Xing"}, "Shen"),
            ({"key": "berg2020x", "authors": "van der Berg K, Li X"}, "van der Berg"),
        ]
        for r, want in cases:
            with self.subTest(r=r["key"]):
                self.assertEqual(arlib.first_surname(r), want)


class DeferredPhase6(ReviewCase):
    def test_phase_6_never_holds_up_the_edition(self):
        self.review["zotero"]["enabled"] = True
        self.save_review()
        run("ar-state", self.dir, "init")
        run("ar-state", self.dir, "phase", "0", "done")
        run("ar-state", self.dir, "checkpoint", "1", "approve")
        for ph in ("1", "2", "3", "4", "5"):
            if ph == "2":
                run("ar-state", self.dir, "checkpoint", "2", "approve")
            if ph == "5":
                run("ar-state", self.dir, "checkpoint", "3", "approve")
            self.assertEqual(run("ar-state", self.dir, "phase", ph, "done")[0], 0)
        self.assertEqual(json.loads(run("ar-state", self.dir, "next", "--json")[1])["next"], "7")
        _code, out = run("ar-state", self.dir, "phase", "7", "done")
        self.assertNotIn("warning", out)
        _code, out = run("ar-state", self.dir, "next")
        self.assertIn("phase 6 (late full texts) stays open", out)
        self.assertEqual(json.loads(run("ar-state", self.dir, "next", "--json")[1])["next"], "done")
        # add-pdfs approves checkpoint 4 and runs the phase; next follows it while it runs
        run("ar-state", self.dir, "checkpoint", "4", "approve")
        run("ar-state", self.dir, "phase", "6", "running")
        self.assertEqual(json.loads(run("ar-state", self.dir, "next", "--json")[1])["next"], "6")
        self.assertEqual(run("ar-state", self.dir, "phase", "6", "done")[0], 0)
        self.assertEqual(run("ar-state", self.dir, "next")[1].strip(), "done")

    def test_playbook_marks_phase_2_done_and_add_pdfs_approves_checkpoint_4(self):
        phases = (PLUGIN / "skills" / "run" / "phases.md").read_text(encoding="utf-8")
        self.assertIn("`ar-state phase 2 done`", phases)
        add = (PLUGIN / "skills" / "add-pdfs" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("checkpoint 4 approve", add)
        self.assertIn("phase 6 done", add)


class CodeAudit(ReviewCase):
    def test_per_agent_files_are_joined_and_reported(self):
        write_jsonl(
            self.dir / "2-merged" / "corpus.jsonl", [rec("a2021x", "A"), rec("b2021x", "B"), rec("c2021x", "C")]
        )
        code = self.dir / "4-checks" / "code"
        write_jsonl(
            code / "code_records_K1.jsonl",
            [
                {
                    "key": "a2021x",
                    "code": {"url": "https://github.com/o/a", "commit": "abc1234", "license": "MIT", "weights": "yes"},
                },
                {"key": "b2021x", "code": {"url": None}, "notes": "code coming soon"},
            ],
        )
        write_jsonl(
            code / "code_records_K2.jsonl",
            [
                {
                    "key": "c2021x",
                    "code": {"url": "https://github.com/o/c", "commit": None, "license": None, "weights": "no"},
                }
            ],
        )
        write_jsonl(
            code / "repo_audit_RA1.jsonl",
            [
                {
                    "key": "a2021x",
                    "repo": "https://github.com/o/a",
                    "total": 12,
                    "items": {"readme": {"score": 2}, "weights": {"score": 0}},
                }
            ],
        )
        write_jsonl(
            code / "paper_code_PC1.jsonl",
            [
                {
                    "claim_id": 1,
                    "paper_key": "a2021x",
                    "claim_text": "uses an L1 loss",
                    "verdict": "differs",
                    "code_permalink": "https://github.com/o/a/blob/abc1234/train.py#L10-L12",
                }
            ],
        )
        write_jsonl(
            code / "paper_code_PC2.jsonl",
            [{"claim_id": 1, "paper_key": "c2021x", "claim_text": "x", "verdict": "conforms"}],
        )
        for f in sorted(code.glob("*_*.jsonl")):  # each agent's file validates on its own
            self.assertEqual(run("ar-validate", self.dir, f)[0], 0, f.name)
        out = run("ar-code", self.dir)
        self.assertEqual(out[0], 0, out[1])
        self.assertIn("with_repo=2", out[1])
        claims = arlib.load_jsonl(code / "paper_code.jsonl")
        self.assertEqual(sorted(str(c["claim_id"]) for c in claims), ["1", "PC2-1"])  # colliding ids renamed
        self.assertEqual(len(arlib.load_jsonl(code / "code_records.jsonl")), 3)
        report = (code / "code_report.md").read_text(encoding="utf-8")
        self.assertIn("With a repository: 2 of 3", report)
        self.assertIn("Code promised but absent or empty: 1 (b2021x)", report)
        self.assertIn("weights (1)", report)
        self.assertIn("train.py#L10-L12", report)


class CodeLinksInReview(ReviewCase):
    PERMA = "https://github.com/o/deep/blob/" + "a" * 40 + "/train.py#L10-L12"
    # the review fixtures of test_scripts.TestReview, without inheriting its tests
    link = test_scripts.TestReview.link
    write_review = test_scripts.TestReview.write_review
    good_text = test_scripts.TestReview.good_text

    def setUp(self):
        super().setUp()
        self.review["review_sections"] = [
            {"id": "s0", "heading": "Summary"},
            {"id": "s1", "heading": "Body"},
            {"id": "s2", "heading": "References"},
        ]
        self.save_review()
        test_scripts.build_corpus(self)
        run("ar-citemap", self.dir)
        self.cmap = arlib.load_citemap(self.dir)
        write_jsonl(
            self.dir / "4-checks" / "code" / "paper_code.jsonl",
            [
                {
                    "claim_id": "PC1-01",
                    "paper_key": "smith2021deep",
                    "claim_text": "L1 loss",
                    "verdict": "differs",
                    "code_permalink": self.PERMA,
                },
                {
                    "claim_id": "PC1-02",
                    "paper_key": "jones2020fast",
                    "claim_text": "x",
                    "verdict": "conforms",
                    "code_permalink": "https://github.com/o/fast/blob/" + "b" * 40 + "/m.py#L1",
                },
            ],
        )

    def check(self, extra=""):
        self.write_review(self.good_text().replace("<!-- section: s2 -->", extra + "\n\n<!-- section: s2 -->"))
        return run("ar-check-review", self.dir)

    def test_cited_paper_with_a_difference_needs_a_code_link(self):
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("smith2021deep is cited and has `differs` verdicts", out)
        self.assertNotIn("jones2020fast is cited", out)  # conforms only: nothing required
        code, out = self.check(f"Reviewer: the code uses an L2 loss ([train.py L10–12]({self.PERMA})).")
        self.assertEqual(code, 0, out)
        self.assertIn("links to code: 1", out)

    def test_left_out_line_in_lead_notes_is_accepted(self):
        (self.dir / "5-final" / "lead_notes.md").write_text(
            "## Lead reviewer\n\ncode-difference left out: smith2021deep — batch size only\n", encoding="utf-8"
        )
        self.assertEqual(self.check()[0], 0)

    def test_code_links_must_be_pinned_and_known(self):
        code, out = self.check(
            f"Reviewer: see ([a](https://github.com/o/deep/blob/main/train.py#L1)) and "
            f"([b](https://github.com/o/deep/blob/{'c' * 40}/x.py#L2)) and ([c]({self.PERMA}))."
        )
        self.assertEqual(code, 1, out)
        self.assertIn("not pinned at a commit", out)
        self.assertIn("not found in paper_code.jsonl", out)


class CatalogueRepositories(ReviewCase):
    def test_code_column_with_stars(self):
        write_jsonl(
            self.dir / "2-merged" / "corpus.jsonl",
            [
                rec("a2021x", "A", code={"url": "https://github.com/o/a-repo.git", "seen_at": "pdf"}),
                rec("b2021x", "B", code={"url": "https://github.com/o/b", "seen_at": "pdf"}),
                rec("c2021x", "C"),
            ],
        )
        run("ar-citemap", self.dir)
        run("ar-catalogue", self.dir)
        cat = (self.dir / "5-final" / "catalogue.md").read_text(encoding="utf-8")
        self.assertIn("| Code |", cat)
        self.assertIn("[o/a-repo](https://github.com/o/a-repo.git)", cat)
        self.assertIn("not yet checked by the code audit", cat)
        self.assertNotIn("★", cat)
        # the code audit's record wins over the discovery record, with its stars
        write_jsonl(
            self.dir / "4-checks" / "code" / "code_records.jsonl",
            [
                {"key": "b2021x", "code": {"url": "https://github.com/o/b", "stars": 1234, "stars_at": "2026-11-16"}},
                {"key": "c2021x", "code": {"url": None}},
            ],
        )
        run("ar-catalogue", self.dir)
        cat = (self.dir / "5-final" / "catalogue.md").read_text(encoding="utf-8")
        self.assertIn("[o/b](https://github.com/o/b) ★ 1,234", cat)
        self.assertIn("★ = GitHub stars on 2026-11-16", cat)
        self.assertIn("(checked by the code audit)", cat)
        rows = [ln for ln in cat.splitlines() if ln.startswith("| [")]
        self.assertTrue(all(ln.count("|") == rows[0].count("|") for ln in rows))
        self.assertTrue(any(ln.rstrip().endswith("| — |") for ln in rows))

    def test_edition_renders_repository_links_safely(self):
        import sys

        sys.path.insert(0, str(PLUGIN / "lib"))
        from edition import render

        html = render.cell_html("[o/b](https://github.com/o/b) ★ 12 <script>")
        self.assertIn('<a class="repo" href="https://github.com/o/b" target="_blank" rel="noopener">o/b</a>', html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<a", render.cell_html("[x](javascript:alert(1))"))


class AutonomousMode(ReviewCase):
    def test_auto_approval_only_in_autonomous_mode(self):
        run("ar-state", self.dir, "init")
        code, out = run("ar-state", self.dir, "checkpoint", "1", "approve", "--auto")
        self.assertEqual(code, 1)
        self.assertIn('needs review.json "autonomy": "autonomous"', out)
        self.assertEqual(self.state()["checkpoints"]["1"]["status"], "pending")
        self.review["autonomy"] = "autonomous"
        self.save_review()
        code, out = run("ar-state", self.dir, "checkpoint", "1", "approve", "--auto", "--note", "self-checked")
        self.assertEqual(code, 0, out)
        cp = self.state()["checkpoints"]["1"]
        self.assertEqual((cp["status"], cp["by"]), ("approved", "autonomous"))
        self.assertIn("1 approved (autonomous)", run("ar-state", self.dir, "show")[1])
        self.assertEqual(run("ar-state", self.dir, "require", "1")[0], 0)

    def test_template_and_skills_describe_the_mode(self):
        review = json.loads((PLUGIN / "templates" / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(review["autonomy"], "interactive")  # never the default
        new = (PLUGIN / "skills" / "new" / "SKILL.md").read_text(encoding="utf-8")
        run_skill = (PLUGIN / "skills" / "run" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--autonomous", new)
        self.assertIn("checkpoint 1 approve --auto", new)
        self.assertIn("## Autonomous mode", run_skill)
        self.assertIn("never call AskUserQuestion", run_skill)


class MergedCommands(unittest.TestCase):
    """The code audit and the edition are phases of /run (3b and 7), not commands of their own."""

    def test_skills_are_gone_and_run_holds_their_steps(self):
        skills = sorted(d.name for d in (PLUGIN / "skills").iterdir() if d.is_dir())
        self.assertEqual(skills, ["add-pdfs", "new", "run", "share", "status"])
        phases = (PLUGIN / "skills" / "run" / "phases.md").read_text(encoding="utf-8")
        for needle in (
            "`code-finder` agent",
            "`repo-auditor` agent",
            "`paper-code-checker` agent",
            "ar-code",
            "key_points.json",
            "figure-designer",
            "ar-edition",
            "--refresh",
        ):
            self.assertIn(needle, phases)
        run_skill = (PLUGIN / "skills" / "run" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("3b [keys...]", run_skill)
        self.assertIn("7 [--refresh]", run_skill)

    def test_no_reference_to_the_old_commands(self):
        roots = [PLUGIN, PLUGIN.parent.parent / "README.md"]
        files = [
            f
            for r in roots
            for f in ([r] if r.is_file() else r.rglob("*"))
            if f.is_file() and f.suffix in (".md", ".py", ".json", ".js", "") and "tests" not in f.parts
        ]
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for old in ("/agentic-review:edition", "/agentic-review:code-audit"):
                for line in text.splitlines():
                    if old in line:
                        self.assertIn("then `" + old + "`", line, f"{f}: {line}")


if __name__ == "__main__":
    unittest.main()
