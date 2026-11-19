"""Database layer for CiteVerify using SQLite.
Stores documents, citations, extracted claims, verification results, and human review logs.
All dashboard metrics query real data from this database.
"""
from __future__ import annotations

import json
import sqlite3
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a connection to the SQLite database with row factory."""
    path = db_path or config.DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables with indexes."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        file_hash TEXT,
        file_type TEXT,
        raw_text TEXT,
        text_length INTEGER DEFAULT 0,
        page_count INTEGER DEFAULT 1,
        references_count INTEGER DEFAULT 0,
        claims_count INTEGER DEFAULT 0,
        trust_score REAL,
        trust_grade TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS citations (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        ref_marker TEXT,
        raw_text TEXT,
        title TEXT,
        authors TEXT,
        year INTEGER,
        doi TEXT,
        journal TEXT,
        verified_status TEXT DEFAULT 'UNVERIFIED',
        retracted INTEGER DEFAULT 0,
        match_score REAL DEFAULT 0.0,
        provider TEXT,
        reason TEXT,
        source_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS claims (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        claim_text TEXT NOT NULL,
        topic TEXT,
        numerical_values TEXT, -- JSON array
        citation_marker TEXT,
        ref_id TEXT,
        context TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS verification_results (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        verdict TEXT NOT NULL, -- SUPPORTED, PARTIALLY_SUPPORTED, REFUTED, CONTRADICTORY, NOT_ENOUGH_EVIDENCE
        explanation TEXT,
        evidence_quote TEXT,
        evidence_section TEXT,
        quote_verified INTEGER DEFAULT 0,
        confidence_score REAL DEFAULT 0.0,
        confidence_label TEXT,
        numeric_verdict TEXT, -- NUMERICAL_MATCH, NUMERICAL_MISMATCH, NONE
        numeric_details TEXT, -- JSON
        limitations TEXT,
        source_title TEXT,
        source_authors TEXT,
        source_year INTEGER,
        source_doi TEXT,
        source_url TEXT,
        source_access TEXT,
        needs_review INTEGER DEFAULT 0,
        contradiction_notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS human_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        action TEXT NOT NULL, -- accept, override, comment
        original_verdict TEXT,
        reviewed_verdict TEXT,
        comments TEXT,
        reviewer TEXT DEFAULT 'Lead Reviewer',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_citations_doc ON citations(doc_id);
    CREATE INDEX IF NOT EXISTS idx_claims_doc ON claims(doc_id);
    CREATE INDEX IF NOT EXISTS idx_results_doc ON verification_results(doc_id);
    CREATE INDEX IF NOT EXISTS idx_reviews_doc ON human_reviews(doc_id);
    """)

    conn.commit()
    conn.close()


