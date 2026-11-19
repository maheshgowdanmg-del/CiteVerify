"""Steps 2 - find claims, detect citations ([1], (Author, Year)), parse the reference list, map them."""
import re

# ---------- citation patterns ----------
NUM_CITE = re.compile(r"\[(\d+(?:\s*[-\u2013,;]\s*\d+)*)\]")
AUTH_PAREN = re.compile(r"\(([^()]*?(?:19|20)\d{2}[a-z]?[^()]*?)\)")
AUTH_PART = re.compile(
    r"^\s*(?:e\.g\.,?\s*|see\s+|cf\.\s*)?([A-Z][A-Za-z'\u2019\-]+)(?:\s+(?:and|&)\s+[A-Z][A-Za-z'\u2019\-]+|\s+et al\.?)?,?\s+((?:19|20)\d{2})[a-z]?"
)
CLAIM_CUES = re.compile(
    r"\d+(?:\.\d+)?\s*%|\bpercent\b|\b(?:study|studies|research|trial|experiment|survey|evidence)\b|"
    r"\b(?:found|shown|show|shows|demonstrate[sd]?|prove[sd]?|reveal(?:s|ed)?|reported|concluded)\b|"
    r"\b(?:significantly|increase[sd]?|reduce[sd]?|improve[sd]?|cause[sd]?|lead(?:s)? to|linked to|outperform\w*)\b",
    re.I,
)

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
ARXIV_RE = re.compile(r"arxiv[:./\s]*(?:abs/)?(\d{4}\.\d{4,5})", re.I)
YEAR_PAREN = re.compile(r"\(((?:19|20)\d{2})[a-z]?\)")
YEAR_ANY = re.compile(r"\b((?:19|20)\d{2})[a-z]?\b")
NUMBERED_ENTRY = re.compile(r"^\[?(\d{1,3})[\].)]\s+")
AUTHOR_START = re.compile(r"^[A-Z][A-Za-z'\u2019\-]+,\s+(?:[A-Z]\.|[A-Z][a-z]+)")


def _drop_headings(text: str) -> str:
    """Remove short heading-like lines (titles, '1. Introduction') so they don't glue onto sentences."""
    kept, prev_end = [], True
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            prev_end = True
            continue
        is_heading = (
            prev_end and len(line.split()) <= 14 and not re.search(r"[.!?][\"'\u201d\])]*$", line)
            and not NUM_CITE.search(line) and not AUTH_PAREN.search(line)
        )
        if is_heading:
            continue
        kept.append(line)
        prev_end = bool(re.search(r"[.!?][\"'\u201d\])]*$", line))
    return " ".join(kept)


