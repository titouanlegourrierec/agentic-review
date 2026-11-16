"""Figures of the reading edition (standard library only).

A review's figures are described in 5-final/figures/figures.json (written by the figure-designer agent):

- charts (`dots`, `bars`, `columns`, `scatter`, `heatmap`) are drawn here, from the numbers in the spec or from
  counts computed over the records, so every mark sits at its value by construction;
- diagrams (`diagram`) are SVG files drawn by the agent for ideas that carry no data (a taxonomy, a pipeline).
  They are checked against an allowlist of elements, attributes and colour classes, and refused otherwise;
- custom charts (`custom`) are SVG files drawn by the agent for a chart the types above cannot draw. The spec
  declares the axes (data range -> SVG coordinates); each data mark carries its value (data-x, data-y ...) and at
  least two ticks per axis carry theirs. A mark or tick that does not sit where its value belongs is refused, so
  the drawing cannot say one number and show another.

Every number a chart shows that is not computed here must appear in the review, in counts.json or in the record of
the paper on that row: the rule of the headline tiles. Rows and points that name a paper link to it like the
citations of the text (the Zotero passage, or the publisher's page) and preview it on hover.

Colours come only from classes (fill-1 ... fill-8, fill-q1 ... fill-q5, fill-ink ...) that figures.css defines for
the light and the dark theme; no figure carries a raw colour. The format is documented in
templates/figures/GUIDE.md.
"""

import copy
import glob
import html
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import arlib

from . import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join("5-final", "figures")
SPEC = os.path.join(FIG_DIR, "figures.json")
W = 680  # drawing width in SVG units; the page shows it up to 920 px wide
FS, FS_S, FS_MIN = 9.5, 8.5, 8
TYPES = ("dots", "bars", "columns", "scatter", "heatmap", "diagram", "custom")
MAX_ROWS, MAX_POINTS, MAX_COLS, MAX_FIGURES = 40, 300, 24, 12
MINUS = "−"
ID_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
NUM = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?")
SKIP_FIELD = re.compile(r"doi|url|arxiv|openalex|pmid|pmcid|isbn|issn|^code|^key$|source_of_record|zotero|_id$", re.I)
MARKERS = ("filled", "hollow", "diamond", "square")
COLOURS = (*tuple(range(1, 9)), "muted", "ink")
REC_FIELDS = ("tier", "family", "year", "venue_type", "evidence_depth", "source")
FIG_TOKEN = re.compile(r"@@FIG(REF)?:([a-z0-9-]+)@@")


class FigureError(Exception):
    pass


# --------------------------------------------------------------------------- small helpers


def esc(s):
    return html.escape(str(s), quote=False)


def esca(s):
    return html.escape(str(s), quote=True)


def norm_num(s):
    s = str(s).lstrip("+-−").replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def nums(text):
    return {norm_num(n) for n in NUM.findall(str(text or ""))}


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fmt(v, signed=False):
    """A number as the figure prints it: no trailing zeros, a true minus sign, + when signed."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(abs(v)) if isinstance(v, int) else (f"{abs(v):.6f}".rstrip("0").rstrip("."))
    if v < 0:
        return MINUS + s
    return ("+" + s) if signed and v > 0 else s


def num_key(v):
    return norm_num(fmt(v))


def tw(s, size=FS, bold=False):
    """Approximate width of a text in SVG units (a sans-serif face; errs on the wide side)."""
    w = 0.0
    for ch in str(s):
        if ch == " ":
            w += 0.28
        elif ch in "il.,:;'|!ıj·":
            w += 0.26
        elif ch in "frt()[]{}-/–*":
            w += 0.36
        elif ch in "mwMW":
            w += 0.86
        elif ch.isupper():
            w += 0.67
        elif ch.isdigit():
            w += 0.58
        elif ord(ch) > 0x2000:
            w += 0.62
        else:
            w += 0.54
    return w * size * (1.06 if bold else 1)


def fit(s, size, maxw, bold=False):
    s = str(s)
    if tw(s, size, bold) <= maxw:
        return s
    while s and tw(s + "…", size, bold) > maxw:
        s = s[:-1]
    return s.rstrip() + "…"


def wrap(s, size, maxw, lines=2):
    """Split a label into at most `lines` lines that fit maxw; the last one is shortened with an ellipsis."""
    words, out, cur = str(s).split(), [], ""
    for w_ in words:
        trial = f"{cur} {w_}".strip()
        if tw(trial, size) <= maxw or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = w_
    out.append(cur)
    if len(out) > lines:
        out = [*out[: lines - 1], " ".join(out[lines - 1 :])]
    return [fit(x, size, maxw) for x in out]


def T(x, y, s, cls="", size=None, anchor="start", weight=None, italic=False, extra=""):
    a = f'<text x="{x:.1f}" y="{y:.1f}"'
    if size and size != FS:
        a += f' font-size="{size}"'
    if anchor != "start":
        a += f' text-anchor="{anchor}"'
    if weight:
        a += f' font-weight="{weight}"'
    if italic:
        a += ' font-style="italic"'
    if cls:
        a += f' class="{cls}"'
    return f"{a}{extra}>{esc(s)}</text>"


def R(x, y, w, h, cls, rx=0, extra=""):
    r = f' rx="{rx}"' if rx else ""
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{max(h, 0):.1f}"{r} class="{cls}"{extra}/>'


def L(x1, y1, x2, y2, cls, sw=1, extra=""):
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}" stroke-width="{sw}"{extra}/>'


def bar_h(x0, y, w, h, cls, r=4):
    """Horizontal bar: square at the baseline x0, rounded at the data end."""
    if w <= 0.4:
        return ""
    r = min(r, w, h / 2)
    x1 = x0 + w
    return (
        f'<path d="M{x0:.1f},{y:.1f} H{x1 - r:.1f} Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f} V{y + h - r:.1f} '
        f'Q{x1:.1f},{y + h:.1f} {x1 - r:.1f},{y + h:.1f} H{x0:.1f} Z" class="{cls}"/>'
    )


def bar_v(x, base, w, h, cls, r=4):
    """Vertical bar standing on `base`: square at the baseline, rounded at the top."""
    if h <= 0.4:
        return ""
    r = min(r, h, w / 2)
    y1 = base - h
    return (
        f'<path d="M{x:.1f},{base:.1f} V{y1 + r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} H{x + w - r:.1f} '
        f'Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 + r:.1f} V{base:.1f} Z" class="{cls}"/>'
    )


def marker(kind, colour, x, y, extra=""):
    if kind == "hollow":
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.7" class="dot fill-surface line-{colour}" '
            f'stroke-width="1.7"{extra}/>'
        )
    if kind == "diamond":
        d = 4.7
        return (
            f'<path d="M{x:.1f},{y - d:.1f} L{x + d:.1f},{y:.1f} L{x:.1f},{y + d:.1f} L{x - d:.1f},{y:.1f} Z" '
            f'class="dot fill-{colour} line-surface" stroke-width="1.2"{extra}/>'
        )
    if kind == "square":
        return R(x - 4, y - 4, 8, 8, f"dot fill-{colour} line-surface", 1.5, f' stroke-width="1.2"{extra}')
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.1" class="dot fill-{colour} line-surface" stroke-width="1.6"{extra}/>'
    )


def swatch(kind, colour, x, y):
    """Legend key centred on (x, y)."""
    if kind in MARKERS:
        return marker(kind, colour, x, y)
    if kind == "hatch":
        return R(x - 7, y - 5, 14, 10, "fill-hatch line-axis", 2, ' stroke-width="0.6"')
    if kind == "band":
        return R(x - 7, y - 5, 14, 10, "fill-wash", 2)
    if kind == "empty":
        return R(x - 7, y - 5, 14, 10, "fill-surface line-grid", 2, ' stroke-width="0.8"')
    return R(x - 7, y - 5, 14, 10, f"fill-{colour}", 2)


def legend(items, y=0, x0=0, width=W):
    """items: [(kind, colour, text)]. Returns (svg, height used)."""
    if not items:
        return "", 0
    x, parts, line_y = x0, [], y
    for kind, colour, text in items:
        w = 20 + tw(text, FS_S) + 18
        if x + w > x0 + width and x > x0:
            x, line_y = x0, line_y + 17
        parts.append(swatch(kind, colour, x + 7, line_y + 7) + T(x + 18, line_y + 10, text, "fill-ink2", FS_S))
        x += w
    return "".join(parts), line_y - y + 22


def nice_step(span, target=6):
    raw = max(span, 1e-9) / target
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw * 0.999)


def nice_range(lo, hi, include_zero=False, target=6):
    if include_zero:
        lo, hi = min(lo, 0), max(hi, 0)
    if hi <= lo:
        lo, hi = lo - 1, hi + 1
    step = nice_step(hi - lo, target)
    return math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step, step


def ticks_between(lo, hi, step):
    out, v = [], lo
    while v <= hi + step * 1e-6:
        out.append(round(v, 10))
        v += step
    return out


def svg_wrap(h, body, label):
    return (
        f'<svg viewBox="0 0 {W} {math.ceil(h)}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{esca(label)}" font-size="{FS}">{body}</svg>'
    )


DEFS = (
    '<div class="fig fg-defs" aria-hidden="true"><svg focusable="false" width="0" height="0"><defs>'
    '<pattern id="fg-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
    '<rect width="5" height="5" class="fill-surface"/><line x1="0" y1="0" x2="0" y2="5" class="line-axis" '
    'stroke-width="1.6"/></pattern>'
    '<marker id="fg-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" '
    'orient="auto-start-reverse"><path d="M0,0.8 L7,4 L0,7.2 z" class="fill-ink2"/></marker>'
    '<marker id="fg-arrow-muted" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" '
    'orient="auto-start-reverse"><path d="M0,0.8 L7,4 L0,7.2 z" class="fill-muted"/></marker>'
    "</defs></svg></div>"
)


# --------------------------------------------------------------------------- what a figure may show


def counts_numbers(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if is_num(obj):
        out.add(num_key(obj))
    elif isinstance(obj, str):
        out |= nums(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            counts_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            counts_numbers(v, out)
    return out


def norm_head(s):
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", str(s or ""))
    s = re.sub(r"[*_`]+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def plain_md(s):
    """Markdown text as plain text: links keep their text, emphasis marks go."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", str(s or ""))
    s = re.sub(r"(\*\*|__|\*|`)", "", s)
    return re.sub(r"\s+", " ", s).strip()


HEAD_MD = re.compile(r"^(#{2,4})[ \t]+(.+?)[ \t]*$", re.M)


def find_section(md_text, name):
    """(h2, h3) of the review heading called `name` (a ##, ### or #### heading), or None."""
    want, h2, h3 = norm_head(name), "", ""
    for m in HEAD_MD.finditer(md_text):
        level, text = len(m.group(1)), m.group(2).strip()
        if level == 2:
            h2, h3 = text, ""
        elif level == 3:
            h3 = text
        if norm_head(text) == want:
            return h2, (h3 if level >= 3 else "")
    return None


def section_lines(md_text, name):
    """Lines under the review heading `name`, up to the next heading of the same or a higher level; None if absent."""
    want, lines = norm_head(name), md_text.splitlines()
    for i, line in enumerate(lines):
        m = HEAD_MD.match(line)
        if m and norm_head(m.group(2)) == want:
            level = len(m.group(1))
            out = []
            for l2 in lines[i + 1 :]:
                m2 = re.match(r"^(#{1,6})\s", l2)
                if m2 and len(m2.group(1)) <= level:
                    break
                out.append(l2)
            return out
    return None


def anchor_problem(md_text, place):
    """Why a figure cannot go where `place` says (checked on review.md), or ''."""
    lines = section_lines(md_text, place["section"])
    if lines is None:
        return ""
    after = place["after"].strip()
    if after.lower() in ("heading", "paragraph"):
        return ""
    if after.lower() == "table":
        return "" if any(ln.startswith("|") for ln in lines) else f'place: no table under "{place["section"]}"'
    want = plain_md(after).lower()
    if any(plain_md(ln).lower().startswith(want) for ln in lines if ln.strip() and not ln.startswith(("|", "#"))):
        return ""
    return f'place: no paragraph "{after}" under heading "{place["section"]}"'


