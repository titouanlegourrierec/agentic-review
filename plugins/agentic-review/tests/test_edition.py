"""Unit tests for ar-edition and lib/edition (standard library only, no network, no Zotero).

Run: python3 -m unittest discover -s <plugin>/tests -v
Each test builds a small synthetic review in a temporary directory. Markdown is rendered by the built-in renderer
(AR_EDITION_MARKDOWN=builtin) so the tests do not depend on pandoc; one test compares it with pandoc when pandoc is
installed. The live Zotero path runs against a local stub server.
"""

import html
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import zipfile
from pathlib import Path
from typing import ClassVar

PLUGIN = Path(__file__).resolve().parent.parent
BIN = PLUGIN / "bin"
sys.path.insert(0, str(PLUGIN / "lib"))
from edition import markdown, page, zlinks

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", AR_EDITION_MARKDOWN="builtin")

REVIEW_MD = """# Test review: a synthetic example

2026-11-01 · test

<!-- section: s0 -->
## Summary

Learned priors gain 1.5 dB on raw data ([Smith et al., 2021](https://doi.org/10.1000/a)). F1 is the main family.

<!-- section: s1 -->
## Methods

### F1 Learned priors

The prior of [Old Label, 2020](https://doi.org/10.1000/b) reports 30.5 dB PSNR. An adjacent paper is
[Jones, 2022](https://arxiv.org/abs/2201.00001).

| Claim | Evidence | Verdict |
|---|---|---|
| Priors help | [Smith et al., 2021](https://doi.org/10.1000/a) | Supported, two studies |
| Bigger is better | none | Contested |

- [ ] Report seeds.
- [x] Release code.

<!-- section: s2 -->
## Methodological rigor

R1 scores are low for most papers.

<!-- section: s3 -->
## References

### Core

- [Smith et al., 2021](https://doi.org/10.1000/a) — Paper A. Journal X, 2021.
- [Old Label, 2020](https://doi.org/10.1000/b): Paper B.

### Background

- [Jones, 2022](https://arxiv.org/abs/2201.00001) — Paper C.
"""

CITEMAP = [
    ("smith2021a", "Smith et al., 2021", "https://doi.org/10.1000/a", "corpus", "core", "F1", "2021", "Paper A"),
    ("brown2020b", "Brown and Lee, 2020", "https://doi.org/10.1000/b", "corpus", "core", "F1", "2020", "Paper B"),
    ("jones2022c", "Jones, 2022", "https://arxiv.org/abs/2201.00001", "omission", "adjacent", "A", "2022", "Paper C"),
]

CATALOGUE = """# Paper catalogue

All 3 catalogued papers.

Families: F1 Learned priors · A Adjacent.

## Core (2)

| Paper | Year | Title | Family | Task |
| --- | --- | --- | --- | --- |
| [Brown and Lee, 2020](https://doi.org/10.1000/b) | 2020 | Paper B | F1 | reconstruction |
| [Smith et al., 2021](https://doi.org/10.1000/a) | 2021 | Paper A | F1 | reconstruction |

## Adjacent (1)

| Paper | Year | Title | Family | Task |
| --- | --- | --- | --- | --- |
| [Jones, 2022](https://arxiv.org/abs/2201.00001) † | 2022 | Paper C | A | segmentation |
"""

RIGOR = """# Rigor scores

1 paper scored on 1 criterion.

| Code | Criterion | Scoring |
| --- | --- | --- |
| R1 | Data realism | 2 raw; 1 emulated; 0 simulated |

| Paper | Read | R1 | Total |
| --- | --- | --- | --- |
| [Smith et al., 2021](https://doi.org/10.1000/a) | full text | 2 | 2/2 |
"""

SNAPSHOT = {
    "ITEMAAAA": {
        "title": "Paper A",
        "doi": "10.1000/a",
        "url": "",
        "collection": "Test collection",
        "atts": [
            {
                "key": "ATTAAAAA",
                "anns": [
                    {
                        "key": "ANNAAAAA",
                        "colour": "green",
                        "type": "highlight",
                        "page_index": 2,
                        "page_label": "3",
                        "sort": "00002",
                        "text": "a gain of 1.5 dB on raw data",
                        "comment": "[Review › Summary] headline gain",
                        "rects": [],
                        "tags": [],
                    },
                    {
                        "key": "ANNBBBBB",
                        "colour": "yellow",
                        "type": "highlight",
                        "page_index": 0,
                        "page_label": "1",
                        "sort": "00000",
                        "text": "we propose a learned prior",
                        "comment": "[Review › Taxonomy] design",
                        "rects": [],
                        "tags": [],
                    },
                ],
            }
        ],
    },
    "ITEMBBBB": {"title": "Paper B", "doi": "10.1000/b", "url": "", "collection": "Sub", "atts": []},
}


def must(m):
    """A regex match the test expects to exist (fails clearly, and narrows the type)."""
    assert m is not None, "expected text not found"
    return m


