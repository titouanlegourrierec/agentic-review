"""Markdown -> HTML: pandoc (-f gfm -t html5 --wrap=none) when it is on PATH, else a built-in GFM subset.

The built-in renderer covers what reviews use: ATX and setext headings with pandoc's GFM identifiers, paragraphs,
bullet, numbered and task lists (tight and loose, nested), emphasis, strong, strikethrough, inline code, links,
images, autolinks (including bare URLs), pipe tables with alignment, blockquotes, fenced and indented code,
horizontal rules, hard breaks, entities and backslash escapes. It writes the same HTML shapes as pandoc 3.

Raw HTML in the markdown is passed through by both renderers and then sanitised (sanitize): tags outside a small
allow-list are shown as text, attributes outside an allow-list are dropped, comments are removed, and a link or
image whose URL has a scheme other than http, https, zotero or mailto loses its URL.
Set AR_EDITION_MARKDOWN=builtin (or pandoc) to force a renderer.
"""

import html
import os
import re
import shutil
import subprocess
import unicodedata

# --------------------------------------------------------------------------- entry points


def renderer_name():
    want = (os.environ.get("AR_EDITION_MARKDOWN") or "").strip().lower()
    if want == "builtin":
        return "builtin"
    if want == "pandoc" or shutil.which("pandoc"):
        return "pandoc" if shutil.which("pandoc") else "builtin"
    return "builtin"