class Ctx:
    """What the figures of one review can use: its text, counts, records, rigor scores, claims and links.
    `check` False (the gallery) skips the number and key checks and draws no links."""

    def __init__(
        self,
        md_text="",
        counts=None,
        records=None,
        rigor=None,
        claims=None,
        citemap=None,
        review=None,
        retier=None,
        cited=None,
        linker=None,
        data=None,
        check=True,
    ):
        self.md_text, self.check = md_text, check
        self.records, self.rigor, self.claims = records or {}, rigor or {}, claims or {}
        self.citemap, self.review, self.retier = citemap, review or {}, retier or {}
        self.cited = cited or set()
        self.linker, self.data = linker, data
        self.base = (nums(re.sub(r"\]\([^)]+\)", "]", md_text)) | counts_numbers(counts or {})) if check else None
        self._paper = {}
        self.links = []

    @classmethod
    def for_review(cls, rdir, review, md_text, counts, linker=None, data=None):
        rdir = str(rdir)
        records = {}
        for rel_path in (arlib.CORPUS, arlib.OMISSIONS, arlib.BACKGROUND):
            p = os.path.join(rdir, rel_path)
            if os.path.exists(p):
                for r in arlib.load_jsonl(p):
                    if r.get("key") and r["key"] not in records:
                        records[r["key"]] = r
        rigor = {}
        for p in sorted(glob_paths(rdir, os.path.join("4-checks", "rigor_scores*.jsonl"))):
            for r in arlib.load_jsonl(p):
                if r.get("key"):
                    rigor[r["key"]] = r
        claims = {}
        for p in sorted(glob_paths(rdir, os.path.join("4-checks", "claims_check*.jsonl"))):
            for c in arlib.load_jsonl(p):
                for k in re.split(r"[,;\s]+", str(c.get("paper_key") or "")):
                    if k:
                        claims.setdefault(k, []).append(c)
        citemap = arlib.load_citemap(rdir) or {}
        urls = set(re.findall(r"\]\((https?://[^)\s]+)\)", md_text))
        cited = {k for k, row in citemap.items() if (row.get("url") or "").strip() in urls}
        return cls(
            md_text, counts, records, rigor, claims, citemap, review, arlib.load_retiering(rdir), cited, linker, data
        )

    def label(self, key, given=""):
        row = (self.citemap or {}).get(key) if key else None
        return (row or {}).get("label") or str(given or "") or str(key or "")

    def paper_nums(self, key):
        if key not in self._paper:
            out = set()
            rec = self.records.get(key) or {}
            for k, v in rec.items():
                if not SKIP_FIELD.search(k):
                    counts_numbers(v, out)
            counts_numbers(self.rigor.get(key) or {}, out)
            for c in self.claims.get(key) or []:
                for f in ("claim_text", "evidence", "correct_value", "quote"):
                    counts_numbers(c.get(f), out)
            self._paper[key] = out
        return self._paper[key]

    def allowed(self, key=None, extra=()):
        if self.base is None:
            return None
        s = self.base | set(extra)
        return s | self.paper_nums(key) if key else s

    def review_line(self, key, h2):
        """The line of section h2 that cites this paper (a table row first): the best context for its link."""
        url = (((self.citemap or {}).get(key) or {}).get("url") or "").strip()
        if not url:
            return ""
        cur, hits = "", []
        for line in self.md_text.splitlines():
            if line.startswith("## "):
                cur = line[3:].strip()
            elif cur == h2 and f"]({url})" in line:
                hits.append(line)
        return next((l_ for l_ in hits if l_.startswith("|")), hits[0] if hits else "")

    def link(self, key, h2, h3, context):
        """(attributes of an <a> that opens the paper and previews it, link dict) or ('', None)."""
        if not key or self.linker is None or self.data is None or key not in self.linker.meta:
            return "", None
        link = self.linker.choose(key, h2, h3, context)
        aid = f"fig{len(self.links)}"
        cit = {"key": key, "link": link}
        self.data.add(aid, cit)
        href = markdown.safe_url(self.data.href(cit))
        self.links.append({"aid": aid, "key": key, "type": link["type"], "href": href})
        newtab = ' target="_blank" rel="noopener"' if href.startswith(("http", "papers/")) else ""
        return f' href="{esca(href)}" data-c="{aid}"{newtab}', link


def glob_paths(rdir, pattern):
    return glob.glob(os.path.join(rdir, pattern))


class Checker:
    """Collects the problems of one figure."""

    def __init__(self, ctx):
        self.ctx, self.bad = ctx, []

    def __call__(self, msg):
        self.bad.append(msg)

    def value(self, v, where, key=None, extra=()):
        if not is_num(v):
            self.bad.append(f"{where}: {json.dumps(v)} is not a number")
            return False
        ok = self.ctx.allowed(key, extra)
        if ok is not None and num_key(v) not in ok:
            whose = ", counts.json or the record of " + key if key else " or counts.json"
            self.bad.append(f"{where}: {fmt(v)} is not in the review{whose}")
        return True

    def text(self, s, where, key=None, extra=()):
        if s is None:
            return ""
        if not isinstance(s, str):
            self.bad.append(f"{where}: expected text")
            return ""
        ok = self.ctx.allowed(key, extra)
        if ok is not None:
            miss = [x for x in NUM.findall(s) if norm_num(x) not in ok]
            if miss:
                whose = ", counts.json or the record of " + key if key else " or counts.json"
                self.bad.append(f"{where}: {', '.join(miss)} not in the review{whose}")
        return s

    def key(self, r, where):
        key = r.get("key") or None
        if key is not None and not isinstance(key, str):
            self.bad.append(f"{where}: key must be text")
            return None
        if key and self.ctx.check and key not in (self.ctx.citemap or {}):
            self.bad.append(f'{where}: key "{key}" is not in citation_map.tsv')
        return key


def colour_of(c, default):
    if c in COLOURS:
        return c
    if isinstance(c, str) and c.isdigit() and int(c) in COLOURS:
        return int(c)
    return default


def series_list(spec, chk, cap, default_marker="filled"):
    raw = spec.get("series")
    if raw is None:
        return [{"id": "_", "label": "", "marker": default_marker, "colour": colour_of(spec.get("colour"), 1)}]
    if not isinstance(raw, list) or not raw:
        chk('series: expected a list of {"id", "label"}')
        return []
    out = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict) or not s.get("id"):
            chk(f"series {i + 1}: needs an id")
            continue
        mk = s.get("marker", default_marker)
        if mk not in MARKERS:
            chk(f'series "{s["id"]}": marker must be one of {", ".join(MARKERS)}')
        out.append(
            {
                "id": str(s["id"]),
                "label": chk.text(s.get("label", ""), f'series "{s["id"]}" label'),
                "marker": mk,
                "colour": colour_of(s.get("colour"), i + 1 if i < 8 else "muted"),
            }
        )
    if len(out) > cap:
        chk(f'{len(out)} series: at most {cap} for this type (fold the rest into "Other" or split the figure)')
    if len({s["id"] for s in out}) != len(out):
        chk("series ids must be unique")
    return out


# --------------------------------------------------------------------------- data computed from the records


def record_value(r, field, ctx):
    if field == "year":
        return arlib.cite_year(r)
    if field in ("tier", "family"):
        tier, fam = arlib.retiered(r, ctx.retier, ctx.review)
        if field == "tier":
            return tier or "?"
        codes = arlib.family_codes(fam)
        return codes[0] if codes else "?"
    v = r.get(field)
    return v if not arlib.is_empty(v) else "?"


def select_records(spec, ctx, chk):
    where = spec.get("where") or {}
    if not isinstance(where, dict):
        chk('where: expected {"field": value or [values]}')
        where = {}
    recs = list(ctx.records.values())
    if spec.get("cited"):
        recs = [r for r in recs if r.get("key") in ctx.cited]
    for field, want in where.items():
        want = [str(x) for x in (want if isinstance(want, list) else [want])]
        recs = [r for r in recs if str(record_value(r, field, ctx)) in want]
    return recs


def category_label(field, value, ctx):
    if field == "family":
        name = arlib.family_names(ctx.review).get(str(value))
        return f"{value} {name}" if name else str(value)
    return str(value)


def category_order(field, values, ctx, counts=None):
    vals = list(values)
    if field == "family":
        return sorted(vals, key=arlib.family_sort_key(ctx.review))
    if field == "tier":
        return sorted(vals, key=lambda t: (arlib.tier_order(t), str(t)))
    if all(isinstance(v, int) or (isinstance(v, str) and v.isdigit()) for v in vals):
        return sorted(vals, key=lambda v: int(v))
    if counts:
        return sorted(vals, key=lambda v: (-counts.get(v, 0), str(v)))
    return sorted(vals, key=str)


def fill_years(order):
    try:
        ints = [int(v) for v in order]
    except (TypeError, ValueError):
        return order
    if not ints or max(ints) - min(ints) > 60:
        return order
    return list(range(min(ints), max(ints) + 1))


# --------------------------------------------------------------------------- dots: rows on one axis


def prep_dots(spec, chk):
    series = series_list(spec, chk, 4)
    sids = {s["id"] for s in series}
    groups = spec.get("groups") or []
    if not isinstance(groups, list):
        chk('groups: expected a list of {"id", "label"}')
        groups = []
    gids = []
    for g in groups:
        if isinstance(g, dict) and g.get("id"):
            gids.append(str(g["id"]))
            chk.text(g.get("label", ""), f'group "{g["id"]}" label')
    rows = spec.get("rows")
    if not isinstance(rows, list) or not rows:
        chk("rows: expected a non-empty list")
        return None
    if len(rows) > MAX_ROWS:
        chk(f"{len(rows)} rows: at most {MAX_ROWS} (split the figure)")
    out, allv = [], []
    for i, r in enumerate(rows):
        where = f"row {i + 1}"
        if not isinstance(r, dict):
            chk(f"{where}: expected an object")
            continue
        key = chk.key(r, where)
        label = chk.ctx.label(key, r.get("label"))
        if not label:
            chk(f"{where}: needs a key or a label")
        vals = r.get("values")
        if vals is None and "value" in r:
            vals = {series[0]["id"] if series else "_": r["value"]}
        vals = vals or {}
        if not isinstance(vals, dict):
            chk(f'{where}: values must be {{"<series id>": number or [numbers]}}')
            vals = {}
        clean = {}
        for sid, v in vals.items():
            if sid not in sids:
                chk(f'{where}: unknown series "{sid}"')
                continue
            lst = v if isinstance(v, list) else [v]
            got = [x for x in lst if chk.value(x, f"{where} ({label})", key)]
            if got:
                clean[sid] = got
                allv += got
        g = r.get("group")
        if gids and g is not None and str(g) not in gids:
            chk(f'{where}: unknown group "{g}"')
        out.append(
            {
                "key": key,
                "label": label,
                "sub": chk.text(r.get("sub", ""), f"{where} sub", key),
                "text": chk.text(r.get("text", ""), f"{where} text", key),
                "note": chk.text(r.get("note", ""), f"{where} note", key),
                "group": str(g) if g is not None else None,
                "values": clean,
            }
        )
    axis = spec.get("axis") or {}
    if not isinstance(axis, dict):
        chk("axis: expected an object")
        axis = {}
    band = spec.get("band")
    if band is not None:
        if not isinstance(band, dict) or not is_num(band.get("from")) or not is_num(band.get("to")):
            chk('band: expected {"from": number, "to": number, "label", "group"}')
            band = None
        else:
            chk.value(band["from"], "band from")
            chk.value(band["to"], "band to")
            chk.text(band.get("label", ""), "band label")
            chk.text(band.get("legend", ""), "band legend")
            allv += [band["from"], band["to"]]
    lo, hi = axis.get("min"), axis.get("max")
    if (lo is not None and not is_num(lo)) or (hi is not None and not is_num(hi)):
        chk("axis min and max must be numbers")
        lo = hi = None
    if allv and ((lo is not None and min(allv) < lo) or (hi is not None and max(allv) > hi)):
        chk(f"a value lies outside the axis ({fmt(min(allv))} to {fmt(max(allv))})")
    for f in ("label", "left", "right", "unit"):
        chk.text(axis.get(f, ""), f"axis {f}")
    return {
        "series": series,
        "groups": [g for g in groups if isinstance(g, dict) and g.get("id")],
        "rows": out,
        "axis": axis,
        "band": band,
        "values": allv,
    }


