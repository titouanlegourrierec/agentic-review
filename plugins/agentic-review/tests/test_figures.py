"""Tests of the figures of the reading edition (lib/edition/figures.py, bin/ar-figures). Standard library only.

Builds on the synthetic review of test_edition.py: its review.md states 1.5 dB and 30.5 dB, cites three papers and
has the headings Summary, Methods, F1 Learned priors, Methodological rigor.
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from test_edition import BIN, ENV, PLUGIN, EditionCase, data_of, run, write_jsonl

sys.path.insert(0, str(PLUGIN / "lib"))
from edition import figures

GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 120">'
    '<rect x="0" y="0" width="200" height="60" rx="6" class="fill-1"/>'
    '<text x="100" y="35" text-anchor="middle" class="on-dark">Learned prior</text>'
    '<line x1="200" y1="30" x2="300" y2="30" class="line-ink2" stroke-width="1" marker-end="url(#fg-arrow)"/>'
    '<a data-key="brown2020b"><rect x="300" y="0" width="200" height="60" class="fill-surface line-ink2"/>'
    '<text x="400" y="35" text-anchor="middle">Brown and Lee</text></a>'
    '<a data-section="Methodological rigor"><text x="560" y="35">rigor</text></a></svg>'
)


def must(m):
    """A regex match the test expects to exist (fails clearly, and narrows the type)."""
    assert m is not None, "expected text not found"
    return m


def figs_run(*args):
    p = subprocess.run(
        [sys.executable, str(BIN / "ar-figures"), *map(str, args)], capture_output=True, text=True, env=ENV, timeout=120
    )
    return p.returncode, p.stdout + p.stderr


def svgs(page_html):
    return re.findall(r"<svg viewBox=.*?</svg>", page_html, re.S)


class FigureCase(EditionCase):
    def setUp(self):
        super().setUp()
        self.figdir = self.dir / "5-final" / "figures"
        write_jsonl(
            self.dir / "2-merged" / "corpus.jsonl",
            [
                {
                    "key": "smith2021a",
                    "title": "Paper A",
                    "venue": "Journal X",
                    "year": 2021,
                    "tier": "core",
                    "family": "F1",
                    "one_line_claim": "A learned prior beats compressed sensing.",
                    "key_results": "31.2 dB",
                },
                {
                    "key": "brown2020b",
                    "title": "Paper B",
                    "venue": "Conf Z",
                    "year": 2020,
                    "tier": "core",
                    "family": "F1",
                },
            ],
        )
        write_jsonl(
            self.dir / "4-checks" / "omissions_checked.jsonl",
            [
                {
                    "key": "jones2022c",
                    "title": "Paper C",
                    "venue": "arXiv",
                    "year": 2022,
                    "tier": "adjacent",
                    "family": "A",
                }
            ],
        )

    def spec(self, *figs):
        self.figdir.mkdir(parents=True, exist_ok=True)
        (self.figdir / "figures.json").write_text(json.dumps({"figures": list(figs)}), encoding="utf-8")

    def dots(self, **kw):
        f = {
            "id": "gain",
            "type": "dots",
            "title": "The headline gain",
            "caption": "One paper, 1.5 dB.",
            "place": {"section": "Summary", "after": "paragraph"},
            "mention": "Figure {n} plots it.",
            "axis": {"label": "PSNR gain (dB)", "signed": True},
            "rows": [{"key": "smith2021a", "values": {"_": [1.5]}, "text": "+1.5 dB on raw data"}],
        }
        f.update(kw)
        return f


class TestPlacement(FigureCase):
    def test_no_figures_json_changes_nothing(self):
        self.assertEqual(run(self.dir)[0], 0)
        before = self.page()
        self.assertNotIn('class="fig"', before)
        self.assertNotIn("--fg-c1", before)
        self.figdir.mkdir()  # a folder without figures.json is the same
        self.assertEqual(run(self.dir)[0], 0)
        self.assertEqual(self.page(), before)

    def test_figures_placed_numbered_and_linked(self):
        (self.figdir).mkdir(parents=True)
        (self.figdir / "concept.svg").write_text(GOOD_SVG, encoding="utf-8")
        self.spec(
            {
                "id": "families",
                "type": "heatmap",
                "title": "Papers by family and year",
                "caption": "All 3 catalogued papers, from the records. See {fig:gain}.",
                "from": "records",
                "rows": "family",
                "columns": "year",
                "place": {"section": "F1 Learned priors", "after": "heading"},
            },
            self.dots(),
            {
                "id": "concept",
                "type": "diagram",
                "file": "concept.svg",
                "title": "How a learned prior works",
                "caption": "A concept, no data.",
                "place": {"section": "Methods", "after": "heading"},
            },
        )
        code, out = run(self.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("figures 3", out)
        page = self.page()
        order = re.findall(r'<figure class="fig" id="fig-([a-z0-9-]+)"', page)
        self.assertEqual(order, ["gain", "concept", "families"])  # reading order, not spec order
        self.assertIn("<b>Figure 1. The headline gain.</b>", page)
        self.assertIn("<b>Figure 3. Papers by family and year.</b>", page)
        self.assertIn('<a class="figref" href="#fig-gain">Figure 1</a> plots it.</p>', page)
        self.assertIn('See <a class="figref" href="#fig-gain">Figure 1</a>.', page)
        self.assertIn("--fg-c1", page)  # the figure styles come with figures
        self.assertEqual(page.count('class="fig fg-defs"'), 1)
        for s in svgs(page):
            ET.fromstring(s)  # well-formed
            self.assertNotRegex(s, r'(fill|stroke)="#')  # colours only through classes
            self.assertNotIn("nan", s.lower().replace("nanny", ""))
        cites = data_of(page)["cites"]
        figs = {k: v for k, v in cites.items() if k.startswith("fig")}
        self.assertEqual(sorted(v["k"] for v in figs.values()), ["brown2020b", "smith2021a"])
        self.assertIn('href="https://doi.org/10.1000/a" data-c="fig0"', page)
        self.assertRegex(page, r'<a href="#methodological-rigor"><text')  # data-section became a jump
        self.assertIn("Data behind the figure", page)
        # counted from the records: F1 has two papers (2020, 2021), A one (2022)
        fam = must(re.search(r'id="fig-families".*?</figure>', page, re.S)).group(0)
        self.assertIn(">F1 Learned priors<", fam)
        self.assertRegex(fam, r"<td>F1 Learned priors</td><td>1</td><td>1</td><td>0</td><td>2</td>")

    def test_refusals_block_the_page(self):
        cases = [
            (self.dots(rows=[{"key": "smith2021a", "values": {"_": [9.9]}}]), "9.9 is not in the review"),
            (self.dots(rows=[{"key": "nobody2020", "values": {"_": [1.5]}}]), 'key "nobody2020" is not in'),
            (self.dots(place={"section": "No such heading"}), "is not a heading of review.md"),
            (self.dots(place={"section": "Summary", "after": "No such words"}), "no paragraph"),
            (self.dots(mention="See the figure."), "must contain {n}"),
            (self.dots(place={"section": "Summary", "after": "heading"}), "follows no paragraph"),
            (self.dots(caption="A 77 dB gain."), "77 not in the review"),
            (self.dots(type="pie"), "type must be one of"),
            (self.dots(id="Bad Id"), "id: lowercase"),
        ]
        for fig, msg in cases:
            with self.subTest(msg=msg):
                self.spec(fig)
                code, out = run(self.dir)
                self.assertEqual(code, 1, out)
                self.assertIn(msg, out)
                self.assertIn("nothing written", out)
                self.assertEqual(figs_run("check", self.dir)[0], 1)

    def test_numbers_from_the_record_of_the_row(self):
        # 31.2 is not in the review but is in smith2021a's record: allowed on that row, refused on another
        self.spec(self.dots(rows=[{"key": "smith2021a", "values": {"_": [31.2]}}]))
        self.assertEqual(figs_run("check", self.dir)[0], 0)
        self.spec(self.dots(rows=[{"key": "brown2020b", "values": {"_": [31.2]}}]))
        code, out = figs_run("check", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("record of brown2020b", out)

    def test_check_and_preview(self):
        self.spec(self.dots())
        code, out = figs_run("check", self.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("ok   gain: dots, 1 rows", out)
        code, out = figs_run("preview", self.dir)
        self.assertEqual(code, 0, out)
        prev = (self.figdir / "preview" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="fig-gain"', prev)


def custom_svg(marks, ticks=(0, 1, 2), extra=""):
    """A custom chart on a y axis from 0 (y=200) to 2 (y=40): Y(1.5) = 80."""
    t = "".join(
        f'<line x1="40" y1="{200 - 80 * v}" x2="600" y2="{200 - 80 * v}" class="line-grid" data-ytick="{v}"/>'
        f'<text x="34" y="{203 - 80 * v}" text-anchor="end" data-ytick="{v}">{v}</text>'
        for v in ticks
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 220">{t}{marks}{extra}</svg>'


AXES = {"y": {"data": [0, 2], "px": [200, 40], "label": "Gain (dB)"}}


class TestCustom(FigureCase):
    def custom(self, svg, axes=AXES, **kw):
        self.figdir.mkdir(parents=True, exist_ok=True)
        (self.figdir / "c.svg").write_text(svg, encoding="utf-8")
        f = {
            "id": "custom",
            "type": "custom",
            "file": "c.svg",
            "title": "A custom chart",
            "caption": "Drawn by hand.",
            "place": {"section": "Summary", "after": "paragraph"},
            "axes": axes,
            **kw,
        }
        self.spec(f)
        return run(self.dir)

    def test_marks_at_their_values_link_and_tabulate(self):
        marks = (
            '<g data-key="smith2021a" data-label="Smith 2021"><circle cx="100" cy="80" r="4" class="fill-1" '
            'data-y="1.5"/><rect x="200" y="80" width="20" height="120" class="fill-2" data-y="1.5" '
            'data-base="0"/></g>'
            '<g transform="translate(10, 20)"><circle cx="300" cy="60" r="4" class="fill-1" data-y="1.5" '
            'data-label="shifted"/></g>'
            '<polyline points="180,80 320,80" class="line-1" fill="none" data-points="2020,1.5 2021,1.5"/>'
            '<line x1="180" y1="200" x2="180" y2="205" class="line-axis" data-xtick="2020"/>'
            '<text x="460" y="215" text-anchor="middle" data-xtick="2022">2022</text>'
        )
        axes = dict(AXES, x={"data": [2019, 2023], "px": [40, 600], "label": "Year"})
        code, out = self.custom(custom_svg(marks), axes=axes)
        self.assertEqual(code, 0, out)
        page = self.page()
        fig = must(re.search(r'id="fig-custom".*?</figure>', page, re.S)).group(0)
        svg = must(re.search(r"<svg.*?</svg>", fig, re.S)).group(0)
        ET.fromstring(svg)
        self.assertNotIn("data-y=", svg)  # annotations do not reach the page
        self.assertIn('<a href="https://doi.org/10.1000/a" data-c="fig0"', svg)
        self.assertIn("<th>Gain (dB)</th>", fig)
        self.assertIn(">Smith 2021<", fig)
        self.assertIn("<td>2020, 1.5 2021, 1.5</td>", fig)

    def test_table_columns_follow_each_panel_axis(self):
        # two panels on different x scales; the left panel's line repeats its own dots
        marks = (
            '<g data-label="Left" data-series="s"><polyline points="100,80 200,80" fill="none" class="line-1" '
            'data-points="2020,1.5 2021,1.5"/><circle cx="100" cy="80" r="4" data-x="2020" data-y="1.5"/>'
            '<circle cx="200" cy="80" r="4" data-x="2021" data-y="1.5"/></g>'
            '<line x1="100" y1="200" x2="100" y2="205" data-xtick="2020"/>'
            '<line x1="200" y1="200" x2="200" y2="205" data-xtick="2021"/>'
            '<g data-xaxis="x2"><circle cx="500" cy="80" r="4" data-x="1.5" data-y="1.5" data-label="Right"/>'
            '<line x1="400" y1="200" x2="400" y2="205" data-xtick="0"/>'
            '<line x1="600" y1="200" x2="600" y2="205" data-xtick="3"/></g>'
        )
        axes = dict(
            AXES,
            x={"data": [2020, 2021], "px": [100, 200], "label": "Year"},
            x2={"data": [0, 3], "px": [400, 600], "label": "Spokes"},
        )
        code, out = self.custom(custom_svg(marks), axes=axes)
        self.assertEqual(code, 0, out)
        fig = must(re.search(r'id="fig-custom".*?</figure>', self.page(), re.S)).group(0)
        table = must(re.search(r"<table.*?</table>", fig, re.S)).group(0)
        heads = re.findall(r"<th>(.*?)</th>", table)
        self.assertEqual(heads, ["Mark", "Series", "Year", "Spokes", "Gain (dB)"])  # no shared x column, no Points
        rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)[1:]
        self.assertEqual(len(rows), 3)
        right = re.findall(r"<td[^>]*>(.*?)</td>", rows[-1], re.S)
        self.assertEqual(right[-3:], ["", "1.5", "1.5"])

    def test_position_and_tick_refusals(self):
        ok_circle = '<circle cx="100" cy="80" r="4" data-y="1.5"/>'
        cases = {
            "misplaced point": ('<circle cx="100" cy="90" r="4" data-y="1.5"/>', {}, "is drawn at 90.0"),
            "bar base": ('<rect x="0" y="80" width="9" height="100" data-y="1.5" data-base="0"/>', {}, "should end at"),
            "one tick": (ok_circle, {"ticks": (1,)}, "at least two ticks"),
            "tick label": (
                ok_circle,
                {"extra": '<text x="34" y="43" text-anchor="end" data-ytick="2">3</text>'},
                "does not read 2",
            ),
            "tick line": (
                ok_circle,
                {"extra": '<line x1="0" y1="50" x2="9" y2="50" data-ytick="2"/>'},
                "should run along y = 40.0",
            ),
            "number": ('<circle cx="100" cy="64" r="4" data-y="1.7"/>', {}, "1.7 is not in the review"),
            "rotated": ('<g transform="rotate(5)">' + ok_circle + "</g>", {}, "rotated or scaled"),
            "no marks": ("", {}, "at least one data mark"),
            "no axis": ('<circle cx="100" cy="80" r="4" data-x="1.5"/>', {}, 'no axis "x"'),
        }
        for name, (marks, kw, msg) in cases.items():
            with self.subTest(name=name):
                code, out = self.custom(custom_svg(marks, **kw))
                self.assertEqual(code, 1, out)
                self.assertIn(msg, out)
        code, out = self.custom(custom_svg(ok_circle), axes={})
        self.assertIn("axes: a custom figure declares its axes", out)

    def test_diagrams_take_no_data_values(self):
        self.figdir.mkdir(parents=True, exist_ok=True)
        (self.figdir / "d.svg").write_text(
            custom_svg('<circle cx="100" cy="80" r="4" data-y="1.5"/>'), encoding="utf-8"
        )
        self.spec(
            {
                "id": "d",
                "type": "diagram",
                "file": "d.svg",
                "title": "D",
                "caption": "C",
                "place": {"section": "Summary"},
            }
        )
        code, out = run(self.dir)
        self.assertEqual(code, 1)
        self.assertIn('figures of type "custom"', out)


class TestDiagramAllowlist(unittest.TestCase):
    def check(self, svg):
        chk = figures.Checker(figures.Ctx(check=False))
        out = figures.sanitize_svg(svg, chk, figures.Ctx(check=False), "", "", "t")
        return out, chk.bad

    def test_hostile_svg_is_refused(self):
        head = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 100">'
        hostile = {
            "script": head + "<script>alert(1)</script></svg>",
            "event": head + '<rect x="0" y="0" width="1" height="1" onclick="alert(1)"/></svg>',
            "raw colour": head + '<rect x="0" y="0" width="1" height="1" fill="#ff0000"/></svg>',
            "style": head + '<rect x="0" y="0" width="1" height="1" style="fill:red"/></svg>',
            "href": head + '<a href="https://example.org"><text x="1" y="1">x</text></a></svg>',
            "xlink": (
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                'viewBox="0 0 680 100"><a xlink:href="javascript:alert(1)"><text x="1" y="1">x</text></a></svg>'
            ),
            "image": head + '<image href="x.png" x="0" y="0" width="1" height="1"/></svg>',
            "foreignObject": head + "<foreignObject><div>x</div></foreignObject></svg>",
            "doctype": '<!DOCTYPE svg [<!ENTITY a "b">]>' + head + "</svg>",
            "class": head + '<rect x="0" y="0" width="1" height="1" class="evil"/></svg>',
            "tiny text": head + '<text x="1" y="1" font-size="5">x</text></svg>',
            "bad marker": head + '<line x1="0" y1="0" x2="1" y2="1" marker-end="url(https://x/y)"/></svg>',
            "viewBox": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5000 100"></svg>',
            "transform": head + '<g transform="matrix(1 0 0 1 0 0)"></g></svg>',
        }
        for name, svg in hostile.items():
            with self.subTest(name=name):
                _, bad = self.check(svg)
                self.assertTrue(bad, name)

    def test_examples_pass(self):
        for name in ("taxonomy.svg", "pipeline.svg"):
            with self.subTest(name=name):
                out, bad = self.check((PLUGIN / "templates" / "figures" / "examples" / name).read_text())
                self.assertEqual(bad, [])
                ET.fromstring(out)
                self.assertNotIn("<!--", out)


class TestLayouts(unittest.TestCase):
    LONG = "A very long label that would never fit in the space a chart gives to its row labels, ever"

    def draw(self, fig):
        ctx = figures.Ctx(check=False)
        prep, bad = figures.prepare(fig, ctx)
        self.assertEqual(bad, [])
        html, n = figures.render(prep, ctx)
        svg = must(re.search(r'<svg viewBox="0 0 (\d+) (\d+)".*?</svg>', html, re.S))
        root = ET.fromstring(svg.group(0))
        h = float(svg.group(2))
        for el in root.iter():
            for a in ("x", "y", "x1", "x2", "y1", "y2", "cx", "cy"):
                if a in el.attrib:
                    v = float(el.attrib[a])
                    self.assertTrue(
                        -60 <= v <= (720 if a.startswith(("x", "c")) and a != "cy" else h + 40),
                        f"{a}={v} outside the drawing in {fig['type']}",
                    )
        return html, n

    def base(self, t, **kw):
        return {"id": "f", "type": t, "title": "T", "caption": "C", "place": {"section": "S"}, **kw}

    def test_one_row_and_forty_rows(self):
        for n in (1, 40):
            rows = [
                {"label": f"{self.LONG} {i}", "values": {"_": [i - 3.5]}, "text": "x" * 80, "note": "y" * 90}
                for i in range(n)
            ]
            html, got = self.draw(self.base("dots", rows=rows))
            self.assertEqual(got, n)
            self.assertIn("…", html)  # shortened in the chart
            self.assertIn(self.LONG, html)  # whole in the data table
            bars = [{"label": f"{self.LONG} {i}", "value": i + 1, "of": 40} for i in range(n)]
            self.draw(self.base("bars", rows=bars))
            heat = {
                "columns": [{"id": f"C{j}", "label": "Long column name"} for j in range(9)],
                "rows": [
                    {"label": f"{self.LONG} {i}", "values": {f"C{j}": (i + j) % 3 for j in range(9)}, "total": i}
                    for i in range(n)
                ],
                "scale": {"min": 0, "max": 2},
                "mean": True,
            }
            self.draw(self.base("heatmap", **heat))
            cols = [{"x": str(2000 + i), "values": {"a": i % 4, "b": 1}} for i in range(n)]
            self.draw(self.base("columns", series=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], columns=cols))
            pts = [{"label": f"P{i}", "x": 2020 + i % 5, "y": i % 7, "tag": i < 3} for i in range(n)]
            self.draw(self.base("scatter", x={"label": "Year"}, y={"label": "Score"}, points=pts))

    def test_same_place_points_are_spread(self):
        pts = [{"label": f"P{i}", "x": 2021, "y": 3} for i in range(3)]
        html, _ = self.draw(self.base("scatter", x={"label": "Year"}, y={"label": "Score"}, points=pts))
        xs = set(re.findall(r'<circle cx="([\d.]+)" cy="[\d.]+" r="4.1"', html))
        self.assertEqual(len(xs), 3)

    def test_count_bins(self):
        lv = figures.heat_levels({"counts": True}, [1, 2, 3])
        self.assertEqual([ln[2] for ln in lv], ["1", "2", "3"])
        lv = figures.heat_levels({"counts": True}, [1, 6])
        self.assertEqual([ln[2] for ln in lv], ["1", "2", "3–4", "5–6"])
        lv = figures.heat_levels({"counts": True}, [1, 40])
        self.assertEqual(lv[0][0], 1)
        self.assertEqual(lv[-1][1], 40)
        self.assertLessEqual(len(lv), 5)
        for v in range(1, 41):  # every count falls in one bin
            self.assertEqual(sum(a <= v <= b for a, b, _, _ in lv), 1, v)

    def test_gallery(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = figs_run("gallery", "--out", tmp)
            self.assertEqual(code, 0, out)
            page = (Path(tmp) / "index.html").read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r'<figure class="fig"', page)), 10)


if __name__ == "__main__":
    unittest.main()