def save_analysis_run(
    doc_id: str,
    filename: str,
    file_type: str,
    raw_text: str,
    page_count: int,
    citations_list: List[Dict[str, Any]],
    claims_list: List[Dict[str, Any]],
    results_list: List[Dict[str, Any]],
    trust_score_data: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None
) -> None:
    """Save or update an entire document analysis run atomically."""
    # Ensure tables exist
    init_db(db_path)

    conn = get_connection(db_path)
    cur = conn.cursor()

    try:
        cur.execute("BEGIN TRANSACTION;")

        # Delete existing data for this document ID if re-running
        cur.execute("DELETE FROM human_reviews WHERE doc_id = ?", (doc_id,))
        cur.execute("DELETE FROM verification_results WHERE doc_id = ?", (doc_id,))
        cur.execute("DELETE FROM claims WHERE doc_id = ?", (doc_id,))
        cur.execute("DELETE FROM citations WHERE doc_id = ?", (doc_id,))
        cur.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

        t_score = trust_score_data.get("score") if trust_score_data else None
        t_grade = trust_score_data.get("grade") if trust_score_data else None

        # Insert document
        cur.execute("""
            INSERT INTO documents (
                id, filename, file_type, raw_text, text_length, page_count,
                references_count, claims_count, trust_score, trust_grade, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
        """, (
            doc_id, filename, file_type, raw_text, len(raw_text), page_count,
            len(citations_list), len(claims_list), t_score, t_grade
        ))

        # Insert citations
        for cit in citations_list:
            authors_str = ", ".join(cit.get("authors") or []) if isinstance(cit.get("authors"), list) else cit.get("authors")
            cur.execute("""
                INSERT INTO citations (
                    id, doc_id, ref_marker, raw_text, title, authors, year, doi,
                    journal, verified_status, retracted, match_score, provider, reason, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                f"{doc_id}_{cit.get('ref_marker') or cit.get('id')}",
                doc_id,
                cit.get("ref_marker") or str(cit.get("id")),
                cit.get("raw_text") or cit.get("raw", ""),
                cit.get("title", ""),
                authors_str,
                cit.get("year"),
                cit.get("doi", ""),
                cit.get("journal", ""),
                cit.get("verified_status") or cit.get("status", "UNVERIFIED"),
                1 if cit.get("retracted") else 0,
                float(cit.get("match_score", 0.0) or 0.0),
                cit.get("provider", ""),
                cit.get("reason", ""),
                cit.get("source_url") or cit.get("url", "")
            ))

        # Insert claims
        for cl in claims_list:
            nums = json.dumps(cl.get("numerical_values") or [])
            cur.execute("""
                INSERT INTO claims (
                    id, doc_id, claim_id, claim_text, topic, numerical_values,
                    citation_marker, ref_id, context
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                f"{doc_id}_{cl.get('claim_id')}",
                doc_id,
                cl.get("claim_id", ""),
                cl.get("claim") or cl.get("claim_text", ""),
                cl.get("topic", "General Science"),
                nums,
                cl.get("citation") or cl.get("citation_marker", ""),
                cl.get("ref_id", ""),
                cl.get("context", "")
            ))

        # Insert verification results
        for res in results_list:
            src = res.get("source") or {}
            ev = res.get("evidence") or {}
            nc = res.get("numeric_check") or {}
            authors_src = ", ".join(src.get("authors") or []) if isinstance(src.get("authors"), list) else src.get("authors")

            cur.execute("""
                INSERT INTO verification_results (
                    id, doc_id, claim_id, verdict, explanation, evidence_quote,
                    evidence_section, quote_verified, confidence_score, confidence_label,
                    numeric_verdict, numeric_details, limitations, source_title,
                    source_authors, source_year, source_doi, source_url, source_access,
                    needs_review, contradiction_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                f"{doc_id}_{res.get('claim_id')}_res",
                doc_id,
                res.get("claim_id", ""),
                res.get("verdict", "NOT_ENOUGH_EVIDENCE"),
                res.get("explanation", ""),
                ev.get("quote") or ev.get("passage", ""),
                ev.get("section", "Abstract"),
                1 if ev.get("verified") else 0,
                float(res.get("confidence_score") or (res.get("confidence") or {}).get("score", 0.5)),
                (res.get("confidence_label") or (res.get("confidence") or {}).get("label", "Medium")),
                nc.get("verdict", "NONE"),
                json.dumps(nc),
                res.get("limitations", ""),
                src.get("title", ""),
                authors_src,
                src.get("year"),
                src.get("doi", ""),
                src.get("url", ""),
                src.get("access", "metadata"),
                1 if res.get("needs_review") else 0,
                res.get("contradiction_notes", "")
            ))

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def add_human_review(
    doc_id: str,
    claim_id: str,
    action: str,
    original_verdict: str,
    reviewed_verdict: Optional[str] = None,
    comments: str = "",
    reviewer: str = "Lead Reviewer",
    db_path: Optional[str] = None
) -> None:
    """Record a human review action in the audit trail."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO human_reviews (
            doc_id, claim_id, action, original_verdict, reviewed_verdict, comments, reviewer
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (doc_id, claim_id, action, original_verdict, reviewed_verdict, comments, reviewer))
    conn.commit()
    conn.close()