def draw_dots(p, ctx, h2, h3, title):
    rows, series, axis, band = p["rows"], {s["id"]: s for s in p["series"]}, p["axis"], p["band"]
    vals = p["values"] or [0]
    zero = axis.get("zero", True)
    lo, hi, step = nice_range(min(vals), max(vals), include_zero=bool(zero))
    lo = axis["min"] if is_num(axis.get("min")) else lo
    hi = axis["max"] if is_num(axis.get("max")) else hi
    ticks = [t for t in axis.get("ticks") or [] if is_num(t)] or ticks_between(
        math.ceil(lo / step - 1e-9) * step, hi, step
    )
    signed = bool(axis.get("signed"))
    unit = axis.get("unit") or ""
    two_lines = any(r["sub"] or r["note"] for r in rows)
    RH = 28 if two_lines else 21
    lab_w = max(max(tw(r["label"], FS, True), tw(r["sub"], FS_S) if r["sub"] else 0) for r in rows) + 12
    txt_w = max(
        [tw(r["text"], FS_S) for r in rows if r["text"]] + [tw(r["note"], FS_S) for r in rows if r["note"]] + [0]
    )
    LW = min(lab_w, W * 0.34)
    RW = min(txt_w + 14, W * 0.3) if txt_w else 0
    PL, PR = LW + 6, W - RW - (12 if RW else 6)
    if PR - PL < 220:
        LW, RW = W * 0.3, W * 0.26 if RW else 0
        PL, PR = LW + 6, W - RW - (12 if RW else 6)
    X = (lambda v: PL + (v - lo) / (hi - lo) * (PR - PL)) if hi > lo else (lambda v: (PL + PR) / 2)
    out = []
    items = [(s["marker"], s["colour"], s["label"]) for s in p["series"] if s["label"]]
    if band and (band.get("legend") or band.get("label")):
        items.append(("band", 1, band.get("legend") or band["label"]))
    leg, y = legend(items if len(items) > 1 or band else [], 0)
    out.append(leg)
    y += 4
    top = y
    order = [g["id"] for g in p["groups"]]
    blocks = [(None, [r for r in rows if r["group"] is None or r["group"] not in order])] + [
        (g, [r for r in rows if r["group"] == g["id"]]) for g in p["groups"]
    ]
    body, band_span, table = [], None, []
    for g, grows in blocks:
        if not grows:
            continue
        if g is not None:
            body.append(T(0, y + 10, str(g.get("label") or g["id"]).upper(), "fill-muted cap", FS_MIN, weight=600))
            y += 18
        g_top = y
        for r in grows:
            cy = y + RH / 2
            ctxt = (
                " | ".join(x for x in (r["label"], r["sub"], r["text"], r["note"]) if x)
                + " "
                + " ".join(fmt(v, signed) for vs in r["values"].values() for v in vs)
            )
            attrs, _ = ctx.link(r["key"], h2, h3, ctxt)
            parts = [R(0, y + 1, W, RH - 2, "hit")]
            ly = cy - 1.5 if r["sub"] else cy + 3.2
            parts.append(T(LW, ly, fit(r["label"], FS, LW - 4, True), "fill-ink", anchor="end", weight=600))
            if r["sub"]:
                parts.append(T(LW, cy + 9.5, fit(r["sub"], FS_S, LW - 4), "fill-muted", FS_S, "end"))
            allv = [v for vs in r["values"].values() for v in vs]
            if len(r["values"]) > 1:
                parts.append(L(X(min(allv)), cy, X(max(allv)), cy, "line-axis", 1.4))
            for sid, vs in r["values"].items():
                s = series[sid]
                if len(vs) > 1:
                    parts.append(L(X(min(vs)), cy, X(max(vs)), cy, f"line-{s['colour']}", 2))
            for sid, vs in r["values"].items():
                s = series[sid]
                for v in sorted(set(vs)):
                    parts.append(marker(s["marker"], s["colour"], X(v), cy))
            if r["text"]:
                parts.append(
                    T(
                        PR + 12,
                        cy - 1.5 if r["note"] else cy + 3.2,
                        fit(r["text"], FS_S, RW - 4),
                        "fill-ink2",
                        FS_S,
                        weight=500,
                    )
                )
            if r["note"]:
                parts.append(
                    T(
                        PR + 12,
                        cy + 9.5 if r["text"] else cy + 3.2,
                        fit(r["note"], FS_S, RW - 4),
                        "fill-muted",
                        FS_S,
                        italic=True,
                    )
                )
            label_full = (
                f"{r['label']}: "
                + "; ".join(
                    f"{series[sid]['label'] or 'value'} " + ", ".join(fmt(v, signed) for v in vs)
                    for sid, vs in r["values"].items()
                )
                if r["values"]
                else r["label"]
            )
            if attrs:
                body.append(f'<a{attrs} aria-label="{esca(label_full)}">{"".join(parts)}</a>')
            else:
                body.append(f'<g class="row"><title>{esc(label_full)}</title>{"".join(parts)}</g>')
            body.append(L(0, y + RH, W, y + RH, "line-grid", 0.5))
            table.append((r, attrs))
            y += RH
        if band and g is not None and band.get("group") == g["id"]:
            band_span = (g_top, y)
        y += 8
    if band and band_span is None:
        band_span = (top, y - 8)
    bottom = y - 4
    grid = []
    if band:
        assert band_span is not None
        bx0, bx1 = X(band["from"]), X(band["to"])
        grid.append(R(bx0, band_span[0], bx1 - bx0, band_span[1] - band_span[0], "fill-wash"))
        if band.get("label") and band.get("legend"):
            grid.append(T((bx0 + bx1) / 2, band_span[0] - 4, band["label"], "fill-ink2", FS_S, "middle", 600))
    for t in ticks:
        if lo - 1e-9 <= t <= hi + 1e-9:
            is_zero = abs(t) < 1e-12 and zero
            grid.append(L(X(t), top, X(t), bottom, "line-ink2" if is_zero else "line-grid", 1 if is_zero else 0.7))
            grid.append(T(X(t), bottom + 13, fmt(t, signed) if t else "0", "fill-ink2", FS_S, "middle"))
    yy = bottom + 13
    if axis.get("label"):
        yy += 15
        grid.append(T((PL + PR) / 2, yy, axis["label"], "fill-ink2", FS_S, "middle"))
    if axis.get("left") or axis.get("right"):
        yy += 14
        if axis.get("left"):
            grid.append(T(PL, yy, axis["left"], "fill-muted", FS_MIN))
        if axis.get("right"):
            grid.append(T(PR, yy, axis["right"], "fill-muted", FS_MIN, "end"))
    svg = svg_wrap(yy + 6, "".join(out) + "".join(grid) + "".join(body), title)
    sids = [s["id"] for s in p["series"]]
    head = (
        ["Row"]
        + [series[s]["label"] or "Value" + (f" ({unit})" if unit else "") for s in sids]
        + (["Text"] if any(r["text"] for r, _ in table) else [])
        + (["Note"] if any(r["note"] for r, _ in table) else [])
    )
    trs = []
    for r, attrs in table:
        cells = [row_cell(r, attrs)]
        cells += [esc(" / ".join(fmt(v, signed) for v in r["values"].get(s, []))) for s in sids]
        if "Text" in head:
            cells.append(esc(r["text"]))
        if "Note" in head:
            cells.append(esc(r["note"]))
        trs.append(cells)
    return svg, data_table(head, trs), len(rows)


def row_cell(r, attrs):
    lab = esc(r["label"]) + (f'<br><span class="fd-sub">{esc(r["sub"])}</span>' if r.get("sub") else "")
    if attrs:
        return f'<a class="cite"{attrs}>{lab}</a>'
    return lab


def data_table(head, rows):
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


# --------------------------------------------------------------------------- bars: one value per row


def prep_bars(spec, chk):
    rows: list[dict[str, Any]] = []
    if spec.get("from") == "records":
        field = spec.get("group")
        if not isinstance(field, str) or not field:
            chk('from records: "group" names the record field to count by (family, tier, year, ...)')
            return None
        recs = select_records(spec, chk.ctx, chk)
        counts = {}
        for r in recs:
            v = record_value(r, field, chk.ctx)
            counts[v] = counts.get(v, 0) + 1
        order = category_order(field, counts, chk.ctx, counts if spec.get("sort") == "value" else None)
        n = len(recs)
        for v in order:
            rows.append(
                {
                    "key": None,
                    "label": category_label(field, v, chk.ctx),
                    "value": counts[v],
                    "of": n if spec.get("share") else None,
                    "weak": False,
                    "text": "",
                    "computed": True,
                }
            )
        computed = {num_key(n)} | {num_key(c) for c in counts.values()}
    else:
        raw = spec.get("rows")
        if not isinstance(raw, list) or not raw:
            chk('rows: expected a non-empty list (or "from": "records")')
            return None
        for i, r in enumerate(raw):
            where = f"row {i + 1}"
            if not isinstance(r, dict):
                chk(f"{where}: expected an object")
                continue
            key = chk.key(r, where)
            label = chk.ctx.label(key, r.get("label"))
            if not label:
                chk(f"{where}: needs a key or a label")
            chk.value(r.get("value"), f"{where} ({label})", key)
            of = r.get("of")
            if of is not None:
                chk.value(of, f"{where} ({label}) of", key)
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "value": r.get("value") if is_num(r.get("value")) else 0,
                    "of": of if is_num(of) else None,
                    "weak": r.get("style") == "weak",
                    "text": chk.text(r.get("text", ""), f"{where} text", key),
                    "computed": False,
                }
            )
        computed = set()
    if len(rows) > MAX_ROWS:
        chk(f"{len(rows)} rows: at most {MAX_ROWS}")
    if any(r["value"] < 0 for r in rows):
        chk('bars start at zero: use "dots" for signed values')
    axis = spec.get("axis") or {}
    if not isinstance(axis, dict):
        axis = {}
    if axis.get("max") is not None and not is_num(axis.get("max")):
        chk("axis max must be a number")
    for f in ("label",):
        chk.text(axis.get(f, ""), f"axis {f}", extra=computed)
    return {"rows": rows, "axis": axis, "colour": colour_of(spec.get("colour"), 1), "computed": computed}


def share(v, of):
    return f"{fmt(v)} of {fmt(of)} ({round(100 * v / of)}%)" if of else fmt(v)


def draw_bars(p, ctx, h2, h3, title):
    rows, axis, colour = p["rows"], p["axis"], p["colour"]
    texts = [r["text"] or share(r["value"], r["of"]) for r in rows]
    LW = min(max(tw(r["label"], FS) for r in rows) + 10, W * 0.42)
    VW = min(max(tw(t, FS_S) for t in texts) + 12, W * 0.3)
    BX, BW = LW + 6, W - LW - 6 - VW
    ofs = {r["of"] for r in rows}
    pct = len(ofs) == 1 and None not in ofs
    top_v = (
        axis.get("max")
        if is_num(axis.get("max"))
        else (next(iter(ofs)) if pct else max(max(r["value"] for r in rows), 1))
    )
    if not pct and not is_num(axis.get("max")):
        _, top_v, _step = nice_range(0, top_v)
    X = lambda v: BX + BW * v / top_v  # noqa: E731
    RH, bh = 22, 13
    parts, n = [], len(rows)
    if pct:
        of = next(iter(ofs))
        tick_vals = [(of * k / 4, f"{25 * k}%") for k in range(5)]
    else:
        st = nice_step(top_v, 5)
        tick_vals = [(t, fmt(t)) for t in ticks_between(0, top_v, st)]
    for t, lab in tick_vals:
        parts.append(L(X(t), 4, X(t), 6 + RH * n, "line-axis" if t == 0 else "line-grid", 1 if t == 0 else 0.7))
        parts.append(T(X(t), 18 + RH * n, lab, "fill-ink2", FS_S, "middle"))
    trs = []
    for i, (r, txt) in enumerate(zip(rows, texts)):
        y = 6 + i * RH
        attrs, _ = ctx.link(r["key"], h2, h3, f"{r['label']} | {txt}")
        g = [
            R(0, y, W, RH, "hit"),
            T(
                LW,
                y + RH / 2 + 3.2,
                fit(r["label"], FS, LW - 4),
                "fill-ink" if not r["weak"] else "fill-ink2",
                anchor="end",
            ),
        ]
        cls = "fill-hatch line-muted" if r["weak"] else f"fill-{colour}"
        g.append(
            bar_h(BX, y + (RH - bh) / 2, max(X(r["value"]) - BX, 2 if r["value"] else 0), bh, cls).replace(
                "/>", ' stroke-width="0.8"/>' if r["weak"] else "/>"
            )
        )
        g.append(T(X(r["value"]) + 6, y + RH / 2 + 3.2, txt, "fill-ink2 halo", FS_S))
        lab = f"{r['label']}: {txt}"
        g = "".join(g)
        parts.append(
            f'<a{attrs} aria-label="{esca(lab)}">{g}</a>'
            if attrs
            else f'<g class="row"><title>{esc(lab)}</title>{g}</g>'
        )
        trs.append(
            [
                row_cell(r, attrs),
                esc(fmt(r["value"])),
                esc(fmt(r["of"])) if r["of"] else "",
                f"{round(100 * r['value'] / r['of'])}%" if r["of"] else "",
            ]
        )
    H = 22 + RH * n
    if axis.get("label"):
        H += 14
        parts.append(T(BX + BW / 2, H, axis["label"], "fill-muted", FS_S, "middle"))
    head = ["Row", "Value"] + (["Of", "Share"] if any(r["of"] for r in rows) else [])
    trs = [t[: len(head)] for t in trs]
    return svg_wrap(H + 6, "".join(parts), title), data_table(head, trs), n


# --------------------------------------------------------------------------- columns: counts along an ordered axis


def prep_columns(spec, chk):
    if spec.get("from") == "records":
        xf, sf = spec.get("x"), spec.get("stack")
        if not isinstance(xf, str) or not xf:
            chk('from records: "x" names the record field along the axis (usually year)')
            return None
        recs = select_records(spec, chk.ctx, chk)
        cells, xs, ss = {}, {}, {}
        for r in recs:
            xv = record_value(r, xf, chk.ctx)
            sv = record_value(r, sf, chk.ctx) if sf else "_"
            cells[(xv, sv)] = cells.get((xv, sv), 0) + 1
            xs[xv] = xs.get(xv, 0) + 1
            ss[sv] = ss.get(sv, 0) + 1
        xorder = fill_years(category_order(xf, xs, chk.ctx))
        sorder = category_order(sf, ss, chk.ctx) if sf else ["_"]
        if len(sorder) > 8:
            keep = sorted(sorder, key=lambda s: -ss[s])[:7]
            sorder2 = [s for s in sorder if s in keep] + ["Other"]
            for (xv, sv), n in list(cells.items()):
                if sv not in keep:
                    cells[(xv, "Other")] = cells.get((xv, "Other"), 0) + n
            sorder = sorder2
        series = [
            {
                "id": str(s),
                "label": category_label(sf, s, chk.ctx) if sf and s != "Other" else ("Other" if s == "Other" else ""),
                "colour": (i + 1) if s != "Other" else "muted",
                "marker": "square",
            }
            for i, s in enumerate(sorder)
        ]
        cols = [
            {"x": str(xv), "values": {str(s): cells.get((xv, s), cells.get((str(xv), s), 0)) for s in sorder}}
            for xv in xorder
        ]
        computed = {num_key(len(recs))} | {num_key(n) for n in xs.values()} | {num_key(n) for n in ss.values()}
    else:
        series = series_list(spec, chk, 8, "square")
        sids = [s["id"] for s in series]
        raw = spec.get("columns")
        if not isinstance(raw, list) or not raw:
            chk('columns: expected a non-empty list of {"x", "values"} (or "from": "records")')
            return None
        cols: list[dict[str, Any]] = []
        for i, c in enumerate(raw):
            if not isinstance(c, dict) or "x" not in c:
                chk(f'column {i + 1}: expected {{"x": label, "values": {{...}}}}')
                continue
            vals = c.get("values")
            if vals is None and "value" in c:
                vals = {sids[0] if sids else "_": c["value"]}
            if not isinstance(vals, dict):
                chk(f"column {i + 1}: values must be an object")
                vals = {}
            clean = {}
            for sid, v in vals.items():
                if sid not in sids:
                    chk(f'column {i + 1}: unknown series "{sid}"')
                elif chk.value(v, f'column "{c["x"]}"'):
                    if v < 0:
                        chk(f'column "{c["x"]}": columns count things; use "dots" for signed values')
                    clean[sid] = v
            cols.append({"x": str(c["x"]), "values": clean})
        computed = {num_key(sum(c["values"].values())) for c in cols}
    if len(cols) > MAX_COLS * 2:
        chk(f"{len(cols)} columns: at most {MAX_COLS * 2}")
    axis = spec.get("axis") or {}
    if not isinstance(axis, dict):
        axis = {}
    chk.text(axis.get("label", ""), "axis label", extra=computed)
    return {"series": series, "cols": cols, "axis": axis, "computed": computed}


