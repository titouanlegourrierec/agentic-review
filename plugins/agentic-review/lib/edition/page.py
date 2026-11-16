"""The reading edition: one self-contained web page (styles, scripts and data inline; it makes no requests).

With Zotero, every citation opens the cited passage in Zotero (links chosen by zlinks); hovering previews the
highlighted passage and its note. Without Zotero, every citation opens its citation-map link and hovering shows the
paper's title, venue and year, its one-line claim and what the claims check found about it.
"""

import datetime
import glob
import html
import json
import os
import re

import arlib

from . import figures, markdown, render

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = re.compile(r"^\s*<!--\s*section:\s*[A-Za-z0-9_.-]+\s*-->\s*$")
BRACKET = re.compile(r"^\s*\[(?:Review\s*›)?[^\]]*\]\s*")
ANCHOR = re.compile(r'<a id="((?:cite|rig)\d+)" class="([^"]*)" href="([^"]*)">')
NUM = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?")
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
CITE_LIKE = re.compile(r"(?:1[89]|2[0-9])\d{2}[a-z]?$")
REF_LINE = re.compile(r"^[-*+]\s+\[([^\]]+)\]\((\S+?)\)(?:\s*[—–]\s*|\s*:\s+|\s+-\s+|\s+|$)(.*)$")
REF_NAMES = {
    "references",
    "bibliography",
    "works cited",
    "références",
    "bibliographie",
    "referencias",
    "literatur",
    "literaturverzeichnis",
    "riferimenti",
    "bibliografia",
    "referências",
}
LANG = {
    "english": "en",
    "french": "fr",
    "français": "fr",
    "german": "de",
    "deutsch": "de",
    "spanish": "es",
    "español": "es",
    "italian": "it",
    "italiano": "it",
    "portuguese": "pt",
    "português": "pt",
    "dutch": "nl",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
}
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
NUMBER_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
ROLE_GROUPS = [
    ("discovery", ("discovery",)),
    ("analysis", ("synthesis", "comparison")),
    ("verification", ("rigor-checker", "omissions-checker", "claims-checker")),
    ("code", ("code-finder", "repo-auditor", "paper-code-checker")),
    ("annotation", ("annotator", "late-pdf-checker")),
]


class Refused(Exception):
    """A key point or a tile whose numbers are not in the review."""


def esc(s):
    return html.escape(s or "", quote=True)


def clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def plain(s):
    """Record text for display: markup removed, entities decoded (the page escapes it again)."""
    return html.unescape(re.sub(r"<[^>]+>", "", str(s or "")))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", arlib.fold(s or "").lower()).strip("-")


def script_json(obj):
    """JSON for a <script type="application/json"> block: '</' and '<!--' cannot end or confuse the block."""
    return (
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "\\u003c!--")
    )


def norm_url(u):
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://(dx\.)?", "", u)
    return u.rstrip("/")


def num_set(text):
    return {n.lstrip("+-−").replace(",", "") for n in NUM.findall(text)}


def js_escape(term):
    return re.sub(r"[.*+?^${}()|\[\]\\/]", lambda m: "\\" + m.group(0), term)


# --------------------------------------------------------------------------- inputs


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def relabel(text, url2rows, labels):
    """Rewrite the text of every citation link from the citation map, matching by URL. Only link texts that look
    like citation labels (ending in a year) or that are labels of the map are rewritten. Returns (text, count)."""
    count = 0

    def rep(m):
        nonlocal count
        label, url = m.group(1), m.group(2)
        rows = url2rows.get(norm_url(url))
        if not rows or not (CITE_LIKE.search(label.strip()) or label in labels):
            return m.group(0)
        if any(r["label"] == label for r in rows) or len(rows) != 1:
            return m.group(0)
        count += 1
        return f"[{rows[0]['label']}]({url})"

    return MD_LINK.sub(rep, text), count


