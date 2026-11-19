"""Step 4a - find the passages of the source paper that best match a claim."""
import re

from . import config


def _sentences(text):
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])", text) if len(s.strip()) > 20]


def build_passages(source: dict, window: int = 2):
    """Turn a resolved source into overlapping passages with section/page labels."""
    passages = []

    def add(sents, section, page=None):
        for i in range(0, max(1, len(sents) - window + 1)):
            chunk = " ".join(sents[i : i + window])
            if chunk:
                passages.append({"text": chunk, "section": section, "page": page})

    if source.get("abstract"):
        add(_sentences(source["abstract"]), "Abstract")
    for page_no, text in source.get("pages", []):
        add(_sentences(text), f"Full text, page {page_no}", page_no)
    for i, p in enumerate(passages, 1):
        p["id"] = f"P{i}"
    return passages


def numbers_in(text: str):
    t = re.sub(r"per\s?cent", "%", text, flags=re.I)
    vals = []
    for m in re.finditer(r"(?<![\w.])(\d[\d,]*\.?\d*)\s*%?", t):
        raw = m.group(1).replace(",", "").rstrip(".")
        try:
            v = float(raw)
        except ValueError:
            continue
        if 1900 <= v <= 2100 and "." not in raw:  # looks like a year
            continue
        vals.append(v)
    return vals


_embedder = None


def _embed_scores(claim, texts):
    global _embedder
    try:
        from sentence_transformers import SentenceTransformer, util

        if _embedder is None:
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        c = _embedder.encode(claim, convert_to_tensor=True)
        p = _embedder.encode(texts, convert_to_tensor=True)
        return util.cos_sim(c, p)[0].tolist()
    except Exception:
        return None


def rank_passages(claim: str, passages: list, k: int = 5):
    """Rank passages by TF-IDF cosine (+ optional embeddings) with a boost for matching numbers."""
    if not passages:
        return []
    texts = [p["text"] for p in passages]
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        mat = vec.fit_transform(texts + [claim])
        scores = cosine_similarity(mat[-1], mat[:-1])[0].tolist()
    except Exception:  # tiny fallback: word overlap
        cw = set(re.findall(r"\w+", claim.lower()))
        scores = [len(cw & set(re.findall(r"\w+", t.lower()))) / (len(cw) or 1) for t in texts]
    if config.USE_EMBEDDINGS:
        emb = _embed_scores(claim, texts)
        if emb:
            scores = [0.5 * a + 0.5 * max(0.0, b) for a, b in zip(scores, emb)]
    claim_nums = set(numbers_in(claim))
    ranked = []
    for p, s in zip(passages, scores):
        boost = 0.15 if claim_nums & set(numbers_in(p["text"])) else 0.0
        ranked.append({**p, "score": round(min(1.0, s + boost), 4), "raw_similarity": round(s, 4)})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:k]