def draw_columns(p, ctx, h2, h3, title):
    series, cols, axis = p["series"], p["cols"], p["axis"]
    sids = [s["id"] for s in series]
    totals = [sum(c["values"].get(s, 0) for s in sids) for c in cols]
    items = [("square", s["colour"], s["label"]) for s in series if s["label"]]
    leg, y0 = legend(items if len(items) > 1 else [], 0)
    _, top_v, step = nice_range(0, max([*totals, 1]), target=4)
    PH, PL, PR = 170, 34, W - 6
    top = y0 + 14
    base = top + PH
    Y = lambda v: base - PH * v / top_v  # noqa: E731
    slot = (PR - PL) / len(cols)
    bw = min(24, slot * 0.62)
    parts = [leg]
    for t in ticks_between(0, top_v, step):
        parts.append(L(PL, Y(t), PR, Y(t), "line-axis" if t == 0 else "line-grid", 1 if t == 0 else 0.7))
        parts.append(T(PL - 6, Y(t) + 3, fmt(t), "fill-ink2", FS_S, "end"))
    rotate = any(tw(c["x"], FS_S) > slot - 3 for c in cols)
    trs = []
    for i, c in enumerate(cols):
        x = PL + i * slot + (slot - bw) / 2
        g = [R(PL + i * slot, top - 12, slot, PH + 12, "hit")]
        cum, segs = 0, [(s, c["values"].get(s["id"], 0)) for s in series]
        nz = [k for k, (_, v) in enumerate(segs) if v > 0]
        for k, (s, v) in enumerate(segs):
            if v <= 0:
                continue
            h = PH * v / top_v
            yb = Y(cum)
            if k == nz[-1]:
                g.append(bar_v(x, yb, bw, h, f"fill-{s['colour']}"))
            else:
                g.append(R(x, yb - h, bw, h, f"fill-{s['colour']}"))
            if cum > 0:
                g.append(L(x, yb, x + bw, yb, "line-surface", 2))
            cum += v
        if totals[i]:
            g.append(T(x + bw / 2, Y(totals[i]) - 4, fmt(totals[i]), "fill-ink2", FS_S, "middle", 500))
        lab = f"{c['x']}: " + (
            ", ".join(f"{s['label']} {fmt(c['values'].get(s['id'], 0))}" for s in series if c["values"].get(s["id"]))
            if len(series) > 1
            else fmt(totals[i])
        )
        parts.append(f'<g class="row"><title>{esc(lab)}</title>{"".join(g)}</g>')
        if rotate:
            parts.append(
                T(
                    x + bw / 2 + 3,
                    base + 10,
                    c["x"],
                    "fill-ink2",
                    FS_S,
                    "end",
                    extra=f' transform="rotate(-40 {x + bw / 2 + 3:.1f} {base + 10:.1f})"',
                )
            )
        else:
            parts.append(T(x + bw / 2, base + 13, c["x"], "fill-ink2", FS_S, "middle"))
        trs.append([esc(c["x"])] + [esc(fmt(c["values"].get(s, 0))) for s in sids] + [esc(fmt(totals[i]))])
    H = base + (max(tw(c["x"], FS_S) for c in cols) * 0.66 + 14 if rotate else 18)
    if axis.get("label"):
        H += 14
        parts.append(T((PL + PR) / 2, H, axis["label"], "fill-muted", FS_S, "middle"))
    head = ["Category"] + [s["label"] or "Value" for s in series] + (["Total"] if len(series) > 1 else [])
    trs = [t if len(series) > 1 else t[:2] for t in trs]
    return svg_wrap(H + 6, "".join(parts), title), data_table(head, trs), len(cols)


# --------------------------------------------------------------------------- scatter: one point per paper


def prep_axis(a, name, chk, vals):
    a = a if isinstance(a, dict) else {}
    if not a.get("label"):
        chk(f"{name}: needs a label")
    chk.text(a.get("label", ""), f"{name} label")
    log = bool(a.get("log"))
    if log and any(v <= 0 for v in vals):
        chk(f"{name}: a log axis needs positive values")
        log = False
    for f in ("min", "max"):
        if a.get(f) is not None and not is_num(a.get(f)):
            chk(f"{name} {f} must be a number")
    if vals and ((is_num(a.get("min")) and min(vals) < a["min"]) or (is_num(a.get("max")) and max(vals) > a["max"])):
        chk(f"{name}: a value lies outside the axis")
    return {
        "label": a.get("label", ""),
        "min": a.get("min"),
        "max": a.get("max"),
        "log": log,
        "zero": bool(a.get("zero")),
    }


def prep_scatter(spec, chk):
    series = series_list(spec, chk, 3)
    sids = {s["id"] for s in series}
    raw = spec.get("points")
    if not isinstance(raw, list) or not raw:
        chk('points: expected a non-empty list of {"key", "x", "y"}')
        return None
    if len(raw) > MAX_POINTS:
        chk(f"{len(raw)} points: at most {MAX_POINTS}")
    pts = []
    for i, r in enumerate(raw):
        where = f"point {i + 1}"
        if not isinstance(r, dict):
            chk(f"{where}: expected an object")
            continue
        key = chk.key(r, where)
        label = chk.ctx.label(key, r.get("label"))
        okx = chk.value(r.get("x"), f"{where} ({label}) x", key)
        oky = chk.value(r.get("y"), f"{where} ({label}) y", key)
        sid = str(r.get("series", series[0]["id"] if series else "_"))
        if sid not in sids:
            chk(f'{where}: unknown series "{sid}"')
        if okx and oky:
            pts.append(
                {
                    "key": key,
                    "label": label,
                    "x": r["x"],
                    "y": r["y"],
                    "series": sid,
                    "tag": bool(r.get("tag")),
                    "note": chk.text(r.get("note", ""), f"{where} note", key),
                }
            )
    x = prep_axis(spec.get("x"), "x axis", chk, [q["x"] for q in pts])
    y = prep_axis(spec.get("y"), "y axis", chk, [q["y"] for q in pts])
    return {"series": series, "points": pts, "x": x, "y": y}


def scale_of(a, vals, lo_px, hi_px):
    if a["log"]:
        lo = a["min"] if is_num(a["min"]) else 10 ** math.floor(math.log10(min(vals)))
        hi = a["max"] if is_num(a["max"]) else 10 ** math.ceil(math.log10(max(vals)))
        if hi <= lo:
            hi = lo * 10
        f = lambda v: lo_px + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (hi_px - lo_px)  # noqa: E731
        ticks, d = [], math.floor(math.log10(lo))
        while 10**d <= hi * 1.0001:
            for m in (1, 2, 5) if math.log10(hi / lo) <= 3 else (1,):
                v = m * 10**d
                if lo <= v <= hi * 1.0001:
                    ticks.append(v)
            d += 1
        return f, ticks
    lo, hi, step = nice_range(min(vals), max(vals), include_zero=a["zero"], target=5)
    lo = a["min"] if is_num(a["min"]) else lo
    hi = a["max"] if is_num(a["max"]) else hi
    step = nice_step(hi - lo, 5)
    f = lambda v: lo_px + (v - lo) / ((hi - lo) or 1) * (hi_px - lo_px)  # noqa: E731
    return f, ticks_between(math.ceil(lo / step - 1e-9) * step, hi, step)


def draw_scatter(p, ctx, h2, h3, title):
    series, pts = {s["id"]: s for s in p["series"]}, p["points"]
    items = [(s["marker"], s["colour"], s["label"]) for s in p["series"] if s["label"]]
    leg, y0 = legend(items if len(items) > 1 else [], 0)
    ytick_w = 30
    PL, PR, PT = 18 + ytick_w, W - 14, y0 + 10
    PB = PT + 300
    X, xt = scale_of(p["x"], [q["x"] for q in pts], PL, PR)
    Y, yt = scale_of(p["y"], [q["y"] for q in pts], PB, PT)
    parts = [leg]
    for t in yt:
        parts.append(L(PL, Y(t), PR, Y(t), "line-grid", 0.7))
        parts.append(T(PL - 6, Y(t) + 3, fmt(t), "fill-ink2", FS_S, "end"))
    parts.append(L(PL, PB, PR, PB, "line-axis", 1))
    for t in xt:
        parts.append(L(X(t), PB, X(t), PB + 4, "line-axis", 1))
        parts.append(T(X(t), PB + 15, fmt(t), "fill-ink2", FS_S, "middle"))
    parts.append(T((PL + PR) / 2, PB + 30, p["x"]["label"], "fill-muted", FS_S, "middle"))
    yl = (PT + PB) / 2
    parts.append(
        T(10, yl, p["y"]["label"], "fill-muted", FS_S, "middle", extra=f' transform="rotate(-90 10 {yl:.1f})"')
    )
    # points at the same place are spread sideways so that each one stays visible and clickable
    spots = {}
    for q in pts:
        spots.setdefault((round(X(q["x"]), 1), round(Y(q["y"]), 1)), []).append(q)
    for same in spots.values():
        for k, q in enumerate(same):
            q["_dx"] = (k - (len(same) - 1) / 2) * 7
    boxes = [(X(q["x"]) + q["_dx"] - 5, Y(q["y"]) - 5, X(q["x"]) + q["_dx"] + 5, Y(q["y"]) + 5) for q in pts]
    labels, trs = [], []
    for q in sorted(pts, key=lambda q: (q["tag"], q["y"])):
        cx, cy = X(q["x"]) + q["_dx"], Y(q["y"])
        s = series.get(q["series"]) or p["series"][0]
        txt = f"{q['label']}: {p['x']['label']} {fmt(q['x'])}, {p['y']['label']} {fmt(q['y'])}"
        attrs, _ = ctx.link(q["key"], h2, h3, f"{q['label']} | {q['note']} | {fmt(q['x'])} {fmt(q['y'])}")
        g = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="9" class="hit"/>' + marker(s["marker"], s["colour"], cx, cy)
        parts.append(
            f'<a{attrs} aria-label="{esca(txt)}"><title>{esc(txt)}</title>{g}</a>'
            if attrs
            else f'<g class="row"><title>{esc(txt)}</title>{g}</g>'
        )
        if q["tag"]:
            w_ = tw(q["label"], FS_S)
            for dx, dy, anchor in ((8, 3, "start"), (-8, 3, "end"), (0, -9, "middle"), (0, 15, "middle")):
                lx = cx + dx
                x0 = lx if anchor == "start" else lx - w_ if anchor == "end" else lx - w_ / 2
                box = (x0, cy + dy - 8, x0 + w_, cy + dy + 2)
                if x0 < PL or x0 + w_ > W or box[1] < PT - 6 or box[3] > PB:
                    continue
                if any(
                    not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3])
                    for b in labels + [b for b in boxes if not (abs(b[0] + 5 - cx) < 0.1 and abs(b[1] + 5 - cy) < 0.1)]
                ):
                    continue
                labels.append(box)
                parts.append(T(lx, cy + dy, q["label"], "fill-ink2 halo", FS_S, anchor))
                break
        trs.append(
            [row_cell(q, attrs), esc(fmt(q["x"])), esc(fmt(q["y"]))] + ([esc(s["label"])] if len(series) > 1 else [])
        )
    head = ["Paper", p["x"]["label"], p["y"]["label"]] + (["Series"] if len(series) > 1 else [])
    return svg_wrap(PB + 38, "".join(parts), title), data_table(head, trs), len(pts)


# --------------------------------------------------------------------------- heatmap: rows x columns


