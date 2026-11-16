"""Test for bin/ar-leftovers. Standard library only."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "ar-leftovers"


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class LeftoversTest(unittest.TestCase):
    def test_drops_corpus_matches_and_repeats(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "review.json").write_text("{}")
            write_jsonl(
                d / "2-merged" / "corpus.jsonl",
                [
                    {"key": "smith2020deep", "title": "Deep Things", "doi": "10.1000/abc", "arxiv_id": None},
                    {"key": "lee2021fast", "title": "Fast: Other Things!", "doi": None, "arxiv_id": "2101.00001"},
                ],
            )
            write_jsonl(
                d / "1-discovery" / "citation_candidates.jsonl",
                [
                    {"title": "Unrelated", "doi": "10.1000/ABC"},  # same DOI, other case
                    {"title": "fast other things", "doi": None},  # same normalised title
                    {"title": "Via arXiv DOI", "doi": "10.48550/arXiv.2101.00001"},
                    {"title": "New Paper", "doi": "10.2000/new"},
                    {"title": "New Paper (dup)", "doi": "10.2000/new"},  # repeated candidate
                    {"title": "Another new one", "doi": None},
                ],
            )
            out = subprocess.run([sys.executable, str(BIN), str(d)], capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            rows = [json.loads(ln) for ln in (d / "2-merged" / "chase_leftovers.jsonl").read_text().splitlines() if ln]
            self.assertEqual([r["title"] for r in rows], ["New Paper", "Another new one"])

    def test_missing_input_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "review.json").write_text("{}")
            out = subprocess.run([sys.executable, str(BIN), tmp], capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 1)


if __name__ == "__main__":
    unittest.main()
