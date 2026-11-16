"""Shared helpers for the agentic-review scripts (standard library only, Python 3.9+).

Everything here is review-agnostic: topic words, tags, collections and section lists come from the review's
own review.json and schema.json.
"""

import contextlib
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = PLUGIN_ROOT / "templates"
USER_AGENT = "agentic-review/0.3 (+https://github.com)"
TIERS = ["core", "boundary", "adjacent"]
TIER_TITLES = {"core": "Core", "boundary": "Boundary", "adjacent": "Adjacent"}
DEPTH_RANK = {"full-text": 3, "abstract": 2, "secondary": 1}
CONF_RANK = {"high": 3, "medium": 2, "low": 1}
EMPTY_STRINGS = {"", "null", "none", "n/a", "unknown"}

# Paths inside a review folder (CONTRACT section 1).
CORPUS = "2-merged/corpus.jsonl"
MERGED = "2-merged/merged.jsonl"
OMISSIONS = "4-checks/omissions_checked.jsonl"
BACKGROUND = "3-analysis/background_refs.jsonl"
RETIERING = "5-final/retiering.json"
CITEMAP = "5-final/citation_map.tsv"
RIGOR = "4-checks/rigor_scores.jsonl"
CLAIMS = "4-checks/claims_check.jsonl"
COMPARISON_CLASS = "3-analysis/comparison_class.jsonl"
REVIEW_MD = "5-final/review.md"


# --------------------------------------------------------------------------- small utilities


def now_iso():
    """Local time, ISO 8601, to the minute."""
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def review_dir(arg):
    """Validate the review-folder argument (exit 2 when it is not a folder)."""
    p = Path(arg).expanduser()
    if not p.is_dir():
        die(f"error: review folder not found: {arg}", 2)
    return p.resolve()


def resolve(rdir, p):
    """A path given on the command line: absolute as is; relative to the review folder, else to the cwd."""
    p = Path(p).expanduser()
    if p.is_absolute():
        return p
    in_review = Path(rdir) / p
    if in_review.exists() or not p.exists():
        return in_review
    return p.resolve()


def rel(rdir, p):
    try:
        return str(Path(p).resolve().relative_to(Path(rdir).resolve()))
    except ValueError:
        return str(p)


def natural_key(s):
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", str(s)) if t != ""]


def md_cell(s, n=None):
    """One markdown table cell: single line, no pipes, optionally truncated to n characters."""
    s = " ".join(str("" if s is None else s).split()).replace("|", "/")
    return (s[: n - 1] + "…") if n and len(s) > n else s


def to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def is_empty(v):
    if v is None or v == [] or v == {}:
        return True
    return isinstance(v, str) and v.strip().lower() in EMPTY_STRINGS


# --------------------------------------------------------------------------- files


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def iter_jsonl(path):
    """Yield (line_number, object_or_None, error_or_None) for every non-blank line."""
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                yield i, json.loads(line), None
            except json.JSONDecodeError as e:
                yield i, None, f"invalid JSON: {e.msg} (column {e.colno})"


def load_jsonl(path, missing_ok=False):
    """Records of a JSONL file (dicts only). Raises ValueError on a bad line."""
    path = Path(path)
    if missing_ok and not path.exists():
        return []
    out = []
    for i, obj, err in iter_jsonl(path):
        if err:
            raise ValueError(f"{path}:{i}: {err}")
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{i}: not a JSON object")
        out.append(obj)
    return out


def save_jsonl(path, records):
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_review(rdir):
    """review.json of the review ({} when absent)."""
    data = load_json(Path(rdir) / "review.json", {})
    return data if isinstance(data, dict) else {}


def base_schema():
    return load_json(TEMPLATES / "record.schema.json", {})


def load_schema(rdir=None, path=None):
    """The review's schema.json, else the plugin's base record schema. Returns (schema, path)."""
    candidates = [Path(path)] if path else []
    if rdir is not None:
        candidates.append(Path(rdir) / "schema.json")
    candidates.append(TEMPLATES / "record.schema.json")
    for c in candidates:
        if c.exists():
            return load_json(c), c
    raise FileNotFoundError("no record schema found")


