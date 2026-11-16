"""Zotero snapshot (local API, read-only) and the choice of link for every citation.

For each citation instance the chooser picks the review highlight that best matches the sentence or table cell
that cites the paper: section bracket of the highlight's comment ("[Review › Section] ..."), shared numbers,
shared words and colour. Without a confident match the link opens the PDF, and papers without a PDF in Zotero
keep their citation-map link. Zotero content is treated as data.

Link format (Zotero 7): zotero://open-pdf/library/items/<attachment>?page=<1-based>&annotation=<key> lands on the
highlight (annotation= alone is enough; page= is a fallback).
"""

import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

DEFAULT_API = "http://localhost:23119/api/users/0"
COLOURS = {"#ffd400": "yellow", "#2ea8e5": "blue", "#5fb236": "green", "#ff6666": "red", "#a28ae5": "purple"}
KNOWN_COLOURS = set(COLOURS.values()) | {"other"}
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
BRACKET = re.compile(r"^\s*\[(?:Review\s*›\s*)?([^\]]*)\]")
NUM = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?")
# Words that mark a limitation in the citing sentence (regex alternatives); review.json edition.limit_words
# replaces the list.
LIMIT_WORDS = [
    "only",
    "without",
    "not",
    "no",
    r"confound\w*",
    "unmatched",
    "simulated",
    "magnitude",
    "under-tuned",
    "inconsistent",
    r"lack\w*",
    "missing",
    "unequal",
    "red flag",
    "caveat",
    r"disagree\w*",
    "shrinks?",
    r"vanish\w*",
]
RESULT = re.compile(r"\d\s*(dB|%)|SSIM|PSNR|NMSE|\b\d+\.\d+\b")
STOP = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "among",
    "because",
    "before",
    "being",
    "below",
    "between",
    "could",
    "doing",
    "during",
    "each",
    "either",
    "every",
    "first",
    "from",
    "further",
    "having",
    "into",
    "itself",
    "just",
    "less",
    "more",
    "most",
    "much",
    "other",
    "ought",
    "over",
    "same",
    "should",
    "since",
    "some",
    "such",
    "than",
    "that",
    "their",
    "theirs",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "until",
    "very",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "whose",
    "with",
    "within",
    "without",
    "would",
    "your",
    "paper",
    "papers",
    "review",
    "model",
    "models",
    "network",
    "networks",
    "using",
    "based",
    "shows",
    "reported",
    "report",
    "table",
    "figure",
    "results",
    "result",
}
ZKEY = re.compile(r"^[A-Z0-9]{8}$")


def limit_regex(words=None):
    return re.compile(r"\b(" + "|".join(words or LIMIT_WORDS) + r")\b", re.I)


def family_regex(codes):
    """Regex over normalised (lower-case) text that finds the review's family ids, e.g. F3, F10.

    Only ids that contain a digit count: a one-letter id such as "A" would match the article "a"."""
    ids = sorted(
        {str(c).lower() for c in codes if re.search(r"\d", str(c)) and re.fullmatch(r"[\w.-]+", str(c))},
        key=lambda c: (-len(c), c),
    )
    if not ids:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(c) for c in ids) + r")\b")


# --------------------------------------------------------------------------- Zotero local API (read-only)