def prep_heatmap(spec, chk):
    ctx = chk.ctx
    src = spec.get("from")
    computed = set()
    if src == "rigor_scores":
        recs = list(ctx.rigor.values())
        if spec.get("keys"):
            want = [k for k in spec["keys"] if isinstance(k, str)]
            missing = [k for k in want if k not in ctx.rigor]
            if missing:
                chk(f"keys without rigor scores: {', '.join(missing)}")
            recs = [ctx.rigor[k] for k in want if k in ctx.rigor]
        if not recs and ctx.check:
            chk("from rigor_scores: 4-checks/rigor_scores.jsonl has no scores")
            return None
        rubric = [x for x in (ctx.review.get("rigor_rubric") or []) if isinstance(x, dict) and x.get("id")]
        ids = [str(x["id"]) for x in rubric] or sorted(
            {c for r in recs for c in (r.get("scores") or {})}, key=arlib.natural_key
        )
        names = {str(x["id"]): x.get("name") or "" for x in rubric}
        cols = [{"id": c, "label": names.get(c, "")} for c in ids]
        rows: list[dict[str, Any]] = []
        for r in recs:
            sc = r.get("scores") or {}
            vals = {c: (sc.get(c) if is_num(sc.get(c)) else None) for c in ids}
            total = r.get("total") if is_num(r.get("total")) else sum(v for v in vals.values() if v is not None)
            mp = r.get("max_possible") if is_num(r.get("max_possible")) else None
            rows.append(
                {"key": r["key"], "label": ctx.label(r["key"], r["key"]), "values": vals, "total": total, "of": mp}
            )
            computed |= {num_key(total)} | ({num_key(mp)} if mp else set())
        if spec.get("sort", "total") == "total":
            rows.sort(key=lambda r: (-(r["total"] or 0), r["label"]))
        smax = max([v for r in rows for v in r["values"].values() if v is not None] + [2])
        scale = {"min": 0, "max": smax}
        totals = True
    elif src == "records":
        rf, cf = spec.get("rows"), spec.get("columns")
        if not isinstance(rf, str) or not isinstance(cf, str):
            chk('from records: "rows" and "columns" name two record fields (e.g. family and year)')
            return None
        recs = select_records(spec, ctx, chk)
        cells, rs, cs = {}, {}, {}
        for r in recs:
            a, b = record_value(r, rf, ctx), record_value(r, cf, ctx)
            cells[(a, b)] = cells.get((a, b), 0) + 1
            rs[a] = rs.get(a, 0) + 1
            cs[b] = cs.get(b, 0) + 1
        rorder = category_order(rf, rs, ctx)
        corder = fill_years(category_order(cf, cs, ctx))
        cols = [{"id": str(c), "label": str(c)} for c in corder]
        rows = [
            {
                "key": None,
                "label": category_label(rf, a, ctx),
                "values": {str(c): cells.get((a, c), cells.get((a, str(c)), 0)) for c in corder},
                "total": rs[a],
                "of": None,
            }
            for a in rorder
        ]
        computed = {num_key(len(recs))} | {num_key(n) for n in list(rs.values()) + list(cs.values())}
        scale = {"counts": True}
        totals = True
    else:
        rawc = spec.get("columns")
        if not isinstance(rawc, list) or not rawc:
            chk('columns: expected a list of {"id", "label"} (or "from": "rigor_scores" / "records")')
            return None
        cols = []
        for i, c in enumerate(rawc):
            if isinstance(c, str):
                c = {"id": c, "label": ""}
            if not isinstance(c, dict) or not c.get("id"):
                chk(f"column {i + 1}: needs an id")
                continue
            cols.append({"id": str(c["id"]), "label": chk.text(c.get("label", ""), f'column "{c["id"]}" label')})
        ids = {c["id"] for c in cols}
        rawr = spec.get("rows")
        if not isinstance(rawr, list) or not rawr:
            chk('rows: expected a non-empty list of {"key" or "label", "values"}')
            return None
        rows: list[dict[str, Any]] = []
        for i, r in enumerate(rawr):
            where = f"row {i + 1}"
            if not isinstance(r, dict):
                chk(f"{where}: expected an object")
                continue
            key = chk.key(r, where)
            label = ctx.label(key, r.get("label"))
            vals = r.get("values") if isinstance(r.get("values"), dict) else {}
            clean = {}
            for cid, v in vals.items():
                if cid not in ids:
                    chk(f'{where}: unknown column "{cid}"')
                elif v is None:
                    clean[cid] = None
                elif chk.value(v, f"{where} ({label}) {cid}", key):
                    clean[cid] = v
            total = r.get("total")
            if total is not None:
                chk.value(total, f"{where} ({label}) total", key)
            of = r.get("of")
            if of is not None:
                chk.value(of, f"{where} ({label}) of", key)
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "values": clean,
                    "total": total if is_num(total) else None,
                    "of": of if is_num(of) else None,
                }
            )
        sc = spec.get("scale") if isinstance(spec.get("scale"), dict) else {}
        allv = [v for r in rows for v in r["values"].values() if v is not None]
        scale = {
            "min": sc.get("min", min([*allv, 0])),
            "max": sc.get("max", max([*allv, 1])),
            "labels": sc.get("labels") if isinstance(sc.get("labels"), dict) else {},
            "counts": bool(sc.get("counts")),
        }
        totals = any(r["total"] is not None for r in rows)
    if len(rows) > MAX_ROWS:
        chk(f"{len(rows)} rows: at most {MAX_ROWS}")
    if len(cols) > MAX_COLS:
        chk(f"{len(cols)} columns: at most {MAX_COLS}")
    scale_labels = (spec.get("scale") or {}).get("labels") if isinstance(spec.get("scale"), dict) else None
    if isinstance(scale_labels, dict):
        for k, v in scale_labels.items():
            chk.text(str(v), f"scale label {k}")
        scale["labels"] = scale_labels
    return {
        "cols": cols,
        "rows": rows,
        "scale": scale,
        "totals": totals and spec.get("totals", True) is not False,
        "mean": bool(spec.get("mean", src == "rigor_scores")),
        "column_totals": bool(spec.get("column_totals", src == "records")),
        "total_label": spec.get("total_label") or "Total",
        "computed": computed,
    }


def heat_levels(scale, values):
    """[(lo, hi, label, step)] for the cells; counts leave zero empty."""
    vals = [v for v in values if v is not None]
    if scale.get("counts"):
        mx = int(max([*vals, 1]))
        if mx <= 5:
            bins = [(v, v) for v in range(1, mx + 1)]
        elif mx <= 9:
            bins = [(a, b) for a, b in ((1, 1), (2, 2), (3, 4), (5, 6), (7, 9)) if a <= mx]
        else:
            edges = sorted({1} | {math.ceil(mx ** (k / 5)) + 1 for k in range(1, 5)})
            bins = [(a, b - 1) for a, b in zip(edges, edges[1:]) if b - 1 >= a] + [(edges[-1], mx)]
        n = len(bins)
        out = []
        for i, (a, b) in enumerate(bins):
            b = min(b, mx)
            lab = str(a) if a == b else f"{a}–{b}"
            out.append((a, b, lab, 1 + round(i * 4 / max(n - 1, 1))))
        return out
    lo, hi = scale.get("min", 0), scale.get("max", 1)
    labels = scale.get("labels") or {}
    if all(float(v).is_integer() for v in [*vals, lo, hi]) and hi - lo <= 4:
        k = int(hi - lo) + 1
        return [
            (lo + i, lo + i, str(labels.get(str(int(lo + i)), fmt(lo + i))), 1 + round(i * 4 / max(k - 1, 1)))
            for i in range(k)
        ]
    edges = [lo + (hi - lo) * i / 5 for i in range(6)]
    return [
        (edges[i], edges[i + 1], f"{fmt(round(edges[i], 2))}–{fmt(round(edges[i + 1], 2))}", i + 1) for i in range(5)
    ]


def level_of(v, levels):
    for lo, hi, _, step in levels:
        if lo - 1e-9 <= v <= hi + 1e-9:
            return step
    return levels[-1][3] if levels and v > levels[-1][1] else (levels[0][3] if levels else 1)


def draw_heatmap(p, ctx, h2, h3, title):
    cols, rows, scale = p["cols"], p["rows"], p["scale"]
    levels = heat_levels(scale, [v for r in rows for v in r["values"].values()])
    LW = min(max(tw(r["label"], FS_S) for r in rows) + 10, W * 0.3)
    TW = 112 if p["totals"] else 0
    cw = min(48, (W - LW - 8 - TW) / max(len(cols), 1))
    CX = LW + 8
    TX = CX + cw * len(cols) + 12
    rh = 16

    def own_label(c):  # "2026*" for column 2026 is one label; "Data" for R1 is a second line
        return bool(c["label"]) and not c["label"].startswith(c["id"])

    head_lines = []
    for c in cols:
        if own_label(c):
            head_lines.append([c["id"], *wrap(c["label"], FS_MIN, cw - 2, 2)])
        else:
            head_lines.append(wrap(c["label"] or c["id"], FS_S, cw - 2, 2))
    hh = 10 * max(len(h) for h in head_lines) + 6
    parts = []
    for j, lines in enumerate(head_lines):
        x = CX + j * cw + cw / 2
        for k, ln in enumerate(lines):
            bold = own_label(cols[j]) and k == 0
            parts.append(
                T(
                    x,
                    9 + 10 * k,
                    ln,
                    "fill-ink" if bold else "fill-ink2",
                    FS_S if bold else 8,
                    "middle",
                    600 if bold else None,
                )
            )
    if p["totals"]:
        parts.append(
            T(
                TX,
                9 + 10 * (len(head_lines[0]) - 1 if head_lines else 0),
                p["total_label"],
                "fill-ink",
                FS_S,
                weight=600,
            )
        )
    y0 = hh + 4
    max_total = max([r["total"] or 0 for r in rows] + [r["of"] or 0 for r in rows] + [1])
    sums, ns, trs = [0.0] * len(cols), [0] * len(cols), []
    any_missing = False
    for i, r in enumerate(rows):
        y = y0 + i * rh
        ctxt = " | ".join(
            [r["label"]]
            + [f"{c['id']} {fmt(r['values'][c['id']])}" for c in cols if r["values"].get(c["id"]) is not None]
        )
        line = ctx.review_line(r["key"], h2) if r["key"] else ""
        attrs, _ = ctx.link(r["key"], h2, h3, line or ctxt)
        g = [R(0, y, W, rh, "hit"), T(LW, y + rh / 2 + 3, fit(r["label"], FS_S, LW - 4), "fill-ink", FS_S, "end")]
        for j, c in enumerate(cols):
            v = r["values"].get(c["id"], 0 if scale.get("counts") else None)
            x = CX + j * cw
            tip = f"{r['label']} · {c['id']}{' ' + c['label'] if c['label'] and c['label'] != c['id'] else ''}: "
            if v is None:
                any_missing = True
                g.append(R(x + 1, y + 1, cw - 2, rh - 2, "fill-hatch line-axis", 2, ' stroke-width="0.5"'))
                continue
            if scale.get("counts") and v == 0:
                g.append(R(x + 1, y + 1, cw - 2, rh - 2, "fill-surface line-grid", 2, ' stroke-width="0.6"'))
                continue
            sums[j] += v
            ns[j] += 1
            q = level_of(v, levels)
            g.append(
                f"<g><title>{esc(tip + fmt(v))}</title>"
                + R(x + 1, y + 1, cw - 2, rh - 2, f"fill-q{q}", 2)
                + T(x + cw / 2, y + rh / 2 + 3, fmt(v), f"on-q{q}", 8, "middle", 500)
                + "</g>"
            )
        if p["totals"] and r["total"] is not None:
            of = r["of"]
            bw = 70 * r["total"] / max_total
            g.append(bar_h(TX, y + 4, bw, rh - 8, "fill-ink2", 2))
            g.append(T(TX + bw + 5, y + rh / 2 + 3, fmt(r["total"]) + (f"/{fmt(of)}" if of else ""), "fill-ink2", 8))
        lab = f"{r['label']}: " + ", ".join(
            f"{c['id']} {fmt(r['values'][c['id']]) if r['values'].get(c['id']) is not None else 'n/a'}" for c in cols
        )
        g = "".join(g)
        parts.append(f'<a{attrs} aria-label="{esca(lab)}">{g}</a>' if attrs else f'<g class="row">{g}</g>')
        trs.append(
            [row_cell(r, attrs)]
            + [
                esc(fmt(r["values"][c["id"]]))
                if r["values"].get(c["id"]) is not None
                else ("0" if scale.get("counts") else "n/a")
                for c in cols
            ]
            + ([esc(fmt(r["total"]) + (f"/{fmt(r['of'])}" if r["of"] else ""))] if p["totals"] else [])
        )
    y = y0 + len(rows) * rh + 6
    if p["mean"] or p["column_totals"]:
        parts.append(L(CX, y - 3, CX + cw * len(cols), y - 3, "line-ink2", 0.6))
        label = "Mean" if p["mean"] else "Total"
        parts.append(T(LW, y + 9, label, "fill-ink", FS_S, "end", 600))
        for j in range(len(cols)):
            if p["mean"]:
                v = f"{sums[j] / ns[j]:.2f}" if ns[j] else "–"
            else:
                v = fmt(int(sums[j]))
            parts.append(T(CX + j * cw + cw / 2, y + 9, v, "fill-ink2", 8, "middle", 500))
        y += 18
    items = [("sq", f"q{step}", lab) for lo, hi, lab, step in levels]
    lx, ky = CX, y + 6
    title_txt = "papers per cell" if scale.get("counts") else "score"
    parts.append(T(CX - 8, ky + 8, title_txt, "fill-muted", 8, "end"))
    for _, colour, lab in items:
        parts.append(R(lx, ky, 18, 10, f"fill-{colour}", 2) + T(lx + 22, ky + 8.5, lab, "fill-ink2", 8))
        lx += 22 + tw(lab, 8) + 14
    if any_missing:
        parts.append(
            R(lx, ky, 18, 10, "fill-hatch line-axis", 2, ' stroke-width="0.5"')
            + T(lx + 22, ky + 8.5, "not assessed", "fill-ink2", 8)
        )
    head = (
        ["Row"]
        + [f"{c['id']} {c['label']}".strip() if c["label"] != c["id"] else c["id"] for c in cols]
        + ([p["total_label"]] if p["totals"] else [])
    )
    return svg_wrap(ky + 16, "".join(parts), title), data_table(head, trs), len(rows)