def get_latest_reviews(doc_id: str, db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Get the latest review decision for each claim in a document."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM human_reviews 
        WHERE doc_id = ? 
        ORDER BY created_at ASC;
    """, (doc_id,))
    rows = cur.fetchall()
    conn.close()

    latest: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        latest[r["claim_id"]] = dict(r)
    return latest


def get_all_reviews(doc_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve complete human review audit log for a document."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM human_reviews 
        WHERE doc_id = ? 
        ORDER BY created_at DESC;
    """, (doc_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_document_run(doc_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load a full document analysis record from database."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT * FROM documents WHERE id = ?;", (doc_id,))
    doc_row = cur.fetchone()
    if not doc_row:
        conn.close()
        return None

    doc = dict(doc_row)

    cur.execute("SELECT * FROM citations WHERE doc_id = ? ORDER BY ref_marker ASC;", (doc_id,))
    citations = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM claims WHERE doc_id = ? ORDER BY claim_id ASC;", (doc_id,))
    claims = []
    for r in cur.fetchall():
        d = dict(r)
        d["numerical_values"] = json.loads(d["numerical_values"]) if d.get("numerical_values") else []
        claims.append(d)

    cur.execute("SELECT * FROM verification_results WHERE doc_id = ? ORDER BY claim_id ASC;", (doc_id,))
    results = []
    for r in cur.fetchall():
        d = dict(r)
        d["numeric_details"] = json.loads(d["numeric_details"]) if d.get("numeric_details") else {}
        results.append(d)

    conn.close()

    reviews = get_latest_reviews(doc_id, db_path)

    # Attach human reviews to results for display
    for r in results:
        rv = reviews.get(r["claim_id"])
        if rv:
            r["review_action"] = rv["action"]
            r["final_verdict"] = rv["reviewed_verdict"] if rv["action"] == "override" and rv["reviewed_verdict"] else r["verdict"]
            r["review_comment"] = rv.get("comments", "")
        else:
            r["review_action"] = "AI Verified"
            r["final_verdict"] = r["verdict"]
            r["review_comment"] = "Autonomous AI verification certified."

    return {
        "document": doc,
        "citations": citations,
        "claims": claims,
        "results": results,
        "reviews": reviews
    }


def list_documents(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all analyzed documents with basic statistics."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, filename, file_type, text_length, page_count, references_count,
               claims_count, trust_score, trust_grade, created_at
        FROM documents
        ORDER BY created_at DESC;
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_global_statistics(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Calculate aggregated global statistics from real database tables for the Overview Dashboard."""
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS total_docs FROM documents;")
    total_docs = cur.fetchone()["total_docs"]

    if total_docs == 0:
        conn.close()
        return {
            "total_documents": 0,
            "total_claims": 0,
            "supported_claims": 0,
            "partially_supported_claims": 0,
            "refuted_claims": 0,
            "contradictory_claims": 0,
            "needs_review_claims": 0,
            "invalid_or_mismatched_citations": 0,
            "total_citations": 0,
            "evidence_coverage": 0.0,
            "avg_trust_score": 0.0,
            "verdict_distribution": {k: 0 for k in config.VERDICTS},
            "citation_integrity": {k: 0 for k in config.CITATION_STATUSES},
            "recent_activity": []
        }

    cur.execute("SELECT COUNT(*) AS total_claims FROM claims;")
    total_claims = cur.fetchone()["total_claims"]

    # Count verdicts across all results
    cur.execute("""
        SELECT verdict, COUNT(*) as cnt 
        FROM verification_results 
        GROUP BY verdict;
    """)
    verdict_counts = {k: 0 for k in config.VERDICTS}
    for row in cur.fetchall():
        if row["verdict"] in verdict_counts:
            verdict_counts[row["verdict"]] = row["cnt"]

    # Count citations by verification status
    cur.execute("""
        SELECT verified_status, COUNT(*) as cnt 
        FROM citations 
        GROUP BY verified_status;
    """)
    citation_counts = {k: 0 for k in config.CITATION_STATUSES}
    for row in cur.fetchall():
        if row["verified_status"] in citation_counts:
            citation_counts[row["verified_status"]] = row["cnt"]

    cur.execute("SELECT COUNT(*) AS total_cits FROM citations;")
    total_citations = cur.fetchone()["total_cits"]

    # Invalid or mismatched citations
    cur.execute("""
        SELECT COUNT(*) AS bad_cits FROM citations 
        WHERE verified_status IN ('DOI_NOT_FOUND', 'METADATA_MISMATCH', 'POSSIBLY_RETRACTED');
    """)
    bad_citations = cur.fetchone()["bad_citations"] if "bad_citations" in cur.fetchone().keys() else 0

    # Evidence coverage: percentage of claims where evidence quote was retrieved
    cur.execute("""
        SELECT COUNT(*) AS with_evidence FROM verification_results 
        WHERE evidence_quote IS NOT NULL AND length(trim(evidence_quote)) > 10;
    """)
    with_evidence = cur.fetchone()["with_evidence"]
    coverage = round((with_evidence / max(1, total_claims)) * 100, 1)

    # Average trust score
    cur.execute("SELECT AVG(trust_score) AS avg_score FROM documents WHERE trust_score IS NOT NULL;")
    avg_score_row = cur.fetchone()
    avg_score = round(avg_score_row["avg_score"], 1) if avg_score_row["avg_score"] is not None else 0.0

    # Needs review claims
    cur.execute("SELECT COUNT(*) as nr FROM verification_results WHERE needs_review = 1;")
    needs_review_count = cur.fetchone()["nr"]

    # Recent activity
    cur.execute("""
        SELECT id, filename, claims_count, trust_score, trust_grade, created_at 
        FROM documents 
        ORDER BY created_at DESC 
        LIMIT 6;
    """)
    recent = [dict(r) for r in cur.fetchall()]

    conn.close()

    return {
        "total_documents": total_docs,
        "total_claims": total_claims,
        "supported_claims": verdict_counts.get("SUPPORTED", 0),
        "partially_supported_claims": verdict_counts.get("PARTIALLY_SUPPORTED", 0),
        "refuted_claims": verdict_counts.get("REFUTED", 0),
        "contradictory_claims": verdict_counts.get("CONTRADICTORY", 0),
        "needs_review_claims": needs_review_count,
        "invalid_or_mismatched_citations": (
            citation_counts.get("DOI_NOT_FOUND", 0) +
            citation_counts.get("METADATA_MISMATCH", 0) +
            citation_counts.get("POSSIBLY_RETRACTED", 0)
        ),
        "total_citations": total_citations,
        "evidence_coverage": coverage,
        "avg_trust_score": avg_score,
        "verdict_distribution": verdict_counts,
        "citation_integrity": citation_counts,
        "recent_activity": recent
    }