class Zotero:
    def __init__(self, api=None, user_agent="agentic-review"):
        self.api = (api or os.environ.get("AR_ZOTERO_API") or DEFAULT_API).rstrip("/")
        self.ua = user_agent

    def get_all(self, path):
        out, start = [], 0
        while True:
            sep = "&" if "?" in path else "?"
            req = urllib.request.Request(
                f"{self.api}{path}{sep}format=json&limit=100&start={start}", headers={"User-Agent": self.ua}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                page = json.load(r)
            out += page
            if len(page) < 100:
                return out
            start += 100

    def find_collection(self, wanted):
        """(key, name) of a collection given by key or by name; (None, None) when not found."""
        if ZKEY.match(wanted or ""):
            return wanted, wanted
        matches = [c for c in self.get_all("/collections") if c.get("data", {}).get("name") == wanted]
        if not matches:
            return None, None
        tops = [c for c in matches if not c["data"].get("parentCollection")]
        c = (tops or matches)[0]
        return c["key"], c["data"]["name"]

    def subtree(self, key, name):
        out = [(key, name)]
        for s in self.get_all(f"/collections/{urllib.parse.quote(key)}/collections"):
            out += self.subtree(s["key"], s["data"].get("name", s["key"]))
        return out


def read_snapshot(zot, collection):
    """Items of the collection and all its sub-collections, their PDF attachments and those attachments'
    annotations, as {item_key: {title, doi, url, collection, atts: [{key, anns: [...]}]}}."""
    key, name = zot.find_collection(collection)
    if key is None:
        raise LookupError(f"Zotero collection not found: {collection}")
    items: dict[str, dict[str, Any]] = {}
    for ckey, cname in zot.subtree(key, name):
        for it in zot.get_all(f"/collections/{urllib.parse.quote(ckey)}/items/top"):
            d = it["data"]
            items.setdefault(
                it["key"],
                {
                    "title": d.get("title", ""),
                    "doi": (d.get("DOI") or "").lower(),
                    "url": d.get("url", ""),
                    "collection": cname,
                    "atts": [],
                },
            )
    by_att = defaultdict(list)
    for a in zot.get_all("/items?itemType=annotation"):  # the local API lists annotations only this way
        d = a["data"]
        try:
            pos = json.loads(d.get("annotationPosition") or "{}")
        except ValueError:
            pos = {}
        by_att[d.get("parentItem")].append(
            {
                "key": a["key"],
                "colour": COLOURS.get((d.get("annotationColor") or "").lower(), "other"),
                "type": d.get("annotationType"),
                "page_index": pos.get("pageIndex"),
                "page_label": d.get("annotationPageLabel"),
                "sort": d.get("annotationSortIndex") or "",
                "text": d.get("annotationText") or "",
                "comment": d.get("annotationComment") or "",
                "rects": pos.get("rects") or [],
                "tags": [t.get("tag") for t in d.get("tags") or []],
            }
        )
    for k, it in items.items():
        for c in zot.get_all(f"/items/{urllib.parse.quote(k)}/children"):
            d = c["data"]
            if d["itemType"] == "attachment" and d.get("contentType") == "application/pdf":
                it["atts"].append({"key": c["key"], "anns": sorted(by_att.get(c["key"], []), key=lambda a: a["sort"])})
    return items


def load_snapshot(path):
    with open(path, encoding="utf-8") as fh:
        items = json.load(fh)
    if not isinstance(items, dict):
        raise ValueError(f"{path}: not a snapshot (expected an object of items)")
    for k, it in list(items.items()):
        if not isinstance(it, dict):
            raise ValueError(f"{path}: item {k} is not an object")
        for f in ("title", "doi", "url", "collection"):
            it[f] = it.get(f) or ""
        it.setdefault("atts", [])
        for att in it["atts"]:
            for a in att.setdefault("anns", []):
                if a.get("colour") not in KNOWN_COLOURS:
                    a["colour"] = "other"
                a.setdefault("comment", "")
                a.setdefault("text", "")
                a.setdefault("tags", [])
    return items


# --------------------------------------------------------------------------- the chooser (logic unchanged)


def review_bracket(a, tag):
    """Section bracket of a review highlight, or None.

    Two reviews may share a PDF, so when the review's tag is known a highlight that carries tags but not this one
    belongs to another review and never counts, even with a [Review ...] comment. A highlight with this review's
    tag counts with any [Section] bracket; an untagged one counts only with a [Review ...] comment (highlights made
    before reviews tagged them)."""
    m = BRACKET.match(a["comment"] or "")
    if not m:
        return None
    tags = set(a.get("tags") or ())
    if tag and tag in tags:
        return m
    if tag and tags:
        return None
    return m if (a["comment"] or "").lstrip().startswith("[Review") else None


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def words(s):
    return {w for w in norm(s).split() if len(w) >= 5 and w not in STOP}


def numbers(s):
    out = set()
    for m in NUM.finditer(s):
        t = m.group(0).lstrip("+-−").replace(",", "")
        if re.fullmatch(r"(19|20)\d\d", t) or ("." not in t and len(t) < 2):
            continue
        out.add(t.rstrip("0").rstrip(".") if "." in t else t)
    return out


def section_score(bracket, h2, h3, fam):
    b = norm(bracket)
    if h3:
        n3 = norm(h3)
        c3, cb = (set(fam.findall(n3)), set(fam.findall(b))) if fam else (set(), set())
        if n3 in b or (c3 and c3 & cb):
            return 3.0
    if norm(h2) and norm(h2) in b:
        return 2.0
    tb, th = set(b.split()) - STOP, set(norm(f"{h2} {h3 or ''}").split()) - STOP
    return round(2.0 * len(tb & th) / max(1, len(tb | th)), 2)


class Linker:
    """Citation map plus (optionally) the Zotero snapshot; decides the link of every citation instance.

    items: the snapshot ({} without Zotero). key2item: citation key -> Zotero item key. tag, fam, limit: the
    review's tag, family regex and limitation-words regex (review.json)."""

    def __init__(self, citemap_rows, items=None, key2item=None, tag="", fam=None, limit=None, share=None):
        self.items = items or {}
        # Share mode: {attachment key: relative path of its PDF in the package}; links open those files instead of
        # Zotero, and an attachment left out of the package counts as no PDF.
        self.share = share
        self.tag, self.fam, self.limit = tag, fam, limit or limit_regex()
        self.label2key, self.key2url, self.meta = {}, {}, {}
        for row in citemap_rows:
            self.label2key[row["label"]] = row["key"]
            self.key2url[row["key"]] = row["url"]
            self.meta[row["key"]] = row
        self.key2item = dict(key2item or {})
        self.issues = self.check_mapping() if self.items else []

    def check_mapping(self):
        bad = []
        for key, item in self.key2item.items():
            z = self.items.get(item)
            url = self.key2url.get(key, "").lower()
            if z is None:
                bad.append((key, item, "not in collection"))
            elif z["doi"] and z["doi"] not in url:
                bad.append((key, item, f"DOI {z['doi']} vs {url}"))
        return bad

    def zotero(self, key):
        item_key = self.key2item.get(key)
        return item_key, self.items.get(item_key) if item_key else None

    def atts(self, item):
        """The item's attachments that links may open (in share mode, only those in the package)."""
        if not item:
            return []
        return [t for t in item["atts"] if self.share is None or t["key"] in self.share]

    def open_href(self, att, page=None, ann=None):
        if self.share is not None:
            return self.share[att] + (f"#page={page}" if page else "")
        query = (f"page={page}&" if page else "") + f"annotation={ann}" if ann else ""
        return f"zotero://open-pdf/library/items/{att}" + (f"?{query}" if query else "")

    def pdf_href(self, key):
        _item_key, item = self.zotero(key)
        atts = self.atts(item)
        if atts:
            att = max(atts, key=lambda t: len(t["anns"]))
            return self.open_href(att["key"])
        return None

    def choose(self, key, h2, h3, context):
        """Link for one citation instance: a highlighted passage, the PDF, or the citation-map link."""
        url = self.key2url.get(key)
        item_key, item = self.zotero(key)
        atts = self.atts(item)
        if not atts:
            return {"type": "doi", "href": url, "item": item_key}
        plain = LINK.sub(lambda m: m.group(1), context)
        cn, cw = numbers(plain), words(plain)
        want_result, want_limit = bool(RESULT.search(plain)), bool(self.limit.search(plain))
        scored = []
        for att in atts:
            for a in att["anns"]:
                m = review_bracket(a, self.tag)
                if not m:
                    continue
                body = a["text"] + " " + a["comment"][m.end() :]
                s_sec = section_score(m.group(1), h2, h3, self.fam)
                s_num = min(6.0, 2.0 * len(cn & numbers(body)))
                s_word = min(2.0, 0.3 * len(cw & words(body)))
                s_col = (0.5 if want_result and a["colour"] == "green" else 0) + (
                    0.3 if want_limit and a["colour"] == "red" else 0
                )
                scored.append((s_sec + s_num + s_word + s_col, s_sec, s_num, a, att["key"]))
        best = max(scored, key=lambda t: t[0]) if scored else None
        confident = bool(best) and best[0] >= 2.5 and (best[1] >= 2.0 or best[2] >= 2.0)
        if not confident and (h2 == "Taxonomy" or "**Landmarks.**" in context):
            # a landmark mention is about the design, so the best architecture highlight is the right passage
            yellow = [t for t in scored if t[3]["colour"] == "yellow"]
            if yellow:
                best, confident = max(yellow, key=lambda t: t[0]), True
        if confident:
            assert best is not None
            score, s_sec, s_num, a, att = best
            page = a["page_index"] + 1 if isinstance(a["page_index"], int) else None
            return {
                "type": "annotation",
                "href": self.open_href(att, page, a["key"]),
                "colour": a["colour"],
                "ann": a["key"],
                "score": round(score, 2),
                "page": page,
                "snippet": (a["text"] or a["comment"])[:140],
                "item": item_key,
            }
        return {"type": "pdf", "href": self.pdf_href(key), "item": item_key, "score": round(best[0], 2) if best else 0}


def spans(line):
    """Context spans of a markdown line: table cells (with the row label), or sentences."""
    if line.startswith("|"):
        cells, pos = [], 0
        parts = line.split("|")
        first = parts[1] if len(parts) > 1 else ""
        for i, p in enumerate(parts):
            # a citation in the row-label column is about the whole row; elsewhere, its cell plus the row label
            cells.append((pos, pos + len(p), line if i == 1 else f"{first} | {p}"))
            pos += len(p) + 1
        return cells
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z(\[*])", line):
        out.append((start, m.start(), line[start : m.start()]))
        start = m.end()
    out.append((start, len(line), line[start:]))
    return out


def citations(md_lines, linker, stop_heading="References"):
    """Every citation instance before the references heading, with its section and chosen link."""
    h2 = h3 = ""
    out = []
    for no, line in enumerate(md_lines):
        if line.startswith("## "):
            h2, h3 = line[3:].strip(), ""
            if h2 == stop_heading:
                break
            continue
        if line.startswith("### "):
            h3 = line[4:].strip()
            continue
        sp = spans(line)
        for m in LINK.finditer(line):
            label, url = m.group(1), m.group(2)
            key = linker.label2key.get(label)
            if key is None:
                out.append(
                    {
                        "line": no,
                        "start": m.start(),
                        "end": m.end(),
                        "label": label,
                        "url": url,
                        "key": None,
                        "h2": h2,
                        "h3": h3,
                        "context": "",
                        "link": {"type": "external", "href": url},
                    }
                )
                continue
            ctx = next((c for a, b, c in sp if a <= m.start() < b), line)
            out.append(
                {
                    "line": no,
                    "start": m.start(),
                    "end": m.end(),
                    "label": label,
                    "url": url,
                    "key": key,
                    "h2": h2,
                    "h3": h3,
                    "context": ctx,
                    "link": linker.choose(key, h2, h3, ctx),
                }
            )
    return out


def read_citemap(path):
    """Rows of citation_map.tsv (plain tab-separated, as ar-citemap writes it: no quoting)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        return []
    head = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if line.strip():
            row = dict(zip(head, line.split("\t")))
            if row.get("key") and row.get("label"):
                row.setdefault("url", "")
                row.setdefault("title", "")
                rows.append(row)
    return rows