# --------------------------------------------------------------------------- diagrams (hand-made SVG)

SVG_NS = "http://www.w3.org/2000/svg"
GEOM = {"x", "y", "width", "height", "rx", "ry", "cx", "cy", "r", "x1", "y1", "x2", "y2", "dx", "dy"}
PAINT = {
    "class",
    "opacity",
    "stroke-width",
    "stroke-dasharray",
    "stroke-linecap",
    "stroke-linejoin",
    "transform",
    "aria-hidden",
}
ALLOWED = {
    "svg": {"viewBox", "width", "height", "role", "aria-label", "font-size", "xmlns", "version"},
    "g": PAINT | {"font-size", "font-weight", "text-anchor", "aria-label"},
    "title": set(),
    "desc": set(),
    "rect": PAINT | {"x", "y", "width", "height", "rx", "ry"},
    "circle": PAINT | {"cx", "cy", "r"},
    "ellipse": PAINT | {"cx", "cy", "rx", "ry"},
    "line": PAINT | {"x1", "y1", "x2", "y2", "marker-start", "marker-end"},
    "polyline": PAINT | {"points", "marker-start", "marker-end"},
    "polygon": PAINT | {"points"},
    "path": PAINT | {"d", "marker-start", "marker-end"},
    "text": PAINT
    | {
        "x",
        "y",
        "dx",
        "dy",
        "text-anchor",
        "dominant-baseline",
        "font-size",
        "font-weight",
        "font-style",
        "letter-spacing",
    },
    "tspan": {"x", "y", "dx", "dy", "class", "font-size", "font-weight", "font-style", "text-anchor", "baseline-shift"},
    "a": {"data-key", "data-section", "class", "aria-label"},
}
_MARK = {"data-x", "data-y", "data-key", "data-label", "data-series", "data-xaxis", "data-yaxis"}
CUSTOM_ATTRS = {  # extra attributes of a custom chart: data values, ticks, and what a mark belongs to
    "g": {"data-key", "data-label", "data-series", "data-xaxis", "data-yaxis"},
    "circle": _MARK,
    "ellipse": _MARK,
    "rect": _MARK | {"data-base"},
    "line": _MARK | {"data-x1", "data-x2", "data-y1", "data-y2", "data-xtick", "data-ytick"},
    "polyline": {"data-points", "data-key", "data-label", "data-series", "data-xaxis", "data-yaxis"},
    "text": {"data-xtick", "data-ytick", "data-xaxis", "data-yaxis"},
}
CLASS_OK = re.compile(
    r"^(?:(?:fill|line)-(?:[1-8]|q[1-5]|ink2?|muted|grid|axis|wash|panel|surface|none|hatch)"
    r"|on-dark|on-light|on-q[1-5]|halo|hit|cap|dot)$"
)
NUMBER = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)$")
NUMLIST = re.compile(r"^[\d\s.,eE+-]*$")
PATH_D = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz\d\s.,eE+-]*$")
TRANSFORM = re.compile(r"^(?:\s*(?:translate|rotate|scale)\(\s*-?[\d.]+(?:[\s,]+-?[\d.]+){0,2}\s*\)\s*)+$")
MARKER_REF = re.compile(r"^url\(#fg-(?:arrow|arrow-muted)\)$")
ENUMS = {
    "text-anchor": {"start", "middle", "end"},
    "dominant-baseline": {"auto", "middle", "central", "hanging"},
    "font-weight": {"400", "500", "600", "700", "normal", "bold"},
    "font-style": {"normal", "italic"},
    "stroke-linecap": {"butt", "round", "square"},
    "stroke-linejoin": {"miter", "round", "bevel"},
    "role": {"img"},
    "aria-hidden": {"true", "false"},
    "baseline-shift": {"super", "sub"},
}


def local(tag):
    if tag.startswith("{"):
        ns, name = tag[1:].split("}", 1)
        return name if ns == SVG_NS else None
    return tag


def check_attr(tag, name, value, chk, where):
    if name in GEOM or name in {"font-size", "opacity", "stroke-width", "letter-spacing"}:
        v = value.strip().rstrip("px")
        if not NUMBER.match(v):
            chk(f'{where}: {name}="{value}" is not a number')
            return None
        if name == "font-size" and float(v) < FS_MIN:
            chk(f"{where}: font-size {v} is below {FS_MIN} (unreadable once scaled)")
        return v
    if name in ("points", "stroke-dasharray"):
        return value if NUMLIST.match(value) else chk(f"{where}: {name} must be numbers")
    if name == "d":
        return value if PATH_D.match(value) else chk(f"{where}: path data has unexpected characters")
    if name == "transform":
        return value if TRANSFORM.match(value) else chk(f"{where}: transform must be translate/rotate/scale")
    if name in ("marker-start", "marker-end"):
        return (
            value
            if MARKER_REF.match(value.strip())
            else chk(f"{where}: {name} may only be url(#fg-arrow) or url(#fg-arrow-muted)")
        )
    if name == "class":
        bad = [c for c in value.split() if not CLASS_OK.match(c)]
        if bad:
            chk(
                f"{where}: unknown class {', '.join(bad)} (colours come from fill-N, line-N, fill-ink ... see GUIDE.md)"
            )
            return None
        return value
    if name in ENUMS:
        return value if value in ENUMS[name] else chk(f'{where}: {name}="{value}" not allowed')
    if name == "viewBox":
        return value
    return value


MARK_TAGS = ("circle", "ellipse", "rect", "line", "polyline")
MARK_DATA = ("data-x", "data-y", "data-x1", "data-x2", "data-y1", "data-y2", "data-points")
INHERIT = ("data-key", "data-label", "data-series", "data-xaxis", "data-yaxis")
TOL = 1.0  # SVG units: a mark may sit at most this far from where its value belongs
TRANSLATE = re.compile(r"^\s*(?:translate\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+))?\s*\)\s*)+$")


def parse_axes(raw, chk):
    """{"x": {"data": [lo, hi], "px": [p0, p1], "label", "log"}, "y": {...}, "x2": ...} -> dict, or None."""
    if not isinstance(raw, dict) or not raw:
        chk(
            'axes: a custom figure declares its axes, e.g. {"x": {"data": [2016, 2026], "px": [60, 660], '
            '"label": "Year"}, "y": {"data": [0, 6], "px": [300, 40], "label": "Gain (dB)"}}'
        )
        return None
    axes = {}
    for name, a in raw.items():
        where = f'axis "{name}"'
        if not re.fullmatch(r"[xy]\d?", str(name)):
            chk(f"{where}: axis names are x, y, or x2, y2 ... for more panels")
            continue
        if not isinstance(a, dict):
            chk(f"{where}: expected an object")
            continue
        data, px = a.get("data"), a.get("px")
        if not (isinstance(data, list) and len(data) == 2 and all(is_num(v) for v in data) and data[0] != data[1]):
            chk(f'{where}: "data" must be two different numbers, the values at the two ends of the axis')
            continue
        if not (isinstance(px, list) and len(px) == 2 and all(is_num(v) for v in px) and px[0] != px[1]):
            chk(f'{where}: "px" must be two different SVG coordinates, where those two values are drawn')
            continue
        log = bool(a.get("log"))
        if log and min(data) <= 0:
            chk(f"{where}: a log axis needs positive values")
            continue
        chk.text(a.get("label", ""), f"{where} label")
        axes[str(name)] = {"name": str(name), "data": data, "px": px, "log": log, "label": str(a.get("label") or "")}
    return axes