def split_sentences(text: str):
    text = re.sub(r"\s+", " ", _drop_headings(text))
    text = re.sub(r"\b(et al|e\.g|i\.e|Fig|vs|approx)\.", lambda m: m.group(0).replace(".", "<DOT>"), text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\[(\"\u201c])", text)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


def _expand_numeric(group: str):
    nums = []
    for chunk in re.split(r"[,;]", group):
        chunk = chunk.strip()
        m = re.match(r"(\d+)\s*[-\u2013]\s*(\d+)$", chunk)
        if m and int(m.group(2)) - int(m.group(1)) < 30:
            nums.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif chunk.isdigit():
            nums.append(int(chunk))
    return nums


def find_citations(sentence: str):
    """Return a list of citation dicts found in a sentence."""
    found = []
    for m in NUM_CITE.finditer(sentence):
        found.append({"raw": m.group(0), "type": "numeric", "ids": _expand_numeric(m.group(1))})
    for m in AUTH_PAREN.finditer(sentence):
        for part in m.group(1).split(";"):
            pm = AUTH_PART.match(part)
            if pm:
                found.append(
                    {"raw": part.strip(), "type": "author_year", "surname": pm.group(1), "year": int(pm.group(2))}
                )
    return found


def strip_citations(sentence: str) -> str:
    s = NUM_CITE.sub("", sentence)
    s = AUTH_PAREN.sub(lambda m: "" if find_citations(m.group(0)) else m.group(0), s)
    return re.sub(r"\s+([.,;])", r"\1", re.sub(r"\s+", " ", s)).strip()


# ---------- reference list ----------
def _split_entries(ref_text: str):
    lines = [l.strip() for l in ref_text.splitlines() if l.strip()]
    numbered = [l for l in lines if NUMBERED_ENTRY.match(l)]
    entries = []
    if len(numbered) >= 2:
        for line in lines:
            m = NUMBERED_ENTRY.match(line)
            if m:
                entries.append({"id": int(m.group(1)), "raw": line[m.end():]})
            elif entries:
                entries[-1]["raw"] += " " + line
    else:
        for line in lines:
            if AUTHOR_START.match(line) and (not entries or re.search(r"[.)\d]$", entries[-1]["raw"])):
                entries.append({"id": len(entries) + 1, "raw": line})
            elif entries:
                entries[-1]["raw"] += " " + line
            else:
                entries.append({"id": 1, "raw": line})
    return entries


def _guess_title(raw: str) -> str:
    q = re.search(r"[\"\u201c](.+?)[,.]?[\"\u201d]", raw)
    if q:
        return q.group(1).strip()
    m = re.search(r"\((?:19|20)\d{2}[a-z]?\)\.?\s*(.+?)(?:\.\s|\?\s|$)", raw)  # APA style
    if m:
        return m.group(1).strip()
    segs = [s.strip() for s in re.split(r"\.\s+", raw) if len(s.split()) >= 4]
    for s in segs:
        if not AUTHOR_START.match(s):
            return s
    return segs[0] if segs else ""


def parse_references(ref_text: str):
    refs = []
    for e in _split_entries(ref_text):
        raw = re.sub(r"\s+", " ", e["raw"]).strip()
        doi = DOI_RE.search(raw)
        arx = ARXIV_RE.search(raw)
        year = YEAR_PAREN.search(raw) or YEAR_ANY.search(raw)
        first = re.match(r"([A-Z][A-Za-z'\u2019\-]+)", raw)
        refs.append(
            {
                "id": e["id"],
                "raw": raw,
                "title": _guess_title(raw),
                "year": int(year.group(1)) if year else None,
                "doi": doi.group(0).rstrip(".,;)") if doi else None,
                "arxiv": arx.group(1) if arx else None,
                "first_author": first.group(1) if first else "",
            }
        )
    return refs


def map_citation(cite: dict, refs: list):
    """Return (matched_refs, unmatched_flag)."""
    matched = []
    if cite["type"] == "numeric":
        by_id = {r["id"]: r for r in refs}
        matched = [by_id[i] for i in cite["ids"] if i in by_id]
    else:
        sur = cite["surname"].lower()
        matched = [r for r in refs if r["first_author"].lower() == sur and r["year"] == cite["year"]]
        if not matched:
            matched = [r for r in refs if r["first_author"].lower() == sur]
    return matched


# ---------- claims ----------
def extract_claims(body: str, refs: list, max_claims: int = 60):
    claims = []
    for sent in split_sentences(body):
        if len(sent) < 25 or len(sent.split()) < 5:
            continue
        cites = find_citations(sent)
        if not cites and not (CLAIM_CUES.search(sent) and len(sent) > 40):
            continue
        ref_ids, missing = [], []
        for c in cites:
            matched = map_citation(c, refs)
            if matched:
                ref_ids.extend(r["id"] for r in matched)
            else:
                missing.append(c["raw"])
        claims.append(
            {
                "id": f"C{len(claims) + 1}",
                "text": sent,
                "clean_text": strip_citations(sent),
                "citations": cites,
                "ref_ids": sorted(set(ref_ids)),
                "unmatched_citations": missing,
                "kind": "cited" if cites else "uncited",
            }
        )
        if len(claims) >= max_claims:
            break
    return claims