def run(*args, env=None):
    p = subprocess.run(
        [sys.executable, str(BIN / "ar-edition"), *map(str, args)],
        capture_output=True,
        text=True,
        env=env or ENV,
        timeout=120,
    )
    return p.returncode, p.stdout + p.stderr


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def data_of(page_html):
    return json.loads(
        must(re.search(r'<script id="data" type="application/json">(.*?)</script>', page_html, re.S)).group(1)
    )


def cite_anchors(page_html):
    body = page_html[: page_html.index('<script id="data"')]
    return [
        (html.unescape(re.sub(r"<[^>]+>", "", m.group(3))), html.unescape(m.group(2)))
        for m in re.finditer(
            r'<a (?:id="[^"]*" )?class="(cite[^"]*)"(?: data-z="1")? href="([^"]*)"[^>]*>(.*?)</a>', body, re.S
        )
    ]


class EditionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ar-edition-test-"))
        self.dir = self.tmp / "my review"  # a space on purpose
        fin = self.dir / "5-final"
        fin.mkdir(parents=True)
        self.review = json.loads((PLUGIN / "templates" / "review.json").read_text(encoding="utf-8"))
        self.review["zotero"].update({"enabled": False, "collection": "Test collection", "tag": "test-tag"})
        self.review["edition"] = {
            "title": "Test review",
            "port": 48000,
            "storage_key": "test-store",
            "glossary": [{"term": "PSNR", "definition": "Peak signal-to-noise ratio."}],
        }
        self.review["taxonomy"] = {"F1": "Learned priors", "A": "Adjacent"}
        self.review["rigor_rubric"] = [
            {"id": "R1", "name": "Data realism", "scoring": "2 raw; 1 emulated; 0 simulated"}
        ]
        self.save_review()
        (fin / "review.md").write_text(REVIEW_MD, encoding="utf-8")
        self.write_citemap(CITEMAP)
        (fin / "catalogue.md").write_text(CATALOGUE, encoding="utf-8")
        (fin / "rigor_table.md").write_text(RIGOR, encoding="utf-8")
        (fin / "counts.json").write_text(json.dumps({"records": {"all": 3}}), encoding="utf-8")
        (fin / "references.bib").write_text(
            "@article{smith2021a,\n  title = {Paper A}\n}\n\n@article{brown2020b,\n  title = {Paper B}\n}\n",
            encoding="utf-8",
        )
        self.key_points(
            {
                "_subtitle": "What learned priors add",
                "_tiles": [
                    {"value": "3", "text": "papers catalogued"},
                    {"value": "1.5 dB", "text": "gain on raw data"},
                ],
                "Summary": ["Priors gain 1.5 dB on raw data."],
                "Methods": ["One paper reports 30.5 dB."],
            }
        )
        write_jsonl(
            self.dir / "2-merged" / "corpus.jsonl",
            [
                {
                    "key": "smith2021a",
                    "title": "Paper A",
                    "venue": "Journal X &amp; Y",
                    "year": 2021,
                    "one_line_claim": "A learned prior beats compressed sensing.",
                },
                {"key": "brown2020b", "title": "Paper B", "venue": "Conf Z", "year": 2020, "one_line_claim": None},
            ],
        )
        write_jsonl(
            self.dir / "4-checks" / "omissions_checked.jsonl",
            [{"key": "jones2022c", "title": "Paper C", "venue": "arXiv", "year": 2022}],
        )
        write_jsonl(
            self.dir / "4-checks" / "claims_check.jsonl",
            [
                {
                    "claim_id": "C1",
                    "claim_text": "Smith gains 1.5 dB.",
                    "paper_key": "smith2021a",
                    "verdict": "supported",
                    "evidence": "Table 2: 1.5 dB",
                },
                {
                    "claim_id": "C2",
                    "claim_text": "Brown reports 30.5 dB.",
                    "paper_key": "brown2020b",
                    "verdict": "partially-supported",
                    "evidence": "Table 1: 30.4 dB",
                },
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save_review(self):
        (self.dir / "review.json").write_text(json.dumps(self.review), encoding="utf-8")

    def write_citemap(self, rows):
        head = "key\tlabel\turl\tsource\ttier\tfamily\tcite_year\ttitle"
        (self.dir / "5-final" / "citation_map.tsv").write_text(
            head + "\n" + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8"
        )

    def key_points(self, kp):
        (self.dir / "5-final" / "key_points.json").write_text(json.dumps(kp), encoding="utf-8")

    def page(self):
        return (self.dir / "7-edition" / "index.html").read_text(encoding="utf-8")

    def zotero_setup(self, snapshot=None, results=True):
        self.review["zotero"]["enabled"] = True
        self.save_review()
        snap = self.tmp / "snapshot.json"
        snap.write_text(json.dumps(snapshot or SNAPSHOT), encoding="utf-8")
        if results:
            (self.dir / "5-final" / "annotation_results.json").write_text(
                json.dumps(
                    {
                        "results": [
                            {"key": "smith2021a", "item_key": "ITEMAAAA"},
                            {"key": "brown2020b", "item_key": "ITEMBBBB"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
        return snap


# --------------------------------------------------------------------------- without Zotero


class TestWebEdition(EditionCase):
    def test_page_without_zotero(self):
        code, out = run(self.dir)  # zotero.enabled is false
        self.assertEqual(code, 0, out)
        self.assertIn("mode web", out)
        self.assertIn("relabelled 2 (2 in review.md)", out)
        self.assertIn("key-point boxes 2", out)
        self.assertIn("BibTeX entries 2 of 3", out)
        h = self.page()
        self.assertNotIn('href="zotero://', h)
        urls = {r[2]: r[1] for r in CITEMAP}
        anchors = cite_anchors(h)
        self.assertTrue(anchors)
        for label, href in anchors:
            self.assertIn(href, urls)  # every citation opens its citation-map link
            self.assertEqual(label, urls[href])  # and shows the map's current label
        self.assertNotIn("Old Label", h)
        d = data_of(h)
        self.assertEqual((d["store"], d["bib"], d["mode"]), ("test-store", "test-store.bib", "web"))
        smith = d["papers"]["smith2021a"]
        self.assertEqual(smith["v"], "Journal X & Y")
        self.assertEqual(smith["c"], "A learned prior beats compressed sensing.")
        self.assertEqual([(c["l"], c["v"]) for c in smith["cc"]], [("Supported", "v-good")])
        self.assertEqual(d["papers"]["brown2020b"]["cc"][0]["l"], "Partly supported")
        self.assertEqual(d["papers"]["jones2022c"]["cc"], [])
        terms = [g["t"] for g in d["gloss"]]
        self.assertEqual(terms, ["PSNR", "F1 · Learned priors", "R1 · Data realism"])  # no one-letter "A"
        self.assertIn('localStorage.getItem("test-store-theme")', h)
        self.assertIn('<p class="subtitle">What learned priors add</p>', h)
        self.assertEqual(h.count('class="tile"'), 2)
        self.assertEqual(h.count('class="keypoints"'), 2)
        self.assertIn("(verdicts from section 1)", h)
        self.assertEqual(len(re.findall(r'<li><a href="#claim-', h)), 2)
        self.assertIn('<h3 class="refgroup">Core</h3>', h)
        self.assertIn('<h3 class="refgroup">Background</h3>', h)
        self.assertIn('<span class="rlabel">Brown and Lee, 2020</span> — Paper B.', h)
        self.assertIn('<h2 id="appendix-a"><span class="secnum">A</span> Paper catalogue</h2>', h)
        self.assertIn('<h2 id="appendix-b"><span class="secnum">B</span> Rigor rubric and scores</h2>', h)
        self.assertNotIn('class="clear-opened"', h)
        self.assertNotIn('class="motif"', h)
        self.assertIn('<html lang="en">', h)
        self.assertEqual(h.count("<script"), 4)
        launch = (self.dir / "7-edition" / "open-in-chrome.command").read_text(encoding="utf-8")
        self.assertIn("PORT=48000", launch)
        self.assertIn("Test review", launch)
        self.assertNotIn("{", launch.replace("${", "").replace("{ ", ""))
        self.assertTrue(os.access(self.dir / "7-edition" / "open-in-browser.sh", os.X_OK))
        readme = (self.dir / "7-edition" / "README.md").read_text(encoding="utf-8")
        self.assertIn("http://localhost:48000", readme)
        self.assertNotIn("{LINKS}", readme)

    def test_absent_optional_inputs_render_nothing(self):
        for f in ("key_points.json", "catalogue.md", "rigor_table.md", "references.bib", "counts.json"):
            (self.dir / "5-final" / f).unlink()
        shutil.rmtree(self.dir / "4-checks")
        code, out = run(self.dir, "--no-zotero")
        self.assertEqual(code, 0, out)
        h = self.page()
        body = h[: h.index('<script id="data"')]
        for absent in (
            'class="subtitle"',
            'class="tiles"',
            'class="keypoints"',
            "Paper catalogue",
            "Rigor rubric and scores",
            'class="bibdl"',
            'class="chip bib"',
        ):
            self.assertNotIn(absent, body)
        self.assertNotRegex(body, r"<h2[^>]*>[^<]*</h2>\s*<h2")
        self.assertEqual(data_of(h)["papers"]["smith2021a"]["cc"], [])

    def test_refused_key_point_and_tile(self):
        self.key_points({"Methods": ["Gains reach 99.9 dB."], "_tiles": [{"value": "77", "text": "papers"}]})
        code, out = run(self.dir)
        self.assertEqual(code, 1, out)
        self.assertIn('refused: "99.9" is not in section "Methods"', out)
        self.assertIn('refused: tile "77"', out)
        self.assertFalse((self.dir / "7-edition" / "index.html").exists())

    def test_missing_review_and_usage(self):
        code, out = run(self.dir, "--no-zotero", "--snapshot", "x.json")
        self.assertEqual(code, 2, out)
        (self.dir / "5-final" / "review.md").unlink()
        code, out = run(self.dir)
        self.assertEqual(code, 1, out)
        self.assertIn("missing 5-final/review.md", out)

    def test_out_option(self):
        out_file = self.tmp / "elsewhere" / "page.html"
        code, out = run(self.dir, "--out", out_file)
        self.assertEqual(code, 0, out)
        self.assertTrue(out_file.exists())
        self.assertFalse((self.dir / "7-edition").exists())  # launchers only next to an index.html


# --------------------------------------------------------------------------- with a Zotero snapshot


class TestZoteroEdition(EditionCase):
    def test_snapshot_links(self):
        snap = self.zotero_setup()
        code, out = run(self.dir, "--snapshot", snap)
        self.assertEqual(code, 0, out)
        self.assertIn("mode zotero", out)
        kinds = eval(must(re.search(r"citations (\{[^}]*\})", out)).group(1), {})
        self.assertEqual(kinds, {"annotation": 1, "pdf": 1, "doi": 2})
        h = self.page()
        anchors = {href: label for label, href in cite_anchors(h)}
        self.assertIn("zotero://open-pdf/library/items/ATTAAAAA?page=3&annotation=ANNAAAAA", anchors)
        self.assertIn("zotero://open-pdf/library/items/ATTAAAAA", anchors)  # not confident: the PDF
        self.assertIn("zotero://select/library/items/ITEMBBBB", anchors)  # in Zotero without a PDF
        self.assertIn("https://arxiv.org/abs/2201.00001", anchors)  # not in Zotero
        self.assertIn('class="cite t-annotation c-green"', h)
        d = data_of(h)
        self.assertEqual(d["anns"]["ANNAAAAA"]["c"], "green")
        self.assertEqual(d["anns"]["ANNAAAAA"]["m"], "headline gain")
        self.assertEqual(d["mode"], "zotero")
        self.assertIn('class="clear-opened"', h)
        self.assertIn('<a class="chip z" href="zotero://open-pdf/library/items/ATTAAAAA">Zotero</a>', h)
        self.assertEqual(page.unresolved_zotero_links(h, SNAPSHOT), [])
        self.assertIn("(2 by annotation_results.json)", out)
        self.assertFalse((self.dir / "7-edition" / "zotero_snapshot.json").exists())

    def test_doi_matching_without_annotation_results(self):
        snap = self.zotero_setup(results=False)
        code, out = run(self.dir, "--snapshot", snap)
        self.assertEqual(code, 0, out)
        self.assertIn("2 papers matched to Zotero items (2 by DOI or arXiv id)", out)

    def test_pilot_mapping(self):
        snap = self.zotero_setup(results=False)
        self.review["edition"]["pilot"] = {"Jones, 2022": "ITEMAAAA", "nobody, 1900": "ITEMBBBB"}
        self.save_review()
        code, out = run(self.dir, "--snapshot", snap)
        self.assertEqual(code, 0, out)
        self.assertIn("edition.pilot: nobody, 1900 is neither a label nor a key", out)
        self.assertIn("3 papers matched to Zotero items (2 by DOI or arXiv id, 1 by edition.pilot)", out)

    def test_unresolved_link_exits_1(self):
        bad = json.loads(json.dumps(SNAPSHOT))
        bad["ITEMAAAA"]["atts"][0]["key"] = "not-a-key"
        snap = self.zotero_setup(bad)
        code, out = run(self.dir, "--snapshot", snap)
        self.assertEqual(code, 1, out)
        self.assertIn("do not resolve in the snapshot", out)
        self.assertEqual(
            page.unresolved_zotero_links(
                '<a href="zotero://open-pdf/library/items/ATTAAAAA?page=1&amp;annotation=ZZZZZZZZ">x</a>'
                '<script id="data">{"z":"zotero://select/library/items/NOPENOPE"}</script><script>x</script>',
                SNAPSHOT,
            ),
            [
                "zotero://open-pdf/library/items/ATTAAAAA?page=1&annotation=ZZZZZZZZ",
                "zotero://select/library/items/NOPENOPE",
            ],
        )

    def test_live_zotero_through_stub(self):
        api = "/api/users/0"

        def item(k, doi):
            return {"key": k, "data": {"itemType": "journalArticle", "title": f"Paper {k}", "DOI": doi}}

        _Stub.routes = {
            f"{api}/collections": [{"key": "COLL0001", "data": {"name": "Test collection", "parentCollection": False}}],
            f"{api}/collections/COLL0001/collections": [{"key": "COLL0002", "data": {"name": "Sub"}}],
            f"{api}/collections/COLL0002/collections": [],
            f"{api}/collections/COLL0001/items/top": [item("ITEMAAAA", "10.1000/A")],
            f"{api}/collections/COLL0002/items/top": [item("ITEMBBBB", "10.1000/b")],
            f"{api}/items?itemType=annotation": [
                {
                    "key": "ANNAAAAA",
                    "data": {
                        "parentItem": "ATTAAAAA",
                        "annotationType": "highlight",
                        "annotationText": "a gain of 1.5 dB",
                        "annotationComment": "[Review › Summary] headline gain",
                        "annotationColor": "#5fb236",
                        "annotationPosition": json.dumps({"pageIndex": 2, "rects": []}),
                        "annotationSortIndex": "1",
                    },
                }
            ],
            f"{api}/items/ITEMAAAA/children": [
                {"key": "ATTAAAAA", "data": {"itemType": "attachment", "contentType": "application/pdf"}}
            ],
            f"{api}/items/ITEMBBBB/children": [],
        }
        self.zotero_setup()
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Stub)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        env = dict(ENV, AR_ZOTERO_API=f"http://127.0.0.1:{srv.server_port}{api}")
        try:
            code, out = run(self.dir, env=env)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(code, 0, out)
        snap = json.loads((self.dir / "7-edition" / "zotero_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(snap), ["ITEMAAAA", "ITEMBBBB"])  # sub-collection included
        self.assertEqual(snap["ITEMBBBB"]["collection"], "Sub")
        self.assertEqual(snap["ITEMAAAA"]["atts"][0]["anns"][0]["colour"], "green")
        self.assertIn("zotero://open-pdf/library/items/ATTAAAAA?page=3&amp;annotation=ANNAAAAA", self.page())
        code, out = run(self.dir, env=env)  # server gone: snapshot reused
        self.assertEqual(code, 0, out)
        self.assertIn("reused", out)
        code, out = run(self.dir, "--refresh", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("cannot read Zotero", out)


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


# --------------------------------------------------------------------------- hostile content

HOSTILE = "</script><script>alert(1)</script> \"quoted\" 'single' <img src=x onerror=alert(1)>"


class TestEscaping(EditionCase):
    def assert_inert(self, h):
        blocks = re.findall(r'<script id="(?:data|bib)" type="application/json">(.*?)</script>', h, re.S)
        self.assertEqual(len(blocks), 2)
        for b in blocks:  # nothing can end or confuse a JSON block
            self.assertNotRegex(b.lower(), r"</|<!--")
        outside = re.sub(r'(<script id="(?:data|bib)" type="application/json">).*?(</script>)', r"\1\2", h, flags=re.S)
        self.assertNotIn("<script>alert", outside)
        self.assertNotIn("<img src=x", outside)
        self.assertEqual(h.count("</script>"), 4)  # theme, data, bib, page script
        for href in re.findall(r'(?:href|src)="([^"]*)"', h):
            self.assertFalse(html.unescape(href).strip().lower().startswith(("javascript:", "data:")), href)
        data_of(h)  # the JSON blocks still parse
        json.loads(must(re.search(r'<script id="bib" type="application/json">(.*?)</script>', h, re.S)).group(1))

    def hostile_inputs(self):
        rows = [list(r) for r in CITEMAP]
        rows[0][7] = HOSTILE  # title of a cited paper
        rows[2][2] = "javascript:alert(2)"  # link of a cited paper
        self.write_citemap([tuple(r) for r in rows])
        write_jsonl(
            self.dir / "2-merged" / "corpus.jsonl",
            [{"key": "smith2021a", "title": HOSTILE, "venue": HOSTILE, "year": 2021, "one_line_claim": HOSTILE}],
        )
        write_jsonl(
            self.dir / "4-checks" / "claims_check.jsonl",
            [
                {
                    "claim_id": "C1",
                    "claim_text": HOSTILE,
                    "paper_key": "smith2021a",
                    "verdict": HOSTILE,
                    "evidence": HOSTILE,
                }
            ],
        )
        md = REVIEW_MD.replace(
            "F1 is the main family.",
            "F1 is the main family. <script>alert(3)</script> [click](javascript:alert(4)) "
            '<a href="javascript:alert(5)" onclick="alert(6)">x</a>',
        )
        md = md.replace("— Paper A. Journal X, 2021.", f"— {HOSTILE}")
        (self.dir / "5-final" / "review.md").write_text(md, encoding="utf-8")
        self.review["edition"]["title"] = "Evil\n</title><script>alert(7)</script> & `rm -rf ~` $HOME %PATH%"
        self.review["edition"]["glossary"].append({"term": "Bad", "pattern": "(unclosed", "definition": HOSTILE})
        self.save_review()
        self.key_points({"Summary": ["<b>1.5</b> dB " + HOSTILE.replace("1", "")]})

    def test_hostile_text_without_zotero(self):
        self.hostile_inputs()
        code, out = run(self.dir)
        self.assertEqual(code, 0, out)
        h = self.page()
        self.assert_inert(h)
        d = data_of(h)
        self.assertEqual(d["papers"]["smith2021a"]["t"], re.sub(r"<[^>]+>", "", HOSTILE).strip())
        self.assertEqual(d["papers"]["jones2022c"]["u"], "#")
        self.assertIn("&lt;script&gt;alert(3)&lt;/script&gt;", h)
        self.assertIn("<title>Evil\n&lt;/title&gt;&lt;script&gt;alert(7)&lt;/script&gt;", h)
        self.assertIn('glossary pattern of "Bad" not usable', out)
        for name in ("open-in-chrome.command", "open-in-browser.sh", "open-in-browser.bat"):
            for line in (self.dir / "7-edition" / name).read_text(encoding="utf-8").splitlines():
                if "Evil" in line or "rm -rf" in line:
                    self.assertTrue(line.startswith(("#", "rem")), line)
                    self.assertNotRegex(line, r"[`$%<>&]")

    def test_hostile_snapshot(self):
        self.hostile_inputs()
        bad = json.loads(json.dumps(SNAPSHOT))
        ann = bad["ITEMAAAA"]["atts"][0]["anns"][0]
        ann["comment"] = "[Review › Summary] " + HOSTILE
        ann["text"] = HOSTILE + " 1.5"
        ann["colour"] = '"><script>alert(8)</script>'
        snap = self.zotero_setup(bad)
        code, out = run(self.dir, "--snapshot", snap)
        self.assertEqual(code, 0, out)
        h = self.page()
        self.assert_inert(h)
        d = data_of(h)
        self.assertEqual(d["anns"]["ANNAAAAA"]["c"], "other")
        self.assertIn("<\\/script>", h)  # '</' escaped inside the JSON block


# --------------------------------------------------------------------------- the built-in markdown renderer


class TestMarkdown(unittest.TestCase):
    def test_shapes(self):
        r = markdown.render
        self.assertEqual(
            r("## Héllo – World: (F5) `x`\n\n## Héllo – World: (F5) `x`\n"),
            '<h2 id="héllo--world-f5-x">Héllo – World: (F5) <code>x</code></h2>\n'
            '<h2 id="héllo--world-f5-x-1">Héllo – World: (F5) <code>x</code></h2>\n',
        )
        self.assertEqual(
            r('*a*b* snake_case_word **bold**text a < b & "c"'),
            '<p><em>a</em>b* snake_case_word <strong>bold</strong>text a &lt; b &amp; "c"</p>\n',
        )
        self.assertEqual(
            r("see https://example.org/x/repo_name_x). and www.example.org"),
            '<p>see <a href="https://example.org/x/repo_name_x">https://example.org/x/repo_name_x</a>). '
            'and <a href="http://www.example.org">www.example.org</a></p>\n',
        )
        self.assertEqual(
            r("| A | B |\n|:--|--:|\n| a \\| b | [l](cite:3) |\n"),
            '<table>\n<thead>\n<tr>\n<th style="text-align: left;">A</th>\n'
            '<th style="text-align: right;">B</th>\n</tr>\n</thead>\n<tbody>\n<tr>\n'
            '<td style="text-align: left;">a | b</td>\n<td style="text-align: right;">'
            '<a href="cite:3">l</a></td>\n</tr>\n</tbody>\n</table>\n',
        )
        self.assertEqual(
            r("- [ ] one\n- [x] two\n"),
            '<ul class="task-list">\n<li><label><input type="checkbox" />one</label></li>\n'
            '<li><label><input type="checkbox" checked="" />two</label></li>\n</ul>\n',
        )
        self.assertEqual(
            r("1. a\n   - b\n2. c\n"), '<ol type="1">\n<li>a\n<ul>\n<li>b</li>\n</ul></li>\n<li>c</li>\n</ol>\n'
        )
        self.assertEqual(r("- a\n\n- b\n"), "<ul>\n<li><p>a</p></li>\n<li><p>b</p></li>\n</ul>\n")
        self.assertEqual(
            r("```\nx 'y' \"z\" <w>\n```\n"), "<pre><code>x &#39;y&#39; &quot;z&quot; &lt;w&gt;</code></pre>\n"
        )
        self.assertEqual(
            r("a  \nb\nc\n\n> q\n\n---\n"), "<p>a<br />\nb c</p>\n<blockquote>\n<p>q</p>\n</blockquote>\n<hr />\n"
        )

    def test_sanitize(self):
        s = markdown.sanitize(
            '<p>x <script>alert(1)</script> <a href="javascript:alert(1)" onclick="x()">y</a> '
            '<a href="cite:3">z</a> <a href="rig:x">w</a> <img src="data:x" alt="q" /><!-- c --> '
            '<a href="https://ok/?a=1&amp;b=2">o</a></p>',
            ("cite",),
        )
        self.assertEqual(
            s,
            '<p>x &lt;script&gt;alert(1)&lt;/script&gt; <a>y</a> <a href="cite:3">z</a> <a>w</a> '
            '<img alt="q" /> <a href="https://ok/?a=1&amp;b=2">o</a></p>',
        )
        self.assertEqual(markdown.safe_url(" JavaScript:alert(1)"), "#")
        self.assertEqual(
            markdown.safe_url("zotero://select/library/items/ABCDEFGH"), "zotero://select/library/items/ABCDEFGH"
        )

    @unittest.skipUnless(shutil.which("pandoc"), "pandoc not installed")
    def test_same_as_pandoc(self):
        src = (
            REVIEW_MD
            + "\n"
            + CATALOGUE.replace("$", "")
            + "\n"
            + RIGOR
            + (
                "\n1. one\n2. two\n\n3) three\n\n* loose\n\n* list\n\n    code\n\nText *em* __strong__ ~~del~~ "
                "<https://auto.link/x> and a bare https://example.org/a_b_c. end\nline two\\\nline three\n"
            )
        )
        pandoc = subprocess.run(
            ["pandoc", "-f", "gfm", "-t", "html5", "--wrap=none"], input=src, capture_output=True, text=True, check=True
        ).stdout

        def tidy(h):
            return re.sub(r"\n+", "\n", markdown.sanitize(h))  # comments leave blank lines

        self.assertEqual(tidy(markdown.render(src)), tidy(pandoc))


class TestChooser(unittest.TestCase):
    def test_family_regex_and_limit_words(self):
        fam = zlinks.family_regex(["F1", "F10", "A", "B"])
        self.assertEqual(fam.findall("f10 and f1 but not a or b"), ["f10", "f1"])
        self.assertIsNone(zlinks.family_regex(["A", "B"]))
        self.assertEqual(
            zlinks.section_score("Key approaches › F10 learned sampling", "Beyond", "F10 Sampling", fam), 3.0
        )
        self.assertTrue(zlinks.limit_regex().search("only on simulated data"))
        self.assertFalse(zlinks.limit_regex(["caveat"]).search("only on simulated data"))

    def test_highlights_of_another_review_never_count(self):
        def ann(comment, tags):
            return {"comment": comment, "tags": tags}

        ours, other = "rev-a", "rev-b"
        self.assertIsNotNone(zlinks.review_bracket(ann("[Review › Results] x", [ours]), ours))
        self.assertIsNotNone(zlinks.review_bracket(ann("[Results] x", [ours]), ours))
        self.assertIsNone(zlinks.review_bracket(ann("[Review › Results] x", [other]), ours))  # a shared PDF
        self.assertIsNotNone(zlinks.review_bracket(ann("[Review › Results] x", []), ours))  # untagged, older
        self.assertIsNone(zlinks.review_bracket(ann("[Results] x", []), ours))
        self.assertIsNotNone(zlinks.review_bracket(ann("[Review › Results] x", [other]), ""))  # no tag known
        self.assertIsNone(zlinks.review_bracket(ann("plain note", [ours]), ours))

    def test_relabel_by_url(self):
        rows = {page.norm_url(u): [{"key": k, "label": lab, "url": u}] for k, lab, u, *_ in CITEMAP}
        text, n = page.relabel(
            "[Old, 2020](https://doi.org/10.1000/b) [NetName](https://doi.org/10.1000/b) "
            "[Jones, 2022](https://arxiv.org/abs/2201.00001)",
            rows,
            {r[1] for r in CITEMAP},
        )
        self.assertEqual(n, 1)
        self.assertIn("[Brown and Lee, 2020](https://doi.org/10.1000/b)", text)
        self.assertIn("[NetName](https://doi.org/10.1000/b)", text)  # prose links keep their text


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- shareable package (ar-share)

SHARE = PLUGIN / "bin" / "ar-share"


def share(*args):
    p = subprocess.run(
        [sys.executable, str(SHARE), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=120,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    return p.returncode, p.stdout + p.stderr


class TestShare(EditionCase):
    def setUp(self):
        super().setUp()
        snap = self.zotero_setup()
        (self.dir / "7-edition").mkdir(exist_ok=True)
        shutil.copy(snap, self.dir / "7-edition" / "zotero_snapshot.json")
        self.zdir = self.tmp / "Zotero"
        (self.zdir / "storage" / "ATTAAAAA").mkdir(parents=True)
        self.pdf = self.zdir / "storage" / "ATTAAAAA" / "Smith - 2021 - Paper A.pdf"

    def build(self, *args, arxiv=True):
        stamp = b"BT (arXiv:2101.00001v2  [eess.IV]  3 Jan 2021) Tj ET" if arxiv else b"BT (Journal X) Tj ET"
        self.pdf.write_bytes(b"%PDF-1.4\n1 0 obj << >> stream\n" + stamp + b"\nendstream endobj\n%%EOF\n")
        out_zip = self.tmp / "out.zip"
        code, out = share(self.dir, "--zotero-dir", self.zdir, "--out", out_zip, *args)
        return code, out, out_zip

    def test_arxiv_pdf_is_packaged_and_citations_open_it(self):
        code, out, out_zip = self.build()
        self.assertEqual(code, 0, out)
        self.assertIn("PDFs included 1", out)
        with zipfile.ZipFile(out_zip) as z:
            names = z.namelist()
            root = names[0].split("/")[0]
            self.assertEqual(root, "test-store-share")
            self.assertIn(f"{root}/papers/smith2021a.pdf", names)
            self.assertIn(f"{root}/index.html", names)
            self.assertIn(f"{root}/README.md", names)
            h = z.read(f"{root}/index.html").decode("utf-8")
            readme = z.read(f"{root}/README.md").decode("utf-8")
        anchors = {href: label for label, href in cite_anchors(h)}
        self.assertIn("papers/smith2021a.pdf#page=3", anchors)  # the highlight's page
        self.assertIn("papers/smith2021a.pdf", anchors)
        self.assertNotIn("zotero://", h.split("<script", 1)[0])
        self.assertEqual(data_of(h)["mode"], "share")
        self.assertIn('target="_blank" rel="noopener">PDF</a>', h)
        self.assertIn("papers` folder", readme)
        self.assertEqual(data_of(h)["anns"]["ANNAAAAA"]["m"], "headline gain")  # the hover keeps the passage

    def test_viewer_ships_pdfjs_and_this_reviews_highlights(self):
        snap = json.loads(json.dumps(SNAPSHOT))
        anns = snap["ITEMAAAA"]["atts"][0]["anns"]
        anns[0]["rects"] = [[72.0, 600.0, 300.0, 612.0]]
        anns.append(
            {
                "key": "ANNOTHER",
                "colour": "red",
                "type": "highlight",
                "page_index": 1,
                "page_label": "2",
                "sort": "00001",
                "text": "other review",
                "comment": "[Other › Summary] not ours",
                "rects": [[1, 2, 3, 4]],
                "tags": ["another-review"],
            }
        )
        (self.dir / "7-edition" / "zotero_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
        code, out, out_zip = self.build()
        self.assertEqual(code, 0, out)
        with zipfile.ZipFile(out_zip) as z:
            names = set(z.namelist())
            for f in ("viewer.html", "pdfjs/pdf.min.js", "pdfjs/pdf.worker.min.js", "pdfjs/LICENSE"):
                self.assertIn(f"test-store-share/{f}", names)
            viewer = z.read("test-store-share/viewer.html").decode("utf-8")
            launcher = z.read("test-store-share/open-in-chrome.command").decode("utf-8")
        data = json.loads(
            must(re.search(r'<script id="anns" type="application/json">(.*?)</script>', viewer, re.S)).group(1)
        )
        mine = data["smith2021a.pdf"]
        self.assertEqual(mine["ANNAAAAA"]["r"], [[72.0, 600.0, 300.0, 612.0]])
        self.assertEqual(mine["ANNAAAAA"]["m"], "headline gain")
        self.assertEqual(mine["ANNAAAAA"]["p"], 2)
        self.assertNotIn("ANNOTHER", mine)  # another review's highlight
        self.assertNotIn("__ANNS_JSON__", viewer)
        self.assertIn("import * as pdfjsLib from './pdfjs/pdf.min.js'", viewer)
        self.assertIn("PORT=48001", launcher)  # the edition's port + 1

    def test_page_script_switches_to_the_viewer_when_served(self):
        js = (PLUGIN / "lib" / "edition" / "webpage.js").read_text(encoding="utf-8")
        self.assertIn("if (SHARE && /^https?:$/.test(location.protocol))", js)
        self.assertIn("viewer.html?file=", js)

    def test_publisher_pdf_left_out_unless_all(self):
        code, out, out_zip = self.build(arxiv=False)
        self.assertEqual(code, 0, out)
        self.assertIn("PDFs included 0", out)
        self.assertIn("left out (no arXiv stamp", out)
        with zipfile.ZipFile(out_zip) as z:
            h = z.read("test-store-share/index.html").decode("utf-8")
            self.assertFalse(any("/papers/" in n and n.endswith(".pdf") for n in z.namelist()))
        self.assertIn("https://doi.org/10.1000/a", {href: ln for ln, href in cite_anchors(h)})
        code, out, out_zip = self.build("--pdfs", "all", arxiv=False)
        self.assertIn("PDFs included 1", out)

    def test_dry_run_and_missing_snapshot(self):
        self.pdf.write_bytes(b"%PDF-1.4 arXiv:2101.00001v2")
        code, out = share(self.dir, "--zotero-dir", self.zdir, "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("all 1", out)
        self.assertIn("with arXiv's stamp 1", out)
        self.assertFalse(list((self.dir / "7-edition").glob("*.zip")))
        (self.dir / "7-edition" / "zotero_snapshot.json").unlink()
        code, out = share(self.dir, "--zotero-dir", self.zdir)
        self.assertEqual(code, 1)
        self.assertIn("build the Zotero edition first", out)