def to_html(md, tags=()):
    """HTML5 for a markdown text, sanitised; hrefs of the form <tag>:<n> (citation tokens) are kept."""
    out = None
    pandoc = shutil.which("pandoc")
    if renderer_name() == "pandoc" and pandoc:
        try:
            out = subprocess.run(
                [pandoc, "-f", "gfm", "-t", "html5", "--wrap=none"],
                input=md,
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            out = None  # a broken pandoc: fall back to the built-in renderer
    if out is None:
        out = render(md)
    return sanitize(out, tags)


# --------------------------------------------------------------------------- sanitiser

SAFE_SCHEMES = ("http", "https", "zotero", "mailto")
ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "blockquote",
    "hr",
    "pre",
    "code",
    "em",
    "strong",
    "del",
    "s",
    "a",
    "img",
    "br",
    "label",
    "input",
    "span",
    "div",
    "sup",
    "sub",
    "b",
    "i",
    "u",
    "small",
    "caption",
    "colgroup",
    "col",
    "dl",
    "dt",
    "dd",
    "kbd",
    "mark",
    "abbr",
    "cite",
    "q",
    "figure",
    "figcaption",
    # MathML, which pandoc writes for $...$ in gfm
    "math",
    "semantics",
    "annotation",
    "mrow",
    "mi",
    "mo",
    "mn",
    "ms",
    "mtext",
    "mspace",
    "msub",
    "msup",
    "msubsup",
    "mfrac",
    "msqrt",
    "mroot",
    "mover",
    "munder",
    "munderover",
    "mtable",
    "mtr",
    "mtd",
    "mstyle",
    "mpadded",
    "mphantom",
    "menclose",
}
ALLOWED_ATTRS = {
    "id",
    "class",
    "href",
    "src",
    "alt",
    "title",
    "style",
    "type",
    "start",
    "checked",
    "disabled",
    "colspan",
    "rowspan",
    "display",
    "xmlns",
    "encoding",
    "mathvariant",
    "stretchy",
    "form",
    "fence",
    "accent",
    "accentunder",
    "columnalign",
    "rspace",
    "lspace",
    "linethickness",
    "separator",
    "scriptlevel",
    "displaystyle",
}
TAG = re.compile(r'<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9-]*)((?:[^>"\']|"[^"]*"|\'[^\']*\')*)>', re.S)
ATTR = re.compile(r'([^\s"\'>/=]+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'=<>`]+)))?')
STYLE_OK = re.compile(r"text-align:\s*(left|right|center);?")


def url_ok(u, tags=()):
    """True for http(s), zotero, mailto, in-page (#...) and citation-token URLs; False for javascript:, data: …"""
    u = html.unescape(u or "").strip()
    if not u or u.startswith("#"):
        return True
    m = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", re.sub(r"[\x00-\x20]", "", u))
    if not m:
        return not re.match(r"\s*[A-Za-z][A-Za-z0-9+.-]*\s*:", u)  # relative URL
    scheme = m.group(1).lower()
    return scheme in SAFE_SCHEMES or (scheme in tags and re.fullmatch(r"[a-z]+:\d+", u) is not None)


def safe_url(u, tags=()):
    """u when url_ok, else '#'."""
    return u if url_ok(u, tags) else "#"


def sanitize(text, tags=()):
    def tag(m):
        if m.group(0).startswith("<!--"):
            return ""
        close, name, rest = m.group(1), m.group(2), m.group(3)
        if name.lower() not in ALLOWED_TAGS:
            return html.escape(m.group(0), quote=False)
        if close:
            return f"</{name}>"
        selfclose = rest.rstrip().endswith("/")
        attrs, changed = [], False
        for a in ATTR.finditer(rest.rstrip().rstrip("/")):
            k = a.group(1).lower()
            v = a.group(2) if a.group(2) is not None else a.group(3) if a.group(3) is not None else a.group(4)
            if (
                k not in ALLOWED_ATTRS
                or (k in ("href", "src") and not url_ok(v, tags))
                or (k == "style" and not STYLE_OK.fullmatch((v or "").strip()))
                or (k == "type" and (v or "").lower() not in ("checkbox", "1", "a", "i"))
            ):
                changed = True
                continue
            attrs.append((k, v))
        if not changed:
            return m.group(0)
        out = "".join(f" {k}" if v is None else f' {k}="{html.escape(html.unescape(v), quote=True)}"' for k, v in attrs)
        return f"<{name}{out}{' /' if selfclose else ''}>"

    return TAG.sub(tag, text)


# --------------------------------------------------------------------------- identifiers (pandoc gfm_auto_identifiers)


def gfm_identifier(text):
    out = []
    for c in text.lower():
        if c.isspace():
            out.append("-")
        elif c.isalnum() or c in "-_" or unicodedata.category(c) in ("Mn", "Mc", "Me", "Pc"):
            out.append(c)
    return "".join(out)


def plain_text(html_fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", html_fragment))


# --------------------------------------------------------------------------- built-in renderer: blocks


def esc_text(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_attr(s):
    return esc_text(s).replace('"', "&quot;")


ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
BQ = re.compile(r"^ {0,3}> ?")
ITEM = re.compile(r"^( {0,3})([-+*]|\d{1,9}[.)])([ \t]+|$)")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
DELIM_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|"
    "div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|"
    "html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|"
    "summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul"
)
HTML_BLOCK1 = re.compile(r"^ {0,3}<(script|pre|style|textarea)(\s|>|$)", re.I)
HTML_BLOCK2 = re.compile(r"^ {0,3}<!--")
HTML_BLOCK6 = re.compile(rf"^ {{0,3}}</?({BLOCK_TAGS})(\s|/?>|$)", re.I)
OPEN_TAG = (
    r'<[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*(?:\s*=\s*(?:[^\s"\'=<>`]+|\'[^\']*\'|"[^"]*"))?)*\s*/?>'
)
CLOSE_TAG = r"</[A-Za-z][A-Za-z0-9-]*\s*>"
HTML_BLOCK7 = re.compile(rf"^ {{0,3}}(?:{OPEN_TAG}|{CLOSE_TAG})\s*$")


def expand_tabs(line):
    return line.expandtabs(4) if "\t" in line else line