def split_review(md_text, ref_heading=None):
    """(body lines from the first `## ` heading to the references heading, reference lines, references heading)."""
    lines = md_text.splitlines()
    first = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    names = {ref_heading.lower()} if ref_heading else REF_NAMES
    refs = next((i for i, ln in enumerate(lines) if ln.startswith("## ") and ln[3:].strip().lower() in names), None)
    if refs is None:
        return lines[first:], [], "References"
    end = next((i for i in range(refs + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[first:refs], lines[refs + 1 : end], lines[refs][3:].strip()


def counts_numbers(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(str(obj) if not isinstance(obj, float) or not obj.is_integer() else str(int(obj)))
    elif isinstance(obj, str):
        out |= num_set(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            counts_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            counts_numbers(v, out)
    return out


def load_records(rdir):
    recs = {}
    for rel_path in (arlib.CORPUS, arlib.OMISSIONS, arlib.BACKGROUND):
        p = os.path.join(rdir, rel_path)
        if os.path.exists(p):
            for r in arlib.load_jsonl(p):
                if r.get("key") and r["key"] not in recs:
                    recs[r["key"]] = r
    return recs


CHECK_CLASSES = [
    (re.compile(r"^(partial|partly)"), "v-mid", "Partly supported"),
    (re.compile(r"^(contradict|refut|not[-_ ]?supported|unsupported|wrong|incorrect)"), "v-poor", "Contradicted"),
    (re.compile(r"^supported"), "v-good", "Supported"),
    (re.compile(r"^(unverif|unclear|not[-_ ]?found|untest|inconclusive)"), "v-open", "Unverified"),
]


def check_verdict(v):
    s = str(v or "").strip().lower()
    for rx, cls, label in CHECK_CLASSES:
        if rx.match(s):
            return cls, label
    return "v-open", (s.replace("-", " ").capitalize() or "Unrated")


def load_claims(rdir):
    """Claims-check results per paper key: [{v: class, l: verdict, q: claim, e: evidence}]."""
    out = {}
    for p in sorted(glob.glob(os.path.join(rdir, "4-checks", "claims_check*.jsonl"))):
        for c in arlib.load_jsonl(p):
            cls, label = check_verdict(c.get("verdict"))
            entry = {
                "v": cls,
                "l": label,
                "q": clip(plain(c.get("claim_text")), 160),
                "e": clip(plain(c.get("evidence") or c.get("correct_value")), 200),
            }
            for k in re.split(r"[,;\s]+", str(c.get("paper_key") or "")):
                if k and entry not in out.setdefault(k, []):
                    out[k].append(entry)
    return out


# --------------------------------------------------------------------------- popover data


class Data:
    """Popover data: citation instances point to a paper and, when there is one, to the highlight."""

    def __init__(self, linker, web=False, records=None, claims=None):
        self.linker, self.cites, self.papers, self.anns = linker, {}, {}, {}
        self.web, self.records, self.claims = web, records or {}, claims or {}
        self.ann_by_key = {a["key"]: a for it in linker.items.values() for att in it["atts"] for a in att["anns"]}

    def paper(self, key):
        if key and key not in self.papers:
            m = self.linker.meta[key]
            item = self.linker.key2item.get(key)
            select = (
                f"zotero://select/library/items/{item}"
                if item in self.linker.items and self.linker.share is None
                else None
            )
            entry = {
                "l": m["label"],
                "t": m.get("title", ""),
                "u": markdown.safe_url(m.get("url", "")),
                "z": self.linker.pdf_href(key) or select,
            }
            if self.web:
                r = self.records.get(key, {})
                venue = arlib.venue_vor(r) if r else None
                year = m.get("cite_year") or (arlib.cite_year(r) if r else None)
                entry["t"] = clip(plain(entry["t"]), 400)
                entry["v"] = clip(plain(venue), 160) if venue and not arlib.is_empty(venue) else ""
                entry["y"] = str(year or "")
                entry["c"] = (
                    clip(plain(r.get("one_line_claim")), 420) if not arlib.is_empty(r.get("one_line_claim")) else ""
                )
                checks = self.claims.get(key, [])
                entry["cc"] = checks[:3]
                entry["n"] = len(checks)
            self.papers[key] = entry
        return key

    def add(self, aid, cit):
        link = cit["link"]
        ann = link.get("ann")
        if ann and ann not in self.anns:
            a = self.ann_by_key[ann]
            self.anns[ann] = {
                "c": a["colour"],
                "p": link.get("page"),
                "x": clip(a["text"], 420),
                "m": clip(BRACKET.sub("", a["comment"]), 420),
                "i": a["type"] == "image",
            }
        self.cites[aid] = {"k": self.paper(cit["key"]), "a": ann, "t": link["type"]}

    def href(self, cit):
        """Papers in Zotero without a PDF open their Zotero item; the rest keep their link."""
        link, key = cit["link"], cit["key"]
        if link["type"] == "doi" and key and self.papers.get(key, {}).get("z"):
            return self.papers[key]["z"]
        return link["href"] or ""


def wire(body, cits, tag, data):
    for n, c in enumerate(cits):
        if c["key"]:
            data.add(f"{tag}{n}", c)

    def rep(m):
        aid, cls, href = m.groups()
        n = int(aid[len(tag) :]) if aid.startswith(tag) else None
        if n is None:
            return m.group(0)
        c = cits[n]
        target = html.escape(markdown.safe_url(data.href(c)), quote=True) if c["key"] else href
        extra = f' data-c="{aid}"' if aid in data.cites else ""
        newtab = ' target="_blank" rel="noopener"' if target.startswith(("http", "papers/")) else ""
        return f'<a id="{aid}" class="{cls}" href="{target}"{extra}{newtab}>'

    return ANCHOR.sub(rep, body)


# --------------------------------------------------------------------------- page parts


def glossary(review, rigor_text):
    """Glossary entries: review.json edition.glossary, then taxonomy families and rigor criteria."""
    out, warnings = [], []
    for g in (review.get("edition") or {}).get("glossary") or []:
        if not isinstance(g, dict) or not g.get("term") or not g.get("definition"):
            warnings.append(f"glossary entry skipped (needs term and definition): {str(g)[:60]}")
            continue
        term = str(g["term"])
        default = rf"(?<![\w-]){js_escape(term)}(?![\w-])"
        pat = g.get("pattern") or default
        try:
            if re.compile(pat).groups:
                raise re.error("capturing group")
        except re.error as e:
            warnings.append(f'glossary pattern of "{term}" not usable ({e}): matching the term itself')
            pat = default
        out.append({"t": term, "p": pat, "d": str(g["definition"])})
    tax = review.get("taxonomy") or {}
    if isinstance(tax, list):
        tax = {str(x.get("id")): x for x in tax if isinstance(x, dict) and x.get("id")}
    for code, v in tax.items() if isinstance(tax, dict) else []:
        code = str(code)
        if not re.search(r"\d", code) or not re.fullmatch(r"[\w.-]+", code):
            continue  # one-letter ids (A, B) would match ordinary words
        name = v if isinstance(v, str) else (v or {}).get("name") or ""
        desc = "" if isinstance(v, str) else (v or {}).get("description") or (v or {}).get("definition") or ""
        out.append(
            {
                "t": f"{code} · {name}" if name else code,
                "p": rf"(?<![\w-]){js_escape(code)}(?![\w-])",
                "d": desc or "A family of the review's taxonomy.",
            }
        )
    rubric = [x for x in (review.get("rigor_rubric") or []) if isinstance(x, dict) and x.get("id")]
    if not rubric:
        rubric = [
            {"id": c, "name": n, "scoring": s}
            for c, n, s in re.findall(r"^\| ([A-Z]+\d+) \| ([^|]+?) \| ([^|]+?) \|", rigor_text or "", re.M)
        ]
    for x in rubric:
        code = str(x["id"])
        if not re.search(r"\d", code) or not re.fullmatch(r"[\w.-]+", code):
            continue
        scale = f", {x['scale']}" if x.get("scale") else ""
        how = x.get("scoring") or x.get("description") or ""
        out.append(
            {
                "t": f"{code} · {x.get('name') or ''}".rstrip(" ·"),
                "p": rf"(?<![\w-]){js_escape(code)}(?![\w-])",
                "d": f"Rigor criterion{scale}: {how}." if how else f"Rigor criterion{scale}.",
            }
        )
    return out, warnings


def key_points(body, md_text, kp):
    """A Key points box under each section heading; every number in it must appear in that section's text."""
    refused, n = [], 0
    for name, points in kp.items():
        if name.startswith("_"):
            continue
        if not isinstance(points, list) or not all(isinstance(p, str) for p in points):
            refused.append(f'key points of "{name}": not a list of strings')
            continue
        sec = re.search(rf"^## {re.escape(name)}[ \t]*\n(.*?)(?=^## |\Z)", md_text, re.S | re.M)
        if not sec:
            refused.append(f'key points of "{name}": no section with this heading in review.md')
            continue
        have = num_set(re.sub(r"\]\([^)]+\)", "]", sec.group(1)))  # numbers inside DOIs and URLs do not count
        bad = [
            f'"{x}" is not in section "{name}": {p}'
            for p in points
            for x in NUM.findall(p)
            if x.lstrip("+-−").replace(",", "") not in have
        ]
        if bad:
            refused += bad
            continue
        m = next(
            (
                m
                for m in re.finditer(r'<h2 id="[^"]+">(?:<span class="secnum">[^<]*</span> )?(.*?)</h2>', body)
                if html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() == name
            ),
            None,
        )
        if not m:
            refused.append(f'key points of "{name}": no heading for it in the page')
            continue
        box = (
            '<aside class="keypoints" aria-label="Key points"><div class="kp-title">Key points</div><ul>'
            + "".join(f"<li>{esc(p)}</li>" for p in points)
            + "</ul></aside>"
        )
        body = body[: m.end()] + "\n" + box + body[m.end() :]
        n += 1
    return body, n, refused


def tiles(kp, md_text, counts):
    """Headline tiles from key_points.json `_tiles`; every number must be in the review or in counts.json."""
    items = kp.get("_tiles") or []
    if not isinstance(items, list):
        return "", ["_tiles: not a list"]
    have = num_set(re.sub(r"\]\([^)]+\)", "]", md_text)) | counts_numbers(counts)
    out, refused = [], []
    for t in items:
        if not isinstance(t, dict) or not str(t.get("value") or "").strip():
            refused.append(f"tile without a value: {str(t)[:80]}")
            continue
        value, text = str(t.get("value")), str(t.get("text") or "")
        bad = [x for x in NUM.findall(f"{value} {text}") if x.lstrip("+-−").replace(",", "") not in have]
        if bad:
            refused.append(f'tile "{value}": {", ".join(bad)} not in the review or counts.json')
            continue
        out.append(f'<div class="tile"><div class="num">{esc(value)}</div><div class="cap">{esc(text)}</div></div>')
    return "".join(out), refused


def references(ref_lines, linker, data, cits, toc, bib, used):
    """Reference list; each entry links back to the sections that cite it (first citation in each section).

    Entries with a BibTeX record get a copy button; the records used are collected in `used` for the page.
    `### ` headings inside the references section become groups."""
    sec_num = {html.unescape(t): num for _, _, num, t in toc}
    cited = {}
    for n, c in enumerate(cits):
        if c["key"]:
            sec = c["h3"] or c["h2"]
            e = cited.setdefault(c["key"], {"n": 0, "secs": {}})
            e["n"] += 1
            e["secs"].setdefault(f"§{sec_num[sec]}" if sec_num.get(sec) else sec, n)
    groups, count = [(None, [])], 0
    for line in ref_lines:
        s = line.strip()
        if s.startswith("### "):
            groups.append((s[4:].strip(), []))
            continue
        m = REF_LINE.match(s)
        if not m:
            continue
        label, url, rest = m.groups()
        key = linker.label2key.get(label)
        z = data.papers.get(data.paper(key), {}).get("z") if key else None
        safe = markdown.safe_url(url)
        host = "arXiv" if "arxiv.org" in safe else "DOI" if "doi.org" in safe else "Web"
        zlabel = "PDF" if linker.share is not None else "Zotero"
        zattr = ' target="_blank" rel="noopener"' if linker.share is not None else ""
        chips = (
            f'<a class="chip z" href="{esc(z)}"{zattr}>{zlabel}</a>' if z else ""
        ) + f'<a class="chip" href="{esc(safe)}" target="_blank" rel="noopener">{host} ↗</a>'
        if key in bib:
            used[key] = bib[key]
            chips += f'<button class="chip bib" type="button" data-bib="{esc(key)}" title="Copy the BibTeX entry">BibTeX</button>'
        back = ""
        if key in cited:
            e = cited[key]
            links = " ".join(f'<a href="#cite{n}">{esc(s)}</a>' for s, n in e["secs"].items())
            back = f'<span class="citedin">cited {e["n"]}× · {links}</span>'
        rest = rest.strip()
        groups[-1][1].append(
            f'<li><span class="rlabel">{esc(label)}</span>{" — " + esc(rest) if rest else ""} '
            f'<span class="chips">{chips}</span>{back}</li>'
        )
        count += 1
    out = []
    for title, items in groups:
        if not items:
            continue
        if title:
            out.append(f'<h3 class="refgroup">{esc(title)}</h3>')
        out.append(f'<ol class="reflist">{"".join(items)}</ol>')
    return "".join(out), count


def verdicts(body, toc):
    """Give each row of the claims table (a table with a Verdict column) an id, and list the claims with their
    verdicts, verbatim."""
    m = re.search(r"<table>(?:(?!</table>).)*?<th[^>]*>Verdict</th>.*?</table>", body, re.S)
    if not m:
        return body, ""
    items = []

    def row(r):
        i = len(items) + 1
        cell = re.search(r"<td[^>]*>(.*?)</td>", r.group(0), re.S)
        claim = re.sub(r"<[^>]+>", "", cell.group(1) if cell else "").strip()
        v = re.search(r'<span class="verdict (v-\w+)">([^<]*)</span>', r.group(0))
        items.append(
            f'<li><a href="#claim-{i}"><span class="verdict {v.group(1) if v else "v-open"}">'
            f"{esc(v.group(2) if v else '')}</span><span>{esc(html.unescape(claim))}</span></a></li>"
        )
        return f'<tr id="claim-{i}">' + r.group(0)[4:]

    table = re.sub(r"<tr>\s*<td[^>]*>.*?</tr>", row, m.group(0), flags=re.S)
    heads = list(re.finditer(r'<h2 id="([^"]+)">', body[: m.start()]))
    where = ""
    if heads:
        hid = heads[-1].group(1)
        num, title = next(((n, t) for lvl, h, n, t in toc if h == hid), ("", ""))
        where = f"section {num}" if num else f"“{html.unescape(title)}”"
    note = f" <span>(verdicts from {esc(where)})</span>" if where else ""
    glance = (
        '<section class="glance" aria-label="The claims at a glance"><div class="glance-title">The '
        f"{len(items)} claims at a glance{note}</div><ol>{''.join(items)}</ol></section>"
    )
    return body[: m.start()] + table + body[m.end() :], glance


def toc_html(toc):
    out, i = [], 0
    while i < len(toc):
        _lvl, hid, num, text = toc[i]
        j, subs = i + 1, []
        while j < len(toc) and toc[j][0] == 3:
            subs.append(toc[j])
            j += 1
        sub = "".join(f'<li><a href="#{h}"><span class="n">{n}</span>{esc(t)}</a></li>' for _, h, n, t in subs)
        out.append(
            f'<li><a href="#{hid}"><span class="n">{num}</span>{esc(text)}</a>{f"<ol>{sub}</ol>" if sub else ""}</li>'
        )
        i = j
    return "<ol>" + "".join(out) + "</ol>"


def bib_entries(path):
    if not os.path.exists(path):
        return {}
    out = {}
    for block in re.split(r"\n(?=@)", read(path)):
        m = re.match(r"@\w+\{([^,\s]+),", block.strip())
        if m:
            out[m.group(1)] = block.strip()
    return out


def default_footer(rdir, today):
    state = arlib.load_json(os.path.join(rdir, "state.json"), {}) or {}
    roles = [str(a.get("role") or "") for a in state.get("agents") or [] if isinstance(a, dict)]
    parts = []
    for name, members in ROLE_GROUPS:
        n = sum(1 for r in roles if r in members)
        if n:
            word = NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else str(n)
            parts.append(f"{word} {name} agent{'s' if n > 1 else ''}")
    if "lead-reviewer" in roles:
        parts.append("a lead reviewer")
    text = ""
    if parts:
        text = (
            "Multi-agent review: "
            + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0])
            + ". "
        )
    return text + f"Built {today.day} {MONTHS[today.month - 1]} {today.year}."


# --------------------------------------------------------------------------- the page

HOWTO_ZOTERO = """<details class="howto"><summary><span class="q" aria-hidden="true">?</span>How the links work</summary>
  <p><b>Every citation opens the paper in Zotero at the passage the review relies on.</b> Hover a citation to preview the
  highlighted text and its note; a ✓ marks passages you have already opened. The underline has the colour of the annotation:</p>
  <p class="keys"><span><i class="sw yellow"></i>method</span> <span><i class="sw blue"></i>data and protocol</span>
  <span><i class="sw green"></i>result cited</span> <span><i class="sw red"></i>limitation or red flag</span>
  <span><i class="sw purple"></i>a correction or a disagreement with the paper</span>
  <span><i class="sw grey"></i>the paper's first page</span> <span><i class="sw dotted"></i>publisher's page</span></p>
  <p>A dotted underline explains a term or an abbreviation. References
  list where each paper is cited, and § next to a heading copies a link to it.</p>
  </details>"""
HOWTO_SHARE = """<details class="howto"><summary><span class="q" aria-hidden="true">?</span>How the links work</summary>
  <p><b>Citations open the paper's PDF, shipped with this page in the <code>papers</code> folder, at the page of the passage
  the review relies on.</b> Hover a citation to preview the highlighted text and its note; a ✓ marks passages you have already
  opened. Papers whose PDF is not in the package open the publisher's page. The underline has the colour of the annotation:</p>
  <p class="keys"><span><i class="sw yellow"></i>method</span> <span><i class="sw blue"></i>data and protocol</span>
  <span><i class="sw green"></i>result cited</span> <span><i class="sw red"></i>limitation or red flag</span>
  <span><i class="sw purple"></i>a correction or a disagreement with the paper</span>
  <span><i class="sw grey"></i>the paper's first page</span> <span><i class="sw dotted"></i>publisher's page</span></p>
  <p>A dotted underline explains a term or an abbreviation. References
  list where each paper is cited, and § next to a heading copies a link to it.</p>
  </details>"""
HOWTO_WEB = """<details class="howto"><summary><span class="q" aria-hidden="true">?</span>How the links work</summary>
  <p><b>Every citation opens the paper's DOI, arXiv or source page.</b> Hover a citation to see the paper, its venue and
  year, its main claim and what the claims check found when it compared the review's statements with the paper.</p>
  <p>A dotted underline under a term or an abbreviation explains it. References
  list where each paper is cited, and § next to a heading copies a link to it.</p>
  </details>"""


def build(rdir, review, linker, web, today=None):
    """Build the page. Returns (page_html, stats, refused, warnings). `linker` carries the citation map and, in
    Zotero mode, the snapshot."""
    rdir = str(rdir)
    today = today or datetime.date.today()
    fin = os.path.join(rdir, "5-final")
    ed = review.get("edition") or {}
    warnings = list(getattr(linker, "warnings", []))
    md_raw = read(os.path.join(fin, "review.md"))
    md_text = "\n".join(ln for ln in md_raw.splitlines() if not MARKER.match(ln)) + "\n"

    # relabel every citation from the citation map, matching by URL
    url2rows, labels = {}, set()
    for row in linker.meta.values():
        url2rows.setdefault(norm_url(row.get("url")), []).append(row)
        labels.add(row["label"])
    md_text, n_relabel = relabel(md_text, url2rows, labels)
    rigor_path, cat_path = os.path.join(fin, "rigor_table.md"), os.path.join(fin, "catalogue.md")
    rigor_text = read(rigor_path) if os.path.exists(rigor_path) else ""
    cat_text = read(cat_path) if os.path.exists(cat_path) else ""
    rigor_text, n2 = relabel(rigor_text, url2rows, labels)
    cat_text, n3 = relabel(cat_text, url2rows, labels)

    body_lines, ref_lines, ref_heading = split_review(md_text, ed.get("references_heading"))
    title_line = next((ln[2:].strip() for ln in md_text.splitlines() if ln.startswith("# ")), "")
    title = str(ed.get("title") or "").strip() or title_line or "Literature review"
    store = slug(str(ed.get("storage_key") or "")) or slug(title) or "review"
    bib_name = f"{store}.bib"
    records = load_records(rdir) if web else {}
    claims = load_claims(rdir) if web else {}
    data = Data(linker, web, records, claims)

    body, cits = render.render_md(body_lines, linker, "cite", stop_heading=ref_heading)
    unnumbered = set(render.UNNUMBERED) | {str(u).lower() for u in ed.get("unnumbered") or []}
    body, toc = render.number_headings(body, unnumbered)
    body = render.polish(body)
    body = wire(body, cits, "cite", data)
    body, glance = verdicts(body, toc)
    kp_path = os.path.join(fin, "key_points.json")
    kp = arlib.load_json(kp_path, {}) if os.path.exists(kp_path) else {}
    if not isinstance(kp, dict):
        kp = {}
        warnings.append("key_points.json is not an object: ignored")
    body, nkp, refused = key_points(body, md_text, kp)
    counts = arlib.load_json(os.path.join(fin, "counts.json"), {}) or {}
    tiles_html, refused_tiles = tiles(kp, md_text, counts)
    refused += refused_tiles
    body = re.sub(r"(<table>.*?</table>)", r'<div class="tw">\1</div>', body, flags=re.S)
    # figures go in last, so that no step above sees their SVG or reads "Figure 3" as a section number
    body, figs = figures.place_all(body, rdir, review, linker, data, md_text, counts)
    if figs:
        refused += figs["refused"]

    rig = ""
    rig_lines = [ln for ln in rigor_text.splitlines() if not ln.startswith("# ")]
    if any(ln.strip() for ln in rig_lines):
        rig_h2 = next((t for lvl, _, _, t in toc if lvl == 2 and re.search(r"rigou?r|rigueur", t, re.I)), None)
        rig, rig_cits = render.render_md(
            rig_lines, linker, "rig", html.unescape(rig_h2 or "Methodological rigor"), stop_heading=ref_heading
        )
        rig = re.sub(r"(<table>.*?</table>)", r'<div class="tw">\1</div>', wire(rig, rig_cits, "rig", data), flags=re.S)
    bib = {}
    refs, nrefs = references(ref_lines, linker, data, cits, toc, bib_entries(os.path.join(fin, "references.bib")), bib)
    cat, _, ncat = render.catalogue_html(cat_text, linker) if cat_text else ("", [], 0)
    cat = re.sub(r'(<table class="catalogue">.*?</table>)', r'<div class="tw">\1</div>', cat, flags=re.S)
    cat = cat.replace('href="zotero://', 'data-z="1" href="zotero://')
    if linker.share is not None:
        cat = re.sub(r'(<a class="cite t-pdf" href="papers/[^"]*")', r'\1 target="_blank" rel="noopener"', cat)
    cat = re.sub(r'(<a class="cite t-doi" href="http[^"]*")', r'\1 target="_blank" rel="noopener"', cat)

    letters = iter("ABCDEFGH")
    sections = []
    if nrefs:
        toc.append((2, "references", "", ref_heading))
        if web:
            intro = f"The {nrefs} works cited above. The chip opens the publisher's page" + (
                ", and <b>BibTeX</b> copies the entry." if bib else "."
            )
        elif linker.share is not None:
            intro = (
                f"The {nrefs} works cited above. <b>PDF</b> opens the paper shipped with this page,\n"
                "the next chip opens the publisher's page" + (", and <b>BibTeX</b> copies the entry." if bib else ".")
            )
        else:
            intro = (
                f"The {nrefs} works cited above. <b>Zotero</b> opens the paper (or its record when there is no PDF),\n"
                "the next chip opens the publisher's page" + (", and <b>BibTeX</b> copies the entry." if bib else ".")
            )
        dl = (
            f'\n<button class="bibdl" type="button">Download the {len(bib)} entries as a BibTeX file</button>'
            if bib
            else ""
        )
        sections.append(f'<h2 id="references">{esc(ref_heading)}</h2>\n<p class="intro">{intro}</p>{dl}\n{refs}')
    if ncat:
        a = next(letters)
        toc.append((2, f"appendix-{a.lower()}", a, "Paper catalogue"))
        how = (
            "Every link opens the publisher's page."
            if web
            else "A solid\nunderline opens the paper's PDF; a dotted one opens the publisher's page."
            if linker.share is not None
            else "A solid\nunderline opens the paper in Zotero; a dotted one opens the publisher's page."
        )
        dagger = " † marks papers added by the omission check." if "†" in cat else ""
        sections.append(
            f'<h2 id="appendix-{a.lower()}"><span class="secnum">{a}</span> Paper catalogue</h2>\n'
            f'<p class="intro">All {ncat} papers catalogued for the review, by tier.{dagger} {how}</p>\n'
            '<details class="catalogue-box"><summary>Show the catalogue</summary>\n'
            '<input class="filter" type="search" placeholder="Filter by author, title, family…" '
            f'aria-label="Filter the catalogue">\n{cat}</details>'
        )
    if rig:
        a = next(letters)
        toc.append((2, f"appendix-{a.lower()}", a, "Rigor rubric and scores"))
        sections.append(
            f'<h2 id="appendix-{a.lower()}"><span class="secnum">{a}</span> Rigor rubric and scores</h2>\n{rig}'
        )

    gloss, gwarn = glossary(review, rigor_text)
    warnings += gwarn
    css = read(os.path.join(HERE, "webpage.css"))
    if figs and figs["n"]:
        css += figures.css()
    js = read(os.path.join(HERE, "webpage.js"))
    payload = script_json(
        {
            "cites": data.cites,
            "papers": data.papers,
            "anns": data.anns,
            "gloss": gloss,
            "store": store,
            "bib": bib_name,
            "mode": "web" if web else "share" if linker.share is not None else "zotero",
        }
    )
    bib_json = script_json(bib)
    raw_subtitle = kp.get("_subtitle")
    subtitle = raw_subtitle if isinstance(raw_subtitle, str) else ""
    kicker = str(ed.get("kicker") or f"Critical literature review · {MONTHS[today.month - 1]} {today.year}")
    footer = str(ed.get("footer") or default_footer(rdir, today))
    lang = LANG.get(str(review.get("language") or "English").strip().lower(), "en")
    theme_key = json.dumps(f"{store}-theme")
    hero = [
        f'<div class="topline"><div class="kicker">{esc(kicker)}</div>\n'
        '    <button class="theme" type="button" aria-label="Switch between light and dark">◐ <span>Dark</span></button></div>',
        f"<h1>{esc(title)}</h1>",
    ]
    if subtitle.strip():
        hero.append(f'<p class="subtitle">{esc(subtitle.strip())}</p>')
    if tiles_html:
        hero.append(f'<div class="tiles">{tiles_html}</div>')
    hero.append(HOWTO_WEB if web else HOWTO_SHARE if linker.share is not None else HOWTO_ZOTERO)
    if glance:
        hero.append(glance)
    if web:
        foot = esc(footer)
    elif linker.share is not None:
        foot = esc(footer) + (
            " The PDFs are in the <code>papers</code> folder next to this page; keep them together.\n"
            '<button class="clear-opened" type="button">Clear the ✓ marks</button>'
        )
    else:
        foot = esc(footer) + (
            " Links need the Zotero 7 desktop app on this computer.\n"
            '<button class="clear-opened" type="button">Clear the ✓ marks</button>'
        )
    nl = "\n"
    page = f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<script>try {{ const t = localStorage.getItem({theme_key}); if (t) document.documentElement.dataset.theme = t; }} catch (e) {{}}</script>
<style>{css}</style>
</head>
<body>
<div class="progress" aria-hidden="true"></div>
<div class="phonebar"><button class="tocbtn" type="button" aria-controls="toc" aria-expanded="false">☰ Contents</button>
  <span class="cursec" aria-live="polite"></span></div>
<div class="scrim" hidden></div>
<div class="layout">
<nav class="toc" id="toc" aria-label="Contents"><p class="toc-title">Contents</p>{toc_html(toc)}</nav>
<main>
<header class="hero">
  {(nl + "  ").join(hero)}
</header>
{body}
{nl.join(sections)}
<footer>{foot}</footer>
</main>
</div>
<a class="totop" href="#" aria-label="Back to top">↑</a>
<div class="toast" role="status" hidden></div>
<div class="pop" role="dialog" aria-live="polite" hidden></div>
<div class="gtip" role="tooltip" hidden></div>
<script id="data" type="application/json">{payload}</script>
<script id="bib" type="application/json">{bib_json}</script>
<script>{js}</script>
</body>
</html>"""
    kinds = {}
    for c in cits:
        kinds[c["link"]["type"]] = kinds.get(c["link"]["type"], 0) + 1
    stats = {
        "kinds": kinds,
        "cites": len(data.cites),
        "papers": len(data.papers),
        "anns": len(data.anns),
        "kp": nkp,
        "gloss": len(gloss),
        "bib": len(bib),
        "refs": nrefs,
        "cat": ncat,
        "relabelled": n_relabel + n2 + n3,
        "relabelled_review": n_relabel,
        "size": len(page.encode("utf-8")),
        "tiles": tiles_html.count('class="tile"'),
        "citations": cits,
        "title": title,
        "figures": (figs or {}).get("n", 0),
        "figure_links": (figs or {}).get("links", 0),
        "figure_kinds": (figs or {}).get("kinds", {}),
        "figure_summary": (figs or {}).get("summary", []),
        "figure_link_list": (figs or {}).get("link_list", []),
    }
    return page, stats, refused, warnings


# --------------------------------------------------------------------------- checks

OPEN_PDF = re.compile(r"^zotero://open-pdf/library/items/([A-Z0-9]{8})(?:\?(?:page=\d+&)?annotation=([A-Z0-9]{8}))?$")
SELECT = re.compile(r"^zotero://select/library/items/([A-Z0-9]{8})$")


def unresolved_zotero_links(page, items):
    """zotero:// links of the page (attributes and popover data, not the script) that do not resolve to an
    attachment (and its annotation) or an item of the snapshot."""
    atts = {att["key"]: {a["key"] for a in att["anns"]} for it in items.values() for att in it["atts"]}
    cut = page.rfind("<script>")
    scan = page[:cut] if cut > 0 else page
    bad = []
    for raw in re.findall(r'zotero://[^"\s<>\']*', scan):
        u = html.unescape(raw).replace("\\/", "/")
        m = OPEN_PDF.match(u)
        if m:
            if m.group(1) not in atts or (m.group(2) and m.group(2) not in atts[m.group(1)]):
                bad.append(u)
            continue
        m = SELECT.match(u)
        if m and m.group(1) in items:
            continue
        bad.append(u)
    return sorted(set(bad))