def domain_fields(schema):
    """Fields the review's schema adds on top of the base schema (Phase 0 domain fields), in schema order."""
    base = set((base_schema().get("properties") or {}).keys())
    return [f for f in (schema.get("properties") or {}) if f not in base]


# --------------------------------------------------------------------------- JSON-Schema subset

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def _short(v, n=60):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def validate(value, schema, path=""):
    """Validate value against a JSON-Schema subset; return a list of (path, message).

    Supported: type (string or list, incl. "null"), required, enum, const, pattern, minLength, maxLength,
    minimum, maximum, minItems, maxItems, properties (nested), items. Unknown properties are allowed.
    """
    errors = []
    where = path or "(record)"
    if not isinstance(schema, dict):
        return errors
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES.get(x, lambda v: True)(value) for x in types):
            errors.append((where, f"expected {' or '.join(types)}, got {_short(value)}"))
            return errors
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join("null" if x is None else str(x) for x in schema["enum"])
        errors.append((where, f"{_short(value)} not one of: {allowed}"))
    if "const" in schema and value != schema["const"]:
        errors.append((where, f"must be {_short(schema['const'])}"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append((where, f"shorter than {schema['minLength']} characters"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append((where, f"longer than {schema['maxLength']} characters"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append((where, f"{_short(value)} does not match {schema['pattern']}"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append((where, f"{value} < minimum {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append((where, f"{value} > maximum {schema['maximum']}"))
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append((f"{path}.{req}" if path else req, "required field missing"))
        for name, sub in (schema.get("properties") or {}).items():
            if name in value:
                errors.extend(validate(value[name], sub, f"{path}.{name}" if path else name))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append((where, f"fewer than {schema['minItems']} items"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append((where, f"more than {schema['maxItems']} items"))
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{where}[{i}]"))
    return errors


# --------------------------------------------------------------------------- identifiers and keys


def norm_doi(d):
    if not isinstance(d, str) or not d.strip():
        return None
    d = d.strip().lower()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d or None


def clean_doi(d):
    """A DOI without URL / 'doi:' prefix, case preserved (for links); None when empty."""
    if not isinstance(d, str) or not d.strip():
        return None
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d.strip(), flags=re.I)
    return re.sub(r"^doi:\s*", "", d, flags=re.I) or None


def norm_arxiv(a):
    if not isinstance(a, str) or not a.strip():
        return None
    a = a.strip()
    a = re.sub(r"^(https?://)?(export\.)?arxiv\.org/(abs|pdf|html)/", "", a, flags=re.I)
    a = re.sub(r"^arxiv:\s*", "", a, flags=re.I)
    a = re.sub(r"\.pdf$", "", a)
    a = re.sub(r"v\d+$", "", a)
    return a or None


def is_arxiv_doi(doi):
    return bool(doi) and doi.lower().startswith("10.48550/")


def record_ids(r):
    """Normalised identifiers of a record: {('doi', x), ('arxiv', y)}; arXiv DOIs count as arXiv ids."""
    ids = set()
    d = norm_doi(r.get("doi"))
    if d:
        if is_arxiv_doi(d) and d.startswith("10.48550/arxiv."):
            ids.add(("arxiv", d.split("arxiv.", 1)[1]))
        else:
            ids.add(("doi", d))
    a = norm_arxiv(r.get("arxiv_id"))
    if a:
        ids.add(("arxiv", a.lower()))
    return ids


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_title(t):
    if not isinstance(t, str):
        return ""
    t = re.sub(r"<[^>]+>", "", t.lower())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def norm_text(t):
    """Like norm_title but folds accents first (used to compare against API metadata)."""
    if not isinstance(t, str):
        return ""
    return norm_title(fold(t))


def similar(a, b, threshold):
    """True when SequenceMatcher(a, b).ratio() >= threshold (with the cheap upper bounds first)."""
    if not a or not b:
        return False
    sm = SequenceMatcher(None, a, b)
    return sm.real_quick_ratio() >= threshold and sm.quick_ratio() >= threshold and sm.ratio() >= threshold


# ---------------------------------------------------------------- author names


def is_initials(tok):
    """'J', 'JA', 'J.A.', 'K.-M.', 'İ' -> True (one to four capital letters with optional dots / hyphens)."""
    core = tok.replace(".", "").replace("-", "")
    return 1 <= len(core) <= 4 and core.isalpha() and core.isupper()


PARTICLES = {
    "van",
    "von",
    "der",
    "den",
    "de",
    "del",
    "della",
    "di",
    "da",
    "du",
    "le",
    "la",
    "dos",
    "das",
    "ten",
    "ter",
    "bin",
    "al",
    "el",
    "st",
    "mc",
}
ET_AL = re.compile(r"\bet\.?\s*al\.?", re.I)


def split_authors(r):
    """Author list in any of the formats agents write:
    'Smith J, Jones K' (the contract's format), 'John Smith; Kate Jones', 'Smith, John; Jones, Kate',
    'Smith, John and Jones, Kate', 'John Smith and Kate Jones'. 'et al.' is dropped (see has_et_al)."""
    s = ET_AL.sub("", r.get("authors") or "").strip(" ,;")
    if ";" in s:
        parts = s.split(";")
    elif re.search(r"\s+and\s+", s) and all("," in p for p in re.split(r"\s+and\s+", s)):
        parts = re.split(r"\s+and\s+", s)
    else:
        parts = re.split(r",\s*|\s+and\s+|\s*&\s*", s)
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


def has_et_al(r):
    return bool(ET_AL.search(r.get("authors") or ""))


def surname(author):
    """'Smith J' / 'Smith JA' -> Smith; 'van der Berg K' -> van der Berg; 'Smith, John' -> Smith;
    'Jane Smith' / 'Jeffrey A. Fessler' -> Smith / Fessler; 'Ludwig van Beethoven' -> van Beethoven."""
    author = ET_AL.sub("", author).strip(" ,")
    if "," in author:
        return author.split(",")[0].strip()
    toks = author.split()
    if not toks:
        return ""
    if len(toks) > 1 and all(is_initials(t) for t in toks[1:]):
        return toks[0] if toks[0].lower() not in PARTICLES else " ".join(toks[:-1])
    if len(toks) > 1 and is_initials(toks[-1]):
        return " ".join(t for t in toks if not is_initials(t))
    if len(toks) == 1:
        return toks[0]
    # Given names first: the last token, with any particles before it.
    i = len(toks) - 1
    while i > 1 and toks[i - 1].lower() in PARTICLES:
        i -= 1
    return " ".join(toks[i:])


def _key_prefix(r):
    """'alhajhemidi2025priiner' -> 'alhajhemidi' (the letters before the year)."""
    m = re.match(r"([a-z]+)\d{4}", str(r.get("key") or ""))
    return m.group(1) if m else ""


def _squash(s):
    return re.sub(r"[^a-z]", "", norm_text(s))


def first_surname(r):
    """Family name of the first author. The contract stores `first_author` as the family name only, but agents
    sometimes store the full name: use it as is only when it is a part of the first listed author's name that is
    shorter than the whole name (a family name), otherwise derive the family name. A compound family name written
    after the given name ('Ziad Al-Haj Hemidi') is recovered from the CrossRef family name the reference check
    stored, or from the record key ('alhajhemidi2025…')."""
    fa = (r.get("first_author") or "").strip()
    a = split_authors(r)
    a0 = a[0] if a else ""
    cr = (((r.get("ref_check") or {}).get("crossref") or {}).get("first_author") or "").strip()
    whole_name = cr and a0 and len(a0.split()) > 1 and _squash(cr) == _squash(a0)
    if cr and not whole_name and (not a0 or (_squash(cr) and _squash(cr) in _squash(a0))):
        return cr
    toks = a0.split() if "," not in a0 else []
    prefix = _key_prefix(r)
    if prefix and len(toks) > 2:
        for i in range(1, len(toks) - 1):
            if _squash(" ".join(toks[i:])) == prefix:
                return " ".join(toks[i:])
    if fa and a0:
        if fa.lower() != a0.lower() and fa.lower() in a0.lower():
            return fa
        return surname(a0)
    if fa:
        return fa if (" " not in fa or fa.split()[0].lower() in PARTICLES) else surname(fa)
    return surname(a0) if a0 else "Anon"


def bibtex_name(author, family=None):
    """One author as BibTeX's 'Family, Given' (unambiguous for compound and particle names). `family`, when known
    and part of the name, is used as the family name."""
    author = ET_AL.sub("", author).strip(" ,")
    if not author or "," in author:
        return author
    fam = family if family and family in author else surname(author)
    given = author.replace(fam, "", 1).strip() if fam and fam in author else ""
    return f"{fam}, {given}" if given else fam


ROMAN = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii"}


def _distinct_tokens(nt):
    """Tokens that tell two otherwise similar titles apart: numbers ('2d', '3d', '2023') and Roman numerals."""
    return {t for t in nt.split() if any(c.isdigit() for c in t) or t in ROMAN}


def _author_tokens(r):
    toks = norm_text(r.get("first_author") or "").split()
    if not toks:
        authors = r.get("authors")
        first = authors[0] if isinstance(authors, list) and authors else str(authors or "")
        toks = norm_text(re.split(r"[;,]|\band\b", first)[0]).split()
    return {t for t in toks if len(t) > 1}


def ids_conflict(a, b):
    """True when both records carry an identifier of the same kind (DOI, or arXiv id) and none of them agree."""
    ia, ib = record_ids(a), record_ids(b)
    for kind in ("doi", "arxiv"):
        va = {v for k, v in ia if k == kind}
        vb = {v for k, v in ib if k == kind}
        if va and vb and not va & vb:
            return True
    return False


def same_work_by_title(a, b, threshold, nta=None, ntb=None):
    """Whether two records with near-identical titles are the same work. Similar titles alone are not enough:
    differing DOIs or arXiv ids, a different number or Roman numeral in the title ('2D' / '3D', 'Part I' / 'Part II'),
    and, when no identifier is shared, a different first author or years more than one apart all say no (no year
    limit for a preprint known only by its arXiv id against an article known only by its DOI, same first author)."""
    nta = nta if nta is not None else norm_text(a.get("title"))
    ntb = ntb if ntb is not None else norm_text(b.get("title"))
    if not similar(nta, ntb, threshold):
        return False
    if ids_conflict(a, b) or _distinct_tokens(nta) != _distinct_tokens(ntb):
        return False
    if record_ids(a) & record_ids(b):
        return True
    fa, fb = _author_tokens(a), _author_tokens(b)
    if fa and fb and not fa & fb:
        return False
    # A preprint (arXiv id only) and its journal version (DOI only) can be years apart: no year limit then.
    kinds_a, kinds_b = {k for k, _ in record_ids(a)}, {k for k, _ in record_ids(b)}
    if kinds_a and kinds_b and not kinds_a & kinds_b and fa and fb:
        return True
    ya, yb = to_int(a.get("year")), to_int(b.get("year"))
    return not (ya and yb and abs(ya - yb) > 1)


def title_sim(a, b):
    a, b = norm_text(a), norm_text(b)
    return round(SequenceMatcher(None, a, b).ratio(), 3) if a and b else 0.0


def norm_key(k):
    return re.sub(r"[^a-z0-9]+", "", fold(str(k or "")).lower())


STOPWORDS = {
    "a",
    "an",
    "the",
    "on",
    "of",
    "for",
    "in",
    "to",
    "and",
    "with",
    "via",
    "by",
    "from",
    "at",
    "is",
    "are",
    "towards",
    "toward",
    "using",
    "into",
    "its",
    "do",
    "does",
    "can",
    "how",
    "what",
    "when",
    "why",
}


def make_key(first_author, year, title):
    """lastname + year + first significant title word (CONTRACT section 4)."""
    last = norm_key((str(first_author or "anon").split() or ["anon"])[0]) or "anon"
    words = [w for w in norm_text(title).split() if w not in STOPWORDS]
    return f"{last}{year or ''}{words[0] if words else ''}"


def unique_key(k, taken):
    """k, or k + b, c, ... when k is already taken (CONTRACT section 4). Adds the result to taken."""
    if k not in taken:
        taken.add(k)
        return k
    for i in range(1, 26 * 27):
        suffix = chr(ord("a") + i) if i < 26 else chr(ord("a") + i // 26 - 1) + chr(ord("a") + i % 26)
        cand = k + suffix
        if cand not in taken:
            taken.add(cand)
            return cand
    raise ValueError(f"too many collisions for key {k}")


# --------------------------------------------------------------------------- tiers, families, years


def tier_aliases(review=None):
    aliases = {}
    for k, v in ((review or {}).get("tier_aliases") or {}).items():
        aliases[str(k).strip().lower()] = str(v).strip().lower()
    return aliases


def map_tier(t, review=None):
    """Normalise a tier value: lower case, review.json `tier_aliases` applied. Unknown values pass through."""
    if t is None:
        return None
    s = str(t).strip().lower()
    return tier_aliases(review).get(s, s)


def tier_order(t):
    return TIERS.index(t) if t in TIERS else len(TIERS)


def family_codes(f):
    """'F3,F7' -> ['F3', 'F7']; 'F3 (cascade); F10' -> ['F3', 'F10']. Empty -> ['?']."""
    codes = []
    for part in re.split(r"[,;/]+", str(f or "")):
        part = part.strip()
        if not part:
            continue
        code = re.split(r"[\s(]+", part)[0]
        if code and code not in codes:
            codes.append(code)
    return codes or ["?"]


def family_names(review):
    """review.json `taxonomy` as an ordered {code: name}; accepts {code: name}, {code: {"name": ...}} or
    [{"id": code, "name": ...}]."""
    t = (review or {}).get("taxonomy") or {}
    if isinstance(t, list):
        t = {str(x.get("id")): x.get("name") or x.get("heading") or "" for x in t if isinstance(x, dict)}
    if not isinstance(t, dict):
        return {}
    return {str(k): (v if isinstance(v, str) else (v or {}).get("name", "")) for k, v in t.items()}


def family_sort_key(review):
    """Sort key for family codes: taxonomy order from review.json, then natural order."""
    order = list(family_names(review))

    def key(code):
        return (order.index(code), []) if code in order else (len(order), natural_key(code))

    return key


def load_retiering(rdir):
    """5-final/retiering.json as {key: {"tier": ..., "family": ...}} (dict or list form accepted)."""
    data = load_json(Path(rdir) / RETIERING, {}) or {}
    if isinstance(data, list):
        data = {d.get("key"): d for d in data if isinstance(d, dict) and d.get("key")}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def retiered(r, retier, review=None):
    """(tier, family) of a record after re-tiering."""
    t = retier.get(r.get("key"), {})
    return map_tier(t.get("tier") or r.get("tier"), review), (t.get("family") or r.get("family"))


def year_vor(r):
    rc = r.get("ref_check") or {}
    return rc.get("year_vor") or r.get("year_vor")


def venue_vor(r):
    rc = r.get("ref_check") or {}
    return rc.get("venue_vor") or r.get("venue_vor") or r.get("venue")


def cite_year(r, this_year=None):
    """Year used in citation labels: an explicit `cite_year`, else the version-of-record year unless it lies
    in the future (issue dates), else the record's year."""
    if r.get("cite_year"):
        return r["cite_year"]
    this_year = this_year or datetime.date.today().year
    v = year_vor(r)
    try:
        if v and int(v) <= this_year:
            return int(v)
    except (TypeError, ValueError):
        pass
    return r.get("year")


# --------------------------------------------------------------------------- citation map

CITEMAP_COLUMNS = ["key", "label", "url", "source", "tier", "family", "cite_year", "title"]


def load_citemap(rdir):
    """5-final/citation_map.tsv as {key: row dict}; {} when absent."""
    p = Path(rdir) / CITEMAP
    if not p.exists():
        return {}
    lines = p.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {}
    head = lines[0].split("\t")
    out = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(head, line.split("\t")))
        out[row.get("key")] = row
    return out


def record_url(r):
    doi = clean_doi(r.get("doi")) or clean_doi((r.get("ref_check") or {}).get("proposed_doi"))
    if doi and not is_arxiv_doi(doi):
        return "https://doi.org/" + doi
    a = norm_arxiv(r.get("arxiv_id"))
    if a:
        return "https://arxiv.org/abs/" + a
    return r.get("source_of_record") or ""


# --------------------------------------------------------------------------- HTTP with on-disk cache


class OfflineMiss(Exception):
    """Raised by http_get(offline=True) when the response is not in the cache."""


MIN_INTERVAL = {"export.arxiv.org": 3.1, "arxiv.org": 3.1, "api.crossref.org": 0.25, "doi.org": 0.2}
DEFAULT_INTERVAL = 0.2
_last_request = {}
NOT_FOUND = b"__404__"


def cache_path(cache_dir, url, headers=None):
    """Cache file of a GET request (tests use it to pre-fill the cache)."""
    h = url if not headers else url + "\n" + json.dumps(headers, sort_keys=True)
    return Path(cache_dir) / hashlib.sha1(h.encode("utf-8")).hexdigest()


def _throttle(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    gap = MIN_INTERVAL.get(host, DEFAULT_INTERVAL)
    last = _last_request.get(host)
    if last is not None:
        wait = gap - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_request[host] = time.monotonic()


def http_get(url, cache_dir=None, headers=None, offline=False, retries=4, timeout=30):
    """GET url with a generic User-Agent; cached on disk when cache_dir is given.

    Returns the body (bytes), or None on 404 or repeated failure. With offline=True a cache miss raises
    OfflineMiss and nothing is sent. Requests to one host are spaced (arXiv: one per 3 s).
    """
    path = cache_path(cache_dir, url, headers) if cache_dir else None
    if path is not None and path.exists():
        data = path.read_bytes()
        return None if data == NOT_FOUND else data
    if offline:
        raise OfflineMiss(url)
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    for attempt in range(retries):
        _throttle(url)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=timeout) as resp:
                data = resp.read()
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 410):
                if path is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(NOT_FOUND)
                return None
            time.sleep(2 * (attempt + 1) + (5 if e.code == 429 else 0))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


# --------------------------------------------------------------------------- arXiv Atom parsing

ATOM = "{http://www.w3.org/2005/Atom}"


def parse_arxiv_feed(data):
    """{arxiv_id (no version): {title, year, authors, first_author}} from an arXiv API Atom feed."""
    import xml.etree.ElementTree as ET

    out = {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return out
    for e in root.findall(ATOM + "entry"):
        aid = (e.findtext(ATOM + "id") or "").rsplit("/abs/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid)
        if not aid or "api/errors" in aid:
            continue
        authors = [a.findtext(ATOM + "name") or "" for a in e.findall(ATOM + "author")]
        year = (e.findtext(ATOM + "published") or "")[:4]
        out[aid] = {
            "title": " ".join((e.findtext(ATOM + "title") or "").split()),
            "year": int(year) if year.isdigit() else None,
            "authors": authors,
            "first_author": authors[0].split()[-1] if authors and authors[0].split() else None,
        }
    return out