def item_marker(line):
    """(indent, marker, content_column, rest) of a list item line, or None."""
    m = ITEM.match(line)
    if not m:
        return None
    ind, marker, sp = len(m.group(1)), m.group(2), m.group(3)
    rest = line[m.end() :]
    if not rest.strip():
        width = ind + len(marker) + 1
        return ind, marker, width, ""
    if len(sp) > 4:
        sp = " "
        rest = line[m.start(3) + 1 :]
    return ind, marker, ind + len(marker) + len(sp), rest


def starts_block(line, in_paragraph=True):
    """True when a line interrupts a paragraph."""
    if ATX.match(line) or HR.match(line) or FENCE.match(line) or BQ.match(line):
        return True
    if HTML_BLOCK1.match(line) or HTML_BLOCK2.match(line) or HTML_BLOCK6.match(line):
        return True
    im = item_marker(line)
    if im and im[3].strip():
        marker = im[1]
        if marker[0].isdigit():
            return marker[:-1] == "1" or not in_paragraph
        return True
    return False


def split_cells(row):
    s = row.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, i = [], [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    cells.append("".join(cur).strip())
    return cells


class Block:
    def __init__(self, kind, **kw):
        self.kind = kind
        self.blank_before = False
        self.__dict__.update(kw)


def parse_blocks(lines):
    """Block structure of a list of lines (tabs expanded)."""
    blocks, i, n = [], 0, len(lines)
    blank = False

    def add(b):
        nonlocal blank
        b.blank_before = blank and bool(blocks)
        blank = False
        blocks.append(b)

    while i < n:
        line = lines[i]
        if not line.strip():
            blank = True
            i += 1
            continue
        m = FENCE.match(line)
        if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
            ind, fence, info = len(m.group(1)), m.group(2), m.group(3).strip()
            body, i = [], i + 1
            while i < n:
                close = re.match(r"^ {0,3}(" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",})[ \t]*$", lines[i])
                if close:
                    i += 1
                    break
                body.append(re.sub(rf"^ {{0,{ind}}}", "", lines[i]))
                i += 1
            add(Block("code", text="\n".join(body), info=info.split()[0] if info else ""))
            continue
        m = ATX.match(line)
        if m:
            add(Block("heading", level=len(m.group(1)), text=(m.group(2) or "").strip()))
            i += 1
            continue
        if HR.match(line):
            add(Block("hr"))
            i += 1
            continue
        if line.startswith("    "):
            body = []
            while i < n and (lines[i].startswith("    ") or not lines[i].strip()):
                body.append(lines[i][4:])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            add(Block("code", text="\n".join(body), info=""))
            continue
        if BQ.match(line):
            inner = []
            while i < n and lines[i].strip():
                if BQ.match(lines[i]):
                    inner.append(BQ.sub("", lines[i], count=1))
                elif inner and not starts_block(lines[i]):
                    inner.append(lines[i])  # lazy continuation
                else:
                    break
                i += 1
            add(Block("quote", children=parse_blocks(inner)))
            continue
        m_html = HTML_BLOCK1.match(line)
        if m_html:
            tagname = m_html.group(1).lower()
            body = []
            while i < n:
                body.append(lines[i])
                i += 1
                if re.search(rf"</{tagname}>", body[-1], re.I):
                    break
            add(Block("html", text="\n".join(body)))
            continue
        if HTML_BLOCK2.match(line):
            body = []
            while i < n:
                body.append(lines[i])
                i += 1
                if "-->" in body[-1]:
                    break
            add(Block("html", text="\n".join(body)))
            continue
        if HTML_BLOCK6.match(line) or HTML_BLOCK7.match(line):
            body = []
            while i < n and lines[i].strip():
                body.append(lines[i])
                i += 1
            add(Block("html", text="\n".join(body)))
            continue
        im = item_marker(line)
        if im:
            i, lst = parse_list(lines, i)
            add(lst)
            continue
        if "|" in line and i + 1 < n and DELIM_ROW.match(lines[i + 1]) and "-" in lines[i + 1]:
            head, delim = split_cells(line), split_cells(lines[i + 1])
            if len(head) == len(delim):
                aligns = []
                for d in delim:
                    d = d.strip()
                    aligns.append(
                        "center"
                        if d.startswith(":") and d.endswith(":")
                        else "left"
                        if d.startswith(":")
                        else "right"
                        if d.endswith(":")
                        else None
                    )
                rows, i = [], i + 2
                while i < n and lines[i].strip() and not starts_block(lines[i]):
                    cells = split_cells(lines[i])
                    rows.append((cells + [""] * len(head))[: len(head)])
                    i += 1
                add(Block("table", head=head, aligns=aligns, rows=rows))
                continue
        # paragraph, possibly a setext heading
        para = [line.lstrip()]
        i += 1
        heading = None
        while i < n and lines[i].strip():
            s = SETEXT.match(lines[i])
            if s:
                heading = 1 if s.group(1)[0] == "=" else 2
                i += 1
                break
            if starts_block(lines[i]):
                break
            para.append(lines[i].lstrip())
            i += 1
        text = "\n".join(para)
        if heading:
            add(Block("heading", level=heading, text=text.strip()))
        else:
            add(Block("para", text=text))
    return blocks


def parse_list(lines, i):
    """One list starting at lines[i]: returns (next index, Block('list'))."""
    n = len(lines)
    first = item_marker(lines[i])
    ordered = first[1][0].isdigit()
    delim = first[1][-1] if ordered else first[1]
    start = int(first[1][:-1]) if ordered else None
    task_kind = None
    items, loose = [], False
    while i < n:
        im = item_marker(lines[i])
        if not im:
            break
        _ind, marker, width, rest = im
        if marker[0].isdigit() != ordered or (marker[-1] if ordered else marker) != delim:
            break
        if HR.match(lines[i]):
            break
        is_task = (not ordered) and re.match(r"\[[ xX]\](?:[ \t]|$)", rest) is not None
        if task_kind is None:
            task_kind = is_task
        elif is_task != task_kind:
            break
        body = [rest]
        i += 1
        trailing_blank = 0
        while i < n:
            line = lines[i]
            if not line.strip():
                body.append("")
                trailing_blank += 1
                i += 1
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent >= width:
                body.append(line[width:])
                trailing_blank = 0
                i += 1
                continue
            if trailing_blank == 0 and body and body[-1].strip() and not starts_block(line) and not item_marker(line):
                body.append(line.lstrip())  # lazy continuation of a paragraph
                i += 1
                continue
            break
        while body and not body[-1].strip():
            body.pop()
        children = parse_blocks(body)
        if any(b.blank_before for b in children[1:]):
            loose = True
        checked = None
        if is_task and children and children[0].kind == "para":
            checked = children[0].text[1] in "xX"
            children[0].text = children[0].text[3:].lstrip(" \t")
        items.append({"children": children, "task": checked})
        nxt = item_marker(lines[i]) if i < n else None
        if trailing_blank and nxt and nxt[1][0].isdigit() == ordered and (nxt[1][-1] if ordered else nxt[1]) == delim:
            loose = True
    return i, Block("list", ordered=ordered, start=start, items=items, loose=loose, task=bool(task_kind))


def render_blocks(blocks, tight=False, ids=None):
    if ids is None:
        ids = set()
    out = []
    for b in blocks:
        if b.kind == "para":
            inner = render_inline(b.text)
            out.append(inner if tight else f"<p>{inner}</p>")
        elif b.kind == "heading":
            inner = render_inline(b.text)
            ident = gfm_identifier(plain_text(inner)) or "section"
            base, k = ident, 0
            while ident in ids:
                k += 1
                ident = f"{base}-{k}"
            ids.add(ident)
            out.append(f'<h{b.level} id="{esc_attr(ident)}">{inner}</h{b.level}>')
        elif b.kind == "hr":
            out.append("<hr />")
        elif b.kind == "code":
            cls = f' class="{esc_attr(b.info)}"' if b.info else ""
            out.append(f"<pre{cls}><code>{esc_attr(b.text).replace(chr(39), '&#39;')}</code></pre>")
        elif b.kind == "quote":
            out.append("<blockquote>\n" + render_blocks(b.children, False, ids) + "\n</blockquote>")
        elif b.kind == "html":
            out.append(b.text)
        elif b.kind == "table":

            def cell(tagname, text, align):
                style = f' style="text-align: {align};"' if align else ""
                return f"<{tagname}{style}>{render_inline(text)}</{tagname}>"

            rows = (
                ["<table>", "<thead>", "<tr>"]
                + [cell("th", h, a) for h, a in zip(b.head, b.aligns)]
                + ["</tr>", "</thead>"]
            )
            if b.rows:
                rows.append("<tbody>")
                for r in b.rows:
                    rows += ["<tr>"] + [cell("td", c, a) for c, a in zip(r, b.aligns)] + ["</tr>"]
                rows.append("</tbody>")
            rows.append("</table>")
            out.append("\n".join(rows))
        elif b.kind == "list":
            if b.ordered:
                open_tag = '<ol type="1">' if b.start == 1 else f'<ol start="{b.start}" type="1">'
            else:
                open_tag = '<ul class="task-list">' if b.task else "<ul>"
            lis = []
            for it in b.items:
                kids = it["children"]
                parts = []
                for j, c in enumerate(kids):
                    if c.kind == "para" and j == 0 and it["task"] is not None:
                        box = '<input type="checkbox" checked="" />' if it["task"] else '<input type="checkbox" />'
                        inner = f"<label>{box}{render_inline(c.text)}</label>"
                        parts.append(inner if not b.loose else f"<p>{inner}</p>")
                    else:
                        parts.append(render_blocks([c], not b.loose, ids))
                lis.append("<li>" + "\n".join(parts) + "</li>")
            out.append(open_tag + "\n" + "\n".join(lis) + "\n" + ("</ol>" if b.ordered else "</ul>"))
    return "\n".join(out)


def render(md):
    """HTML5 for a markdown text with the built-in GFM subset (pandoc's output shapes)."""
    lines = [expand_tabs(ln) for ln in md.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    if lines and lines[0].rstrip() == "---":  # YAML metadata block, dropped like pandoc does
        end = next((i for i in range(1, len(lines)) if lines[i].rstrip() in ("---", "...")), None)
        if end is not None and all(
            ":" in ln or not ln.strip() or ln.startswith((" ", "-", "#")) for ln in lines[1:end]
        ):
            lines = lines[end + 1 :]
    return render_blocks(parse_blocks(lines), False, set()) + "\n"


# --------------------------------------------------------------------------- built-in renderer: inlines

PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
ENTITY = re.compile(r"&(?:#[xX][0-9a-fA-F]{1,6}|#[0-9]{1,7}|[A-Za-z][A-Za-z0-9]{1,31});")
AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*)>")
EMAIL_AUTOLINK = re.compile(
    r"<([A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)>"
)
RAW_INLINE = re.compile(rf"{OPEN_TAG}|{CLOSE_TAG}|<!--.*?-->|<\?.*?\?>|<![A-Z]+\s[^>]*>|<!\[CDATA\[.*?\]\]>", re.S)
BARE = re.compile(r"(?:(?:https?://)|(?:www\.))[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*[^\s<]*")


def is_punct(c):
    return c in PUNCT or (bool(c) and unicodedata.category(c).startswith(("P", "S")))


class Node:
    __slots__ = ("attrs", "children", "delim", "kind", "next", "prev", "text")

    def __init__(self, kind, text="", children=None, attrs=None):
        self.kind, self.text, self.children, self.attrs = kind, text, children or [], attrs or {}
        self.prev = self.next = None
        self.delim = None


class Delim:
    def __init__(self, node, char, count, can_open, can_close, bracket=False, image=False):
        self.node, self.char, self.count, self.orig = node, char, count, count
        self.can_open, self.can_close = can_open, can_close
        self.bracket, self.image, self.active = bracket, image, True
        self.prev = self.next = None


def parse_link_tail(s, i):
    """After ']' at s[i-1]: parse '(dest "title")'. Returns (dest, title, end) or None."""
    if i >= len(s) or s[i] != "(":
        return None
    j = i + 1
    while j < len(s) and s[j] in " \t\n":
        j += 1
    dest = ""
    if j < len(s) and s[j] == "<":
        k = j + 1
        while k < len(s) and s[k] not in ">\n":
            if s[k] == "\\" and k + 1 < len(s):
                k += 1
            k += 1
        if k >= len(s) or s[k] != ">":
            return None
        dest, j = s[j + 1 : k], k + 1
    else:
        depth, k = 0, j
        while k < len(s):
            c = s[k]
            if c == "\\" and k + 1 < len(s) and s[k + 1] in PUNCT:
                k += 2
                continue
            if c in " \t\n" or ord(c) < 32:
                break
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            k += 1
        if depth:
            return None
        dest, j = s[j:k], k
    title = None
    k = j
    while k < len(s) and s[k] in " \t\n":
        k += 1
    if k < len(s) and s[k] in "\"'(" and k > j:
        close = ")" if s[k] == "(" else s[k]
        e = k + 1
        while e < len(s) and s[e] != close:
            if s[e] == "\\" and e + 1 < len(s):
                e += 1
            e += 1
        if e >= len(s):
            return None
        title, k = s[k + 1 : e], e + 1
        while k < len(s) and s[k] in " \t\n":
            k += 1
    if k < len(s) and s[k] == ")":
        return unescape_md(dest), (unescape_md(title) if title is not None else None), k + 1
    return None


def unescape_md(s):
    s = re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", s)
    return ENTITY.sub(lambda m: html.unescape(m.group(0)), s)


def render_inline(text):
    return "".join(emit(n) for n in parse_inline(text))


def parse_inline(s):
    """Inline nodes of a paragraph, heading or table cell (CommonMark delimiter algorithm)."""
    head = Node("root")
    tail = head
    stack = []  # delimiter records, in order
    buf = []

    def append(node):
        nonlocal tail
        node.prev, tail.next = tail, node
        tail = node
        return node

    def flush():
        if buf:
            append(Node("text", "".join(buf)))
            buf.clear()

    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            if i + 1 < n and s[i + 1] == "\n":
                flush()
                append(Node("br"))
                i += 2
                while i < n and s[i] == " ":
                    i += 1
                continue
            if i + 1 < n and s[i + 1] in PUNCT:
                buf.append(s[i + 1])
                i += 2
                continue
            buf.append("\\")
            i += 1
            continue
        if c == "`":
            j = i
            while j < n and s[j] == "`":
                j += 1
            ticks, k, found = j - i, j, -1
            while k < n:
                if s[k] == "`":
                    e = k
                    while e < n and s[e] == "`":
                        e += 1
                    if e - k == ticks:
                        found = k
                        break
                    k = e
                else:
                    k += 1
            if found < 0:
                buf.append(s[i:j])
                i = j
                continue
            code = s[j:found].replace("\n", " ")
            if code.startswith(" ") and code.endswith(" ") and code.strip(" "):
                code = code[1:-1]
            flush()
            append(Node("code", code))
            i = found + ticks
            continue
        if c == "<":
            m = AUTOLINK.match(s, i)
            if m:
                flush()
                append(Node("autolink", m.group(1), attrs={"href": m.group(1)}))
                i = m.end()
                continue
            m = EMAIL_AUTOLINK.match(s, i)
            if m:
                flush()
                append(Node("autolink", m.group(1), attrs={"href": "mailto:" + m.group(1)}))
                i = m.end()
                continue
            m = RAW_INLINE.match(s, i)
            if m:
                flush()
                append(Node("raw", m.group(0)))
                i = m.end()
                continue
            buf.append("<")
            i += 1
            continue
        if c == "&":
            m = ENTITY.match(s, i)
            if m:
                buf.append(html.unescape(m.group(0)))
                i = m.end()
                continue
            buf.append("&")
            i += 1
            continue
        if c == "\n":
            joined = "".join(buf)
            stripped = joined.rstrip(" ")
            hard = len(joined) - len(stripped) >= 2
            buf.clear()
            if stripped:
                buf.append(stripped)
            flush()
            if not hard and tail.kind == "text" and tail.delim is None:
                tail.text = tail.text.rstrip(" ")
            append(Node("br" if hard else "soft"))
            i += 1
            while i < n and s[i] == " ":
                i += 1
            continue
        if c in "*_~":
            j = i
            while j < n and s[j] == c:
                j += 1
            run = j - i
            if c == "~" and run > 2:
                buf.append(s[i:j])
                i = j
                continue
            before = s[i - 1] if i > 0 else " "
            after = s[j] if j < n else " "
            ws_before, ws_after = before.isspace(), after.isspace()
            p_before, p_after = is_punct(before), is_punct(after)
            left = not ws_after and (not p_after or ws_before or p_before)
            right = not ws_before and (not p_before or ws_after or p_after)
            if c == "_":
                can_open = left and (not right or p_before)
                can_close = right and (not left or p_after)
            else:
                can_open, can_close = left, right
            flush()
            node = append(Node("text", s[i:j]))
            d = Delim(node, c, run, can_open, can_close)
            node.delim = d
            stack.append(d)
            i = j
            continue
        if c in "hw" and (i == 0 or s[i - 1].isspace() or s[i - 1] in "*_~("):
            url = bare_url(s, i)
            if url:
                flush()
                append(Node("autolink", url, attrs={"href": url if url.startswith("http") else "http://" + url}))
                i += len(url)
                continue
        if c == "!" and i + 1 < n and s[i + 1] == "[":
            flush()
            node = append(Node("text", "!["))
            stack.append(Delim(node, "[", 1, False, False, bracket=True, image=True))
            i += 2
            continue
        if c == "[":
            flush()
            node = append(Node("text", "["))
            stack.append(Delim(node, "[", 1, False, False, bracket=True))
            i += 1
            continue
        if c == "]":
            oi = next((k for k in range(len(stack) - 1, -1, -1) if stack[k].bracket), None)
            if oi is None:
                buf.append("]")
                i += 1
                continue
            opener = stack[oi]
            parsed = parse_link_tail(s, i + 1) if opener.active else None
            if parsed is None:
                stack.pop(oi)
                buf.append("]")
                i += 1
                continue
            flush()
            dest, title, end = parsed
            _emphasis(stack[oi + 1 :])
            del stack[oi + 1 :]
            kids, nd = [], opener.node.next
            while nd:
                kids.append(nd)
                nd = nd.next
            prev = opener.node.prev
            prev.next = None
            tail = prev
            for k in kids:
                k.prev = k.next = None
            append(Node("image" if opener.image else "link", children=kids, attrs={"href": dest, "title": title}))
            stack.pop(oi)
            if not opener.image:
                for d in stack[:oi]:
                    if d.bracket and not d.image:
                        d.active = False
            i = end
            continue
        buf.append(c)
        i += 1
    flush()
    _emphasis(stack)
    out, nd = [], head.next
    while nd:
        out.append(nd)
        nd = nd.next
    if out and out[-1].kind == "text":
        out[-1].text = out[-1].text.rstrip(" ")
    return out


def _emphasis(ds):
    """Resolve emphasis on an ordered list of delimiter records (bracket records are skipped)."""
    ds = [d for d in ds if not d.bracket]
    alive = list(ds)
    openers_bottom = {}
    ci = 0
    while ci < len(alive):
        closer = alive[ci]
        if not closer.can_close or closer.count == 0:
            ci += 1
            continue
        key = (closer.char, closer.can_open, closer.orig % 3)
        lo = openers_bottom.get(key, -1)
        oi = ci - 1
        found = None
        while oi > lo:
            op = alive[oi]
            if op.char == closer.char and op.can_open and op.count > 0:
                if closer.char == "~":
                    if op.count == closer.count:
                        found = oi
                        break
                else:
                    odd = (
                        (op.can_close or closer.can_open)
                        and (op.orig + closer.orig) % 3 == 0
                        and not (op.orig % 3 == 0 and closer.orig % 3 == 0)
                    )
                    if not odd:
                        found = oi
                        break
            oi -= 1
        if found is None:
            openers_bottom[key] = ci - 1
            if not closer.can_open:
                alive.pop(ci)
                continue
            ci += 1
            continue
        op = alive[found]
        if closer.char == "~":
            use, kind = closer.count, "del"
        else:
            use = 2 if op.count >= 2 and closer.count >= 2 else 1
            kind = "strong" if use == 2 else "em"
        op.count -= use
        closer.count -= use
        op.node.text = op.node.text[: len(op.node.text) - use]
        closer.node.text = closer.node.text[use:]
        # wrap the nodes between opener and closer
        kids = []
        nd = op.node.next
        while nd is not closer.node:
            kids.append(nd)
            nd = nd.next
        wrap = Node(kind, children=kids)
        op.node.next, wrap.prev = wrap, op.node
        wrap.next, closer.node.prev = closer.node, wrap
        for k in kids:
            k.prev = k.next = None
        # relink children as a chain (for emit)
        # delimiters between opener and closer are removed
        del alive[found + 1 : ci]
        ci = found + 1
        if op.count == 0:
            _unlink(op.node)
            alive.pop(found)
            ci -= 1
        if closer.count == 0:
            _unlink(closer.node)
            alive.pop(ci)


def _unlink(node):
    if node.prev:
        node.prev.next = node.next
    if node.next:
        node.next.prev = node.prev
    node.prev = node.next = None


def bare_url(s, i):
    """A GFM extended autolink (http://, https:// or www.) starting at s[i], trailing punctuation removed."""
    m = BARE.match(s, i)
    if not m:
        return None
    url = m.group(0)
    while url:
        if url[-1] in "?!.,:*_~'\"":
            url = url[:-1]
            continue
        if url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
            continue
        em = re.search(r"&[A-Za-z0-9]+;$", url)
        if em:
            url = url[: em.start()]
            continue
        break
    m_host = re.match(r"(?:https?://)?([^/?#]*)", url)
    host = m_host.group(1) if m_host else ""
    if "." not in host or host.endswith(".") or host.startswith("."):
        return None
    return url


def emit(nd, in_link=False):
    k = nd.kind
    if k == "text":
        return esc_text(re.sub(r"[ \t]+", " ", nd.text))  # pandoc keeps one space between words
    if k == "soft":
        return " "
    if k == "br":
        return "<br />\n"
    if k == "code":
        return f"<code>{esc_text(nd.text)}</code>"
    if k == "raw":
        return nd.text
    if k == "autolink":
        if in_link:
            return esc_text(nd.text)
        return f'<a href="{esc_attr(nd.attrs["href"])}">{esc_text(nd.text)}</a>'
    if k in ("em", "strong", "del"):
        return f"<{k}>" + "".join(emit(c, in_link) for c in nd.children) + f"</{k}>"
    if k == "link":
        title = nd.attrs.get("title")
        t = f' title="{esc_attr(title)}"' if title else ""
        return f'<a href="{esc_attr(nd.attrs["href"])}"{t}>' + "".join(emit(c, True) for c in nd.children) + "</a>"
    if k == "image":
        alt = plain_text("".join(emit(c, True) for c in nd.children))
        title = nd.attrs.get("title")
        t = f' title="{esc_attr(title)}"' if title else ""
        return f'<img src="{esc_attr(nd.attrs["href"])}"{t} alt="{esc_attr(alt)}" />'
    return ""