def to_px(ax, v):
    (lo, hi), (p0, p1) = ax["data"], ax["px"]
    if ax["log"]:
        if v <= 0:
            return float("nan")
        t = (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    else:
        t = (v - lo) / (hi - lo)
    return p0 + t * (p1 - p0)


def near(a, b, tol=TOL):
    return a == a and b == b and abs(a - b) <= tol


def fval(s):
    """A data value as written in the SVG (accepts the true minus sign)."""
    return float(str(s).strip().replace("−", "-").replace(",", ""))


def first_number(text):
    m = NUM.search(text or "")
    return fval(m.group(0)) if m else None


class Positions:
    """Checks that the data marks and ticks of a custom figure sit where their values belong on the declared axes."""

    def __init__(self, axes, chk):
        self.axes, self.chk, self.ticks, self.used = axes, chk, {}, set()

    def axis(self, letter, inh, where):
        name = inh.get(f"data-{letter}axis") or letter
        ax = self.axes.get(name)
        if ax is None:
            self.chk(f'{where}: no axis "{name}" in "axes"')
        return ax

    def mark(self, tag, el, vals, inh, ox, oy, where, key):
        chk, fields = self.chk, {}
        for name in (*MARK_DATA[:-1], "data-base"):
            if name in vals:
                try:
                    fields[name[5:]] = fval(vals[name])
                except ValueError:
                    chk(f'{where}: {name}="{vals[name]}" is not a number')
                    return None
        for f, v in fields.items():
            if f != "base":
                chk.value(v, f"{where} {f}", key)

        def geo(name):
            try:
                return float(el.get(name, "0"))
            except ValueError:
                return float("nan")

        def need(actual, letter, v, label):
            ax = self.axis(letter, inh, where)
            if ax is None:
                return
            self.used.add(ax["name"])
            exp = to_px(ax, v)
            if not near(actual, exp):
                chk(f'{where}: {label} is drawn at {actual:.1f}, but {fmt(v)} on axis "{ax["name"]}" is at {exp:.1f}')

        if tag in ("circle", "ellipse"):
            if set(fields) - {"x", "y"}:
                chk(f"{where}: a {tag} takes data-x and data-y only")
            if "x" in fields:
                need(geo("cx") + ox, "x", fields["x"], "cx")
            if "y" in fields:
                need(geo("cy") + oy, "y", fields["y"], "cy")
        elif tag == "rect":
            if set(fields) - {"x", "y", "base"}:
                chk(f"{where}: a rect takes data-x or data-y, and data-base for the bar's other end")
            if "base" in fields and "x" in fields and "y" in fields:
                chk(f"{where}: data-base needs one of data-x or data-y, not both")
            for letter, start, size in (("x", "x", "width"), ("y", "y", "height")):
                if letter not in fields:
                    continue
                ax = self.axis(letter, inh, where)
                if ax is None:
                    continue
                self.used.add(ax["name"])
                a = geo(start) + (ox if letter == "x" else oy)
                b = a + geo(size)
                exp = to_px(ax, fields[letter])
                if not (near(a, exp) or near(b, exp)):
                    chk(
                        f"{where}: neither edge ({a:.1f}, {b:.1f}) of the bar is at {exp:.1f}, where "
                        f'{fmt(fields[letter])} sits on axis "{ax["name"]}"'
                    )
                elif "base" in fields:
                    base = to_px(ax, fields["base"])
                    other = b if near(a, exp) else a
                    if not near(other, base):
                        chk(
                            f"{where}: the bar should end at {base:.1f} (data-base {fmt(fields['base'])}), "
                            f"not {other:.1f}"
                        )
        elif tag == "line":
            if "base" in fields:
                chk(f"{where}: a line takes data-x, data-y, data-x1, data-x2, data-y1, data-y2")
            x1, x2, y1, y2 = geo("x1") + ox, geo("x2") + ox, geo("y1") + oy, geo("y2") + oy
            if "x" in fields:
                need(x1, "x", fields["x"], "x1")
                need(x2, "x", fields["x"], "x2")
            if "y" in fields:
                need(y1, "y", fields["y"], "y1")
                need(y2, "y", fields["y"], "y2")
            for f, actual, letter in (("x1", x1, "x"), ("x2", x2, "x"), ("y1", y1, "y"), ("y2", y2, "y")):
                if f in fields:
                    need(actual, letter, fields[f], f)
        elif tag == "polyline":
            if fields:
                chk(f"{where}: a polyline takes data-points only")
            try:
                pairs = [tuple(fval(v) for v in p.split(",")) for p in str(vals.get("data-points", "")).split()]
                pts = [float(v) for v in re.split(r"[\s,]+", (el.get("points") or "").strip()) if v]
            except ValueError:
                chk(f'{where}: data-points must be "x,y x,y ..." values')
                return None
            if not pairs or any(len(p) != 2 for p in pairs) or len(pts) != 2 * len(pairs):
                chk(f'{where}: data-points must give one "x,y" value pair per point of the polyline')
                return None
            for i, (vx, vy) in enumerate(pairs):
                chk.value(vx, f"{where} point {i + 1} x", key)
                chk.value(vy, f"{where} point {i + 1} y", key)
                need(pts[2 * i] + ox, "x", vx, f"point {i + 1} x")
                need(pts[2 * i + 1] + oy, "y", vy, f"point {i + 1} y")
            fields["points"] = " ".join(f"{fmt(a)}, {fmt(b)}" for a, b in pairs)
        return fields

    def tick(self, tag, el, letter, value, inh, ox, oy, where, text):
        chk = self.chk
        try:
            v = fval(value)
        except ValueError:
            chk(f'{where}: data-{letter}tick="{value}" is not a number')
            return
        ax = self.axis(letter, inh, where)
        if ax is None:
            return
        exp = to_px(ax, v)
        if tag == "line":
            a1, a2 = (float(el.get(f"{letter}1", "0")), float(el.get(f"{letter}2", "0")))
            off = ox if letter == "x" else oy
            if not (near(a1 + off, exp) and near(a2 + off, exp)):
                chk(f'{where}: the tick for {fmt(v)} should run along {letter} = {exp:.1f} (axis "{ax["name"]}")')
                return
        else:
            if letter == "x":
                if (el.get("text-anchor") or inh.get("text-anchor")) != "middle":
                    chk(f'{where}: a tick label on an x axis needs text-anchor="middle"')
                    return
                if not near(float(el.get("x", "0")) + ox, exp, 2):
                    chk(f"{where}: the label of tick {fmt(v)} should be centred at x = {exp:.1f}")
                    return
            else:
                dy = float(el.get("y", "0")) + oy - exp
                if not -4 <= dy <= 8:
                    chk(f"{where}: the label of tick {fmt(v)} should sit at y = {exp:.1f} (its baseline 0 to 6 below)")
                    return
            n = first_number(text)
            if n is None or abs(n - v) > 1e-9 * max(1, abs(v)):
                chk(f'{where}: the tick label "{text.strip()}" does not read {fmt(v)}')
                return
        self.ticks.setdefault(ax["name"], set()).add(v)


def sanitize_svg(text, chk, ctx, h2, h3, title, axes=None, marks=None):
    """The diagram (or custom chart, with `axes`) as safe inline SVG, or None. Refuses (never strips) anything
    outside the allowlist. For a custom chart, every data mark and tick must sit where its value belongs on the
    declared axes; `marks` collects the marks for the data table."""
    if len(text.encode("utf-8")) > 200_000:
        chk("the SVG is larger than 200 KB")
        return None
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        chk("the SVG must not contain a DOCTYPE or entities")
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        chk(f"the SVG is not well-formed XML ({e})")
        return None
    if local(root.tag) != "svg":
        chk("the file must start with an <svg> element")
        return None
    vb = (root.get("viewBox") or "").split()
    try:
        vw, vh = float(vb[2]), float(vb[3])
        if vb[0] != "0" or vb[1] != "0" or not (300 <= vw <= 1000) or not (40 <= vh <= 1600):
            raise ValueError
    except (IndexError, ValueError):
        chk('viewBox must be "0 0 <width> <height>", width 300 to 1000 (680 recommended), height up to 1600')
        return None
    count = [0]
    pos = Positions(axes, chk) if axes is not None else None
    marks = marks if marks is not None else []

    def emit(el, depth, inh):
        count[0] += 1
        tag = local(el.tag)
        where = f"<{tag or el.tag}>"
        if tag is None or tag not in ALLOWED:
            chk(f"element {el.tag} is not allowed (allowed: {', '.join(sorted(ALLOWED))})")
            return ""
        if depth > 0 and tag == "svg":
            chk("nested <svg> is not allowed")
            return ""
        attrs, data, link_attrs = [], {}, ""
        allowed_here = ALLOWED[tag] | (
            CUSTOM_ATTRS.get(tag, set()) if axes is not None else ({"data-key"} if tag in ("g", *MARK_TAGS) else set())
        )
        for name, value in el.attrib.items():
            if name.startswith("{"):
                chk(f"{where}: namespaced attribute {name} is not allowed")
                continue
            if name in ("fill", "stroke"):
                if value.strip() == "none":
                    attrs.append(f'{name}="none"')
                    continue
                chk(
                    f'{where}: {name}="{value}": colours come from classes (fill-N, line-N, fill-ink ...), not '
                    f"attributes"
                )
                continue
            if name == "style" or name.lower().startswith("on") or name in ("href", "id"):
                chk(f"{where}: attribute {name} is not allowed")
                continue
            if name not in allowed_here:
                hint = ' (data values are for figures of type "custom")' if name.startswith("data-") else ""
                chk(f"{where}: attribute {name} is not allowed on <{tag}>{hint}")
                continue
            if tag == "svg" and name in ("width", "height", "xmlns", "version", "font-size", "role", "aria-label"):
                continue
            if name.startswith("data-") and name != "data-section":
                data[name] = value.strip()
                continue
            if name == "data-section":
                link_attrs = f' href="#@@SEC:{esca(value.strip())}@@"'
                continue
            v = check_attr(tag, name, value, chk, where)
            if v is not None:
                attrs.append(f'{name}="{esca(v)}"')
        inh = dict(inh)
        for k in INHERIT:
            if k in data:
                inh[k] = data[k]
        if el.get("text-anchor"):
            inh["text-anchor"] = el.get("text-anchor")
        tr = el.get("transform")
        if tr:
            m = TRANSLATE.match(tr)
            if m:
                for t in re.finditer(r"translate\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+))?\s*\)", tr):
                    inh["ox"] += float(t.group(1))
                    inh["oy"] += float(t.group(2) or 0)
            else:
                inh["warped"] = True
        key = inh.get("data-key")
        own_key = data.get("data-key")
        if own_key and ctx.check and own_key not in (ctx.citemap or {}):
            chk(f'{where}: data-key "{own_key}" is not in citation_map.tsv')
            own_key = None
        fields = None
        if tag in MARK_TAGS and any(k in data for k in MARK_DATA):
            if pos is None:
                chk(f'{where}: data values are for figures of type "custom"')
            elif inh["warped"]:
                chk(f"{where}: a data mark must not sit in a rotated or scaled group")
            else:
                fields = pos.mark(tag, el, data, inh, inh["ox"], inh["oy"], where, key)
        elif "data-base" in data:
            chk(f"{where}: data-base belongs on a bar (rect) with data-x or data-y")
        for letter in ("x", "y"):
            tv = data.get(f"data-{letter}tick")
            if tv is not None:
                if pos is None:
                    chk(f'{where}: ticks are for figures of type "custom"')
                elif inh["warped"]:
                    chk(f"{where}: a tick must not sit in a rotated or scaled group")
                else:
                    pos.tick(tag, el, letter, tv, inh, inh["ox"], inh["oy"], where, "".join(el.itertext()))
        if tag == "a" and not own_key and not link_attrs:
            if not el.get("data-section"):
                chk("<a> needs data-key (a paper of the citation map) or data-section (a heading of the review)")
            return "".join(emit(c, depth + 1, inh) + esc(c.tail or "") for c in el)
        if tag == "text" and ctx.base is not None and not any(f"data-{ln}tick" in data for ln in "xy"):
            own = "".join(el.itertext())
            ok = ctx.allowed(key)
            miss = [x for x in NUM.findall(own) if norm_num(x) not in ok]
            if miss:
                whose = f", counts.json or the record of {key}" if key else " or counts.json"
                chk(f'text "{own.strip()[:60]}": {", ".join(miss)} not in the review{whose}')
        inner = esc(el.text or "") + "".join(emit(c, depth + 1, inh) + esc(c.tail or "") for c in el)
        if tag == "svg":
            return (
                f'<svg viewBox="0 0 {vb[2]} {vb[3]}" xmlns="http://www.w3.org/2000/svg" role="img" '
                f'aria-label="{esca(title)}" font-size="{FS}">{inner}</svg>'
            )
        a = (" " + " ".join(attrs)) if attrs else ""
        label = inh.get("data-label") or (ctx.label(key) if key else "")
        summary = ""
        if fields is not None:
            summary = (label + ": " if label else "") + "; ".join(
                f"{f} {v if f == 'points' else fmt(v)}" for f, v in fields.items() if f != "base"
            )
        if own_key:
            words = " ".join(el.itertext()) or summary
            link_attrs, _ = ctx.link(own_key, h2, h3, f"{ctx.label(own_key)} | {label} | {words} | {title}")
        if fields is not None:
            marks.append(
                {
                    "key": key,
                    "label": label or "",
                    "series": inh.get("data-series") or "",
                    "fields": fields,
                    "attrs": link_attrs if own_key else "",
                    "xaxis": inh.get("data-xaxis"),
                    "yaxis": inh.get("data-yaxis"),
                }
            )
        if tag == "a":
            return f"<a{link_attrs}{a}>{inner}</a>"
        shape = (
            f"<{tag}{a}>{inner}</{tag}>" if inner or tag in ("text", "tspan", "title", "desc", "g") else f"<{tag}{a}/>"
        )
        if own_key and link_attrs:
            tip = f"<title>{esc(summary)}</title>" if summary else ""
            return f'<a{link_attrs} aria-label="{esca(summary or label)}">{tip}{shape}</a>'
        if summary:
            return f'<g class="row"><title>{esc(summary)}</title>{shape}</g>'
        return shape

    out = emit(root, 0, {"ox": 0.0, "oy": 0.0, "warped": False})
    if count[0] > 4000:
        chk("the SVG has more than 4,000 elements")
    if pos is not None:
        if not marks:
            chk(
                "a custom figure needs at least one data mark (data-x, data-y ... on a circle, rect, line or "
                'polyline); a figure without data is a "diagram"'
            )
        for name in sorted(pos.used):
            if len(pos.ticks.get(name, ())) < 2:
                chk(
                    f'axis "{name}": mark at least two ticks with data-{name[0]}tick (a tick line or a centred '
                    f"label), so that the drawn scale can be checked"
                )
    return out


POINT_PAIR = re.compile(r"(\S+), (\S+)")


def custom_table(marks, axes):
    """The data table of a custom figure, from its marks. Values go in one column per axis label, so that panels
    on different scales (acceleration R in one, spokes per frame in another) never share a column; a polyline whose
    every point is also a dot of the same mark and series is not listed again."""

    def ax_label(m, letter):
        name = m.get(f"{letter}axis") or letter
        return (axes.get(name) or {}).get("label") or name

    def ident(m):
        return m["label"], m["series"], ax_label(m, "x"), ax_label(m, "y")

    dots = {
        (*ident(m), fmt(m["fields"]["x"]), fmt(m["fields"]["y"]))
        for m in marks
        if "x" in m["fields"] and "y" in m["fields"]
    }

    def repeated(m):
        pts = POINT_PAIR.findall(m["fields"].get("points") or "")
        return bool(pts) and all(ident(m) + p in dots for p in pts)

    shown = [m for m in marks if not repeated(m)]

    cols = []
    for m in shown:
        for f in m["fields"]:
            if f not in ("base", "points"):
                col = (f[0], f[1:], ax_label(m, f[0]))
                if col not in cols:
                    cols.append(col)
    cols.sort(key=lambda c: (c[0], c[1]))  # x before y, the value before a line's start and end; stable otherwise
    pairs = {(ax_label(m, "x"), ax_label(m, "y")) for m in shown if "points" in m["fields"]}
    pts_head = "Points ({}; {})".format(*next(iter(pairs))) if len(pairs) == 1 else "Points (x, y)"

    def head(c):
        return c[2] + {"1": " (start)", "2": " (end)"}.get(c[1], "")

    has_series = any(m["series"] for m in shown)
    has_points = bool(pairs)
    rows = []
    for m in shown:
        r = {"label": m["label"] or "–"}
        cells = [row_cell(r, m["attrs"])] + ([esc(m["series"])] if has_series else [])
        for c in cols:
            f = c[0] + c[1]
            v = m["fields"].get(f) if ax_label(m, c[0]) == c[2] else None
            cells.append("" if v is None else esc(fmt(v)))
        if has_points:
            cells.append(esc(m["fields"].get("points") or ""))
        rows.append(cells)
    return data_table(
        ["Mark"] + (["Series"] if has_series else []) + [head(c) for c in cols] + ([pts_head] if has_points else []),
        rows,
    )


# --------------------------------------------------------------------------- one figure

DRAW = {
    "dots": (prep_dots, draw_dots),
    "bars": (prep_bars, draw_bars),
    "columns": (prep_columns, draw_columns),
    "scatter": (prep_scatter, draw_scatter),
    "heatmap": (prep_heatmap, draw_heatmap),
}


def prepare(fig, ctx, fig_dir=None):
    """Check one figure spec. Returns (prepared, problems)."""
    chk = Checker(ctx)
    if not isinstance(fig, dict):
        return None, ["expected an object"]
    fid = fig.get("id")
    if not isinstance(fid, str) or not ID_RX.match(fid):
        chk('id: lowercase letters, digits and hyphens (e.g. "rigor-scores")')
    t = fig.get("type")
    if t not in TYPES:
        chk(f"type must be one of {', '.join(TYPES)}")
        return None, chk.bad
    for f in ("title", "caption"):
        if not isinstance(fig.get(f), str) or not fig[f].strip():
            chk(f"{f}: required text")
    prep = {
        "id": fid,
        "type": t,
        "title": str(fig.get("title") or "").strip(),
        "caption": str(fig.get("caption") or "").strip(),
        "alt": str(fig.get("alt") or ""),
        "mention": fig.get("mention") if isinstance(fig.get("mention"), str) else "",
    }
    place = fig.get("place") if isinstance(fig.get("place"), dict) else {}
    prep["place"] = {"section": str(place.get("section") or ""), "after": str(place.get("after") or "paragraph")}
    if ctx.check:
        if not prep["place"]["section"]:
            chk("place.section: the review heading the figure goes under")
            sec = None
        else:
            sec = find_section(ctx.md_text, prep["place"]["section"])
            if sec is None:
                chk(f'place.section "{prep["place"]["section"]}" is not a heading of review.md')
            else:
                why = anchor_problem(ctx.md_text, prep["place"])
                if why:
                    chk(why)
        src = fig.get("source") if isinstance(fig.get("source"), dict) else {}
        if src.get("section"):
            s2 = find_section(ctx.md_text, src["section"])
            if s2 is None:
                chk(f'source.section "{src["section"]}" is not a heading of review.md')
            sec = s2 or sec
            if src.get("subsection"):
                s3 = find_section(ctx.md_text, src["subsection"])
                if s3 is None:
                    chk(f'source.subsection "{src["subsection"]}" is not a heading of review.md')
                elif s3[1]:
                    sec = s3
        prep["h2"], prep["h3"] = sec or ("", "")
    else:
        prep["h2"], prep["h3"] = "", ""
    if t in ("diagram", "custom"):
        axes = None
        if t == "custom":
            axes = parse_axes(fig.get("axes"), chk)
            prep["axes"] = axes or {}
        name = fig.get("file")
        if not isinstance(name, str) or not re.fullmatch(r"[\w.-]+\.svg", name):
            chk("file: the name of an .svg file in 5-final/figures/")
        else:
            path = os.path.join(fig_dir or "", name)
            if not os.path.exists(path):
                chk(f"file {name} not found in {fig_dir}")
            else:
                with open(path, encoding="utf-8") as fh:
                    prep["svg_text"] = fh.read()
                # a dry run catches every problem before any link is drawn
                dry = copy.copy(ctx)
                dry.linker, dry.links = None, []
                if t == "diagram" or axes:
                    marks = []
                    sanitize_svg(prep["svg_text"], chk, dry, prep["h2"], prep["h3"], prep["title"], axes, marks)
                    prep["n_marks"] = len(marks)
        prep["computed"] = set()
    else:
        p = DRAW[t][0](fig, chk)
        if p is None and not chk.bad:
            chk("nothing to draw")
        prep["data"] = p
        prep["computed"] = (p or {}).get("computed") or set()
    for f in ("title", "caption", "alt", "mention"):
        chk.text(prep[f], f, extra=prep["computed"])
    if prep["mention"] and "{n}" not in prep["mention"]:
        chk('mention: must contain {n} where the figure number goes, e.g. "Figure {n} plots every comparison."')
    if prep["mention"] and prep["place"]["after"].strip().lower() in ("heading", "table"):
        chk(
            "mention: a figure placed after a heading or a table follows no paragraph; drop the mention or place "
            "the figure after a paragraph"
        )
    return prep, chk.bad


def caption_html(prep, ids):
    """The caption with [text](#heading) links resolved; numbers are already checked."""

    def link(m):
        text, target = m.group(1), m.group(2)
        hid = ids.get(norm_head(target)) or (target if target in ids.values() else None)
        return f'<a class="figref" href="#{esca(hid)}">{esc(text)}</a>' if hid else esc(text)

    out, pos = [], 0
    cap = prep["caption"]
    for m in re.finditer(r"\[([^\]]+)\]\(#([^)]+)\)", cap):
        out.append(esc(cap[pos : m.start()]))
        out.append(link(m))
        pos = m.end()
    out.append(esc(cap[pos:]))
    text = "".join(out)
    return re.sub(r"\{fig:([a-z0-9-]+)\}", lambda m: f"@@FIGREF:{m.group(1)}@@", text)


def render(prep, ctx):
    """(figure html, n rows or points). Draws the links (each one adds a popover entry)."""
    fid, title = prep["id"], prep["title"]
    label = prep["alt"] or title
    if prep["type"] in ("diagram", "custom"):
        chk = Checker(ctx)
        axes = prep.get("axes") if prep["type"] == "custom" else None
        marks = []
        svg = sanitize_svg(prep["svg_text"], chk, ctx, prep["h2"], prep["h3"], label, axes, marks)
        table = custom_table(marks, axes) if axes and marks else ""
        n = len(marks)
    else:
        svg, table, n = DRAW[prep["type"]][1](prep["data"], ctx, prep["h2"], prep["h3"], label)
    t = title if re.search(r"[.!?]$", title) else title + "."
    details = (
        (f'\n<details class="figdata"><summary>Data behind the figure</summary><div class="tw">{table}</div></details>')
        if table
        else ""
    )
    return (
        f'<figure class="fig" id="fig-{fid}"><div class="figscroll">{svg}</div>'
        '<p class="fighint">Scroll sideways to see the whole figure →</p>'
        f"<figcaption><b>Figure @@FIG:{fid}@@. {esc(t)}</b> @@CAP:{fid}@@</figcaption>{details}</figure>"
    ), n


# --------------------------------------------------------------------------- the review's figures


def load_spec(rdir):
    """(list of figure specs or None when the review has none, problems)."""
    p = os.path.join(str(rdir), SPEC)
    if not os.path.exists(p):
        return None, []
    try:
        with open(p, encoding="utf-8") as fh:
            obj = json.load(fh)
    except ValueError as e:
        return [], [f"figures.json is not valid JSON ({e})"]
    figs = obj.get("figures") if isinstance(obj, dict) else obj
    if not isinstance(figs, list):
        return [], ['figures.json: expected {"figures": [ ... ]}']
    return figs, []


HEAD_HTML = re.compile(r'<h([234]) id="([^"]+)">(.*?)</h\1>', re.S)
P_HTML = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.S)
CONTAINER = re.compile(r"<(/?)(ul|ol|blockquote|aside|details|div|table|figure)\b[^>]*>")


