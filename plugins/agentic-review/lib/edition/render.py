"""Markdown of the review -> HTML with the chosen citation links, numbered headings, polished tables, catalogue."""

import html
import re
from collections import defaultdict

from . import markdown, zlinks

VERDICT = re.compile(
    r"^(Partially supported|Partly supported|Not supported|Unsupported|Supported|Conditional|"
    r"Plausible|Contested|Refuted|Contradicted|Unverified|Untested)"
)
VCLASS = {
    "Supported": "v-good",
    "Conditional": "v-mid",
    "Plausible": "v-mid",
    "Contested": "v-open",
    "Not supported": "v-poor",
    "Refuted": "v-poor",
    "Partially supported": "v-mid",
    "Partly supported": "v-mid",
    "Unsupported": "v-poor",
    "Contradicted": "v-poor",
    "Unverified": "v-open",
    "Untested": "v-open",
}
UNNUMBERED = {
    "summary",
    "abstract",
    "executive summary",
    "résumé",
    "resume",
    "zusammenfassung",
    "resumen",
    "sommario",
    "sintesi",
    "synthèse",
}


def esc(s):
    return html.escape(s or "", quote=True)


def anchor(label_html, link, aid=None):
    t = link["type"]
    colour = link.get("colour") if link.get("colour") in zlinks.KNOWN_COLOURS else "other"
    cls = f"cite t-{t}" + (f" c-{colour}" if t == "annotation" else "")
    ident = f' id="{aid}"' if aid else ""
    return f'<a{ident} class="{cls}" href="{esc(markdown.safe_url(link["href"] or ""))}">{label_html}</a>'


def tokenise(lines, cits, tag):
    """Replace each citation's markdown link by [label](tag:n) so the chosen href survives the markdown step."""
    by_line = defaultdict(list)
    for n, c in enumerate(cits):
        by_line[c["line"]].append((n, c))
    out = list(lines)
    for no, lst in by_line.items():
        line = out[no]
        for n, c in sorted(lst, key=lambda t: -t[1]["start"]):
            line = f"{line[: c['start']]}[{c['label']}]({tag}:{n}){line[c['end'] :]}"
        out[no] = line
    return out


def render_md(lines, linker, tag, context_h2=None, stop_heading="References"):
    """Markdown lines -> HTML with links; context_h2 gives the citations a section when the text has none."""
    src = ([f"## {context_h2}", ""] if context_h2 else []) + list(lines)
    cits = zlinks.citations(src, linker, stop_heading)
    body = markdown.to_html("\n".join(tokenise(src, cits, tag)), (tag,))
    body = re.sub(
        rf'<a href="{tag}:(\d+)">(.*?)</a>',
        lambda m: anchor(m.group(2), cits[int(m.group(1))]["link"], f"{tag}{m.group(1)}"),
        body,
    )
    if context_h2:
        body = re.sub(r'<h2 id="[^"]*">.*?</h2>\s*', "", body, count=1)
    return body, cits


def number_headings(body, unnumbered=UNNUMBERED):
    toc, n2, n3 = [], 0, 0
    skip = {u.lower() for u in unnumbered}

    def rep(m):
        nonlocal n2, n3
        lvl, hid, text = m.group(1), m.group(2), m.group(3)
        if lvl == "2":
            n3 = 0
            if html.unescape(re.sub(r"<[^>]+>", "", text)).strip().lower() in skip:
                num = ""
            else:
                n2 += 1
                num = str(n2)
        else:
            n3 += 1
            num = f"{n2}.{n3}"
        toc.append((int(lvl), hid, num, re.sub(r"<[^>]+>", "", text)))
        lead = f'<span class="secnum">{num}</span> ' if num else ""
        return f'<h{lvl} id="{hid}">{lead}{text}</h{lvl}>'

    return re.sub(r'<h([23]) id="([^"]+)">(.*?)</h\1>', rep, body), toc


def polish(body):
    body = re.sub(r'<input type="checkbox"[^>]*/?>', '<span class="checkbox"></span>', body)
    body = re.sub(r"<label>(.*?)</label>", r"<span>\1</span>", body, flags=re.S)

    def verdict_table(m):
        t = m.group(0)
        if not re.search(r"<th[^>]*>Verdict</th>", t):
            return t

        def cell(c):
            attrs, inner = c.group(1), c.group(2)
            v = VERDICT.match(inner)
            if not v:
                return c.group(0)
            return (
                f'<td{attrs}><span class="verdict {VCLASS[v.group(1)]}">{v.group(1)}</span>{inner[v.end() :]}</td></tr>'
            )

        return re.sub(r"<td([^>]*)>((?:(?!<td).)*?)</td>\s*</tr>", cell, t, flags=re.S)

    return re.sub(r"<table>.*?</table>", verdict_table, body, flags=re.S)


CELL_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def cell_html(c):
    """A catalogue cell: escaped text, with markdown links to http(s) pages (a paper's repository) as links."""
    out, pos = [], 0
    for m in CELL_LINK.finditer(c):
        out.append(esc(c[pos : m.start()]))
        out.append(
            f'<a class="repo" href="{esc(markdown.safe_url(m.group(2)))}" target="_blank" '
            f'rel="noopener">{esc(m.group(1))}</a>'
        )
        pos = m.end()
    out.append(esc(c[pos:]))
    return "".join(out)


def catalogue_html(text, linker):
    """The catalogue (5-final/catalogue.md): one table per `## ` tier heading, header row from the markdown."""
    out, toc, rows = [], [], 0
    head, open_table, pending = None, False, None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if open_table:
                out.append("</tbody></table>")
                open_table = False
            pending = line[3:].strip()
            head = None
            continue
        if pending is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c) and cells:
                continue
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if re.match(r"^\s*\|?\s*:?-+", nxt):
                head = cells
                title = pending
                hid = "cat-" + re.sub(r"[^a-z]+", "-", title.lower()).strip("-")
                toc.append((3, hid, "", title))
                th = "".join(f"<th>{esc(h)}</th>" for h in head)
                out.append(
                    f'<h3 class="cat" id="{hid}">{esc(title)}</h3><table class="catalogue"><thead><tr>{th}</tr>'
                    "</thead><tbody>"
                )
                open_table = True
                continue
        if not open_table or all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        m = re.search(r"\[([^\]]+)\]\(([^)\s]*)\)", cells[0])
        mark = " †" if "†" in cells[0] else ""
        if m:
            label, url = m.group(1), m.group(2)
            key = linker.label2key.get(label)
            pdf = linker.pdf_href(key) if key else None
            link = {"type": "pdf", "href": pdf} if pdf else {"type": "doi", "href": url}
            first = anchor(esc(label), link) if link["href"] else esc(label)
        else:
            first = esc(cells[0].replace("†", "").strip())
        out.append(
            "<tr><td>" + first + mark + "</td>" + "".join(f"<td>{cell_html(c)}</td>" for c in cells[1:]) + "</tr>"
        )
        rows += 1
    if open_table:
        out.append("</tbody></table>")
    return "\n".join(out), toc, rows