def head_text(inner):
    inner = re.sub(r'<span class="secnum">[^<]*</span>\s*', "", inner)
    return html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()


def heading_ids(body):
    return {norm_head(head_text(m.group(3))): m.group(2) for m in HEAD_HTML.finditer(body)}


def outer_end(body, start, pos):
    """If pos lies inside a container opened after `start`, the end of the outermost one; else pos."""
    stack = []
    for m in CONTAINER.finditer(body, start, pos):
        if m.group(1):
            if stack and stack[-1][0] == m.group(2):
                stack.pop()
        else:
            stack.append((m.group(2), m.start()))
    if not stack:
        return pos
    name, depth = stack[0][0], 0
    for m in CONTAINER.finditer(body, stack[0][1]):
        if m.group(2) != name:
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()
    return pos


def insertion_point(body, place):
    """(position, paragraph end or None) for a figure placed under `place`, or None."""
    want = norm_head(place["section"])
    heads = list(HEAD_HTML.finditer(body))
    for i, m in enumerate(heads):
        if norm_head(head_text(m.group(3))) != want:
            continue
        level = int(m.group(1))
        end = next((h.start() for h in heads[i + 1 :] if int(h.group(1)) <= level), None)
        if end is None:
            nxt = re.search(r"<h2 id=", body[m.end() :])
            end = m.end() + nxt.start() if nxt else len(body)
        pos = m.end()
        aside = re.match(r'\s*<aside class="keypoints".*?</aside>', body[pos:end], re.S)
        if aside:
            pos += aside.end()
        after = place["after"].strip()
        if after.lower() == "heading":
            return pos, None
        if after.lower() == "table":
            t = re.search(r"</table>\s*</div>", body[pos:end])
            if not t:
                return None
            return pos + t.end(), None
        want_p = plain_md(after).lower()
        for pm in P_HTML.finditer(body, pos, end):
            text = re.sub(r"\s+", " ", markdown.plain_text(pm.group(1))).strip().lower()
            if after.lower() == "paragraph" or text.startswith(want_p):
                at = outer_end(body, m.end(), pm.end())
                return at, (pm.end() if at == pm.end() else None)
        return None
    return None


def skip_figures(body, pos):
    while True:
        m = re.match(r'\s*<figure class="fig".*?</figure>', body[pos:], re.S)
        if not m:
            return pos
        pos += m.end()


def place_all(body, rdir, review, linker, data, md_text, counts):
    """Insert the review's figures into the page body. Returns (body, result) where result is None when the review
    has no figures.json, else {'n', 'links', 'refused', 'summary', 'kinds'}."""
    figs, problems = load_spec(rdir)
    if figs is None:
        return body, None
    ctx = Ctx.for_review(rdir, review, md_text, counts, linker, data)
    res = {"n": 0, "links": 0, "refused": [f"figures: {p}" for p in problems], "summary": [], "kinds": {}}
    if len(figs) > MAX_FIGURES:
        res["refused"].append(f"figures: {len(figs)} figures, at most {MAX_FIGURES}")
    preps, seen = [], set()
    for i, fig in enumerate(figs):
        prep, bad = prepare(fig, ctx, os.path.join(str(rdir), FIG_DIR))
        name = (prep or {}).get("id") or f"#{i + 1}"
        if name in seen:
            bad.append("id used twice")
        seen.add(name)
        if not bad and insertion_point(body, prep["place"]) is None:
            bad.append(
                f'place: no paragraph "{prep["place"]["after"]}" under heading "{prep["place"]["section"]}"'
                if prep["place"]["after"].lower() not in ("heading", "paragraph", "table")
                else f'place: nothing to put it after ({prep["place"]["after"]}) under "{prep["place"]["section"]}"'
            )
        res["refused"] += [f'figure "{name}": {b}' for b in bad]
        preps.append(prep)
    if res["refused"]:
        return body, res
    ids = heading_ids(body)
    for prep in preps:
        fig_html, n = render(prep, ctx)
        pos, par_end = insertion_point(body, prep["place"])
        if prep["mention"] and par_end is not None:
            mention = esc(prep["mention"])
            mention = re.sub(r"(?:Figure\s+)?\{n\}", f"@@FIGREF:{prep['id']}@@", mention)
            close = par_end - len("</p>")
            body = body[:close] + " " + mention + body[close:]
            pos += len(mention) + 1
        pos = skip_figures(body, pos)
        body = body[:pos] + "\n" + fig_html + "\n" + body[pos:]
        body = body.replace(f"@@CAP:{prep['id']}@@", caption_html(prep, ids), 1)
        res["summary"].append((prep["id"], prep["type"], n, sorted(prep["computed"], key=float)))
    order = re.findall(r'<figure class="fig" id="fig-([a-z0-9-]+)"', body)
    number = {fid: i + 1 for i, fid in enumerate(order)}

    def tok(m):
        fid = m.group(2)
        if fid not in number:
            return "Figure ?"
        return f'<a class="figref" href="#fig-{fid}">Figure {number[fid]}</a>' if m.group(1) else str(number[fid])

    body = FIG_TOKEN.sub(tok, body)
    body = re.sub(
        r'href="#@@SEC:([^"@]*)@@"', lambda m: f'href="#{ids.get(norm_head(html.unescape(m.group(1))), "")}"', body
    )
    first = body.find('<figure class="fig"')
    if first >= 0:
        body = body[:first] + DEFS + "\n" + body[first:]
    res["n"] = len(order)
    res["links"] = len(ctx.links)
    for l_ in ctx.links:
        res["kinds"][l_["type"]] = res["kinds"].get(l_["type"], 0) + 1
    res["link_list"] = ctx.links
    return body, res


def css():
    with open(os.path.join(HERE, "figures.css"), encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- standalone pages (preview, gallery)


def standalone(figs_html, title, note=""):
    with open(os.path.join(HERE, "webpage.css"), encoding="utf-8") as fh:
        base = fh.read()
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<script>
try {{
  const q = new URLSearchParams(location.search);
  if (q.get('theme')) document.documentElement.dataset.theme = q.get('theme');
  window.ONLY = q.get('only');
}} catch (e) {{}}
</script>
<style>{base}
{css()}
main.gallery {{ max-width: 960px; margin: 0 auto; padding: 28px 20px 60px; }}
main.gallery h1 {{ font: 700 28px/1.2 var(--sans); margin: 0 0 6px; }}
main.gallery .note {{ font: 14px/1.5 var(--sans); color: var(--ink2); max-width: 680px; }}
main.gallery .fname {{ font: 12px/1.4 ui-monospace, Menlo, monospace; color: var(--muted); margin: 26px 0 -20px; }}
</style>
</head>
<body>
<main class="gallery">
<h1>{esc(title)}</h1>
<p class="note">{note}</p>
{figs_html}
</main>
<script>
if (window.ONLY) document.querySelectorAll('figure.fig').forEach(f => {{
  if (f.id !== 'fig-' + window.ONLY) {{ f.style.display = 'none'; const n = f.previousElementSibling;
    if (n && n.classList.contains('fname')) n.style.display = 'none'; }}
}});
if (window.ONLY) document.querySelectorAll('main.gallery > h1, main.gallery > .note').forEach(e => e.style.display = 'none');
</script>
</body>
</html>"""


def render_list(figs, ctx, fig_dir):
    """Figures one after another (no review around them). Returns (html, refused, [(id, height)])."""
    out, refused, sizes = [], [], []
    for i, fig in enumerate(figs):
        prep, bad = prepare(fig, ctx, fig_dir)
        name = (prep or {}).get("id") or f"#{i + 1}"
        if bad:
            refused += [f'figure "{name}": {b}' for b in bad]
            continue
        h, _ = render(prep, ctx)
        h = h.replace(f"@@FIG:{prep['id']}@@", str(i + 1)).replace(f"@@CAP:{prep['id']}@@", caption_html(prep, {}))
        h = FIG_TOKEN.sub(lambda m: f"Figure {m.group(2)}", h)
        vb = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"', h)
        sizes.append((prep["id"], float(vb.group(2)) / float(vb.group(1)) if vb else 0.6))
        out.append(f'<p class="fname">{esc(prep["id"])} · {esc(prep["type"])}</p>\n{h}')
    return DEFS + "\n" + "\n".join(out), refused, sizes
