
"""Step 4b - LLM judgment, quote verification, confidence scoring, and status mapping."""

import json
import re
from datetime import date

import requests
from src import config


STATUS = {
    "supported": ("Supported", "#465C59"),
    "partially_supported": ("Partially Supported", "#CFA130"),
    "unsupported": ("Unsupported", "#e74c3c"),
    "contradictory": ("Contradictory", "#8e44ad"),
    "needs_review": ("Needs Review", "#7f8c8d"),
    "outdated": ("Possibly Outdated", "#d35400"),
    "missing_citation": ("Missing Citation", "#95a5a6"),
    "bad_reference": ("Bad Reference", "#c0392b"),
    "cannot_verify": ("Cannot Verify", "#bdc3c7"),
}

SEVERITY = {
    "contradictory": 1,
    "unsupported": 2,
    "bad_reference": 3,
    "missing_citation": 4,
    "outdated": 5,
    "partially_supported": 6,
    "needs_review": 7,
    "cannot_verify": 8,
    "supported": 9,
}

VALID_LLM_VERDICTS = {
    "supported",
    "partially_supported",
    "unsupported",
    "contradictory",
    "needs_review",
}


def numeric_check(claim, passages):
    """Check whether numbers in a claim appear in the retrieved evidence."""
    from src.matching import numbers_in

    claim_nums = numbers_in(claim)
    if not claim_nums:
        return None

    text = " ".join(p.get("text", "") for p in passages)

    # Match complete numeric tokens rather than accidental substrings.
    evidence_nums = set(numbers_in(text))

    found = []
    missing = []

    for number in claim_nums:
        if number in evidence_nums:
            found.append(number)
        else:
            missing.append(number)

    return {
        "claim_numbers": claim_nums,
        "matched": found,
        "missing": missing,
    }


def _normalize_quote(text):
    """Normalize punctuation and whitespace for quote comparison."""
    return re.sub(r"[^\w]+", "", str(text).lower())


def verify_quote(quote, passages, passage_id=None):
    """Verify a quote against the selected passage, or all passages if unspecified."""
    if not quote or str(quote).strip().lower() in {"none", "null"}:
        return False, "No quote provided"

    quote_clean = _normalize_quote(quote)

    if len(quote_clean) < 8:
        return False, "Quote too short to verify"

    if passage_id:
        selected = [
            p for p in passages
            if p.get("id") == passage_id
        ]
        if not selected:
            return False, "Selected evidence passage was not found"
        passages_to_check = selected
    else:
        passages_to_check = passages

    for passage in passages_to_check:
        passage_clean = _normalize_quote(passage.get("text", ""))
        if quote_clean in passage_clean:
            return True, "Verified"

    return False, "Not found in selected source passage"


def compute_confidence(
    similarity,
    access,
    num_check,
    llm_certainty,
    quote_ok,
    is_matched,
    max_score=1.0,
    is_llm=True,
):
    """Calculate a confidence score using retrieval and verification signals."""
    base = min(1.0, max(0.0, float(similarity)) * 1.5)

    if access == "full_text":
        base += 0.2
    elif access == "none":
        base -= 0.4

    if num_check and num_check.get("missing"):
        base -= 0.3

    if is_llm:
        try:
            certainty = float(llm_certainty)
        except (TypeError, ValueError):
            certainty = 0.0

        certainty = max(0.0, min(1.0, certainty))
        base = (base + certainty) / 2

    # An unverified quote must reduce confidence substantially.
    if not quote_ok:
        base = min(base, 0.4)

    if not is_matched:
        base = min(base, 0.2)

    score = round(max(0.1, min(float(max_score), base)), 2)

    label = (
        "High" if score >= 0.75
        else "Medium" if score >= 0.45
        else "Low"
    )

    return {
        "score": score,
        "label": label,
        "components": {
            "similarity": round(float(similarity), 2),
            "access": access,
            "quote_verified": bool(quote_ok),
            "llm_certainty": llm_certainty,
        },
    }


def _extract_json(reply):
    """Extract a JSON object from normal or Markdown-fenced LLM output."""
    if isinstance(reply, list):
        # Some OpenAI-compatible APIs return content as text parts.
        reply = " ".join(
            part.get("text", "")
            for part in reply
            if isinstance(part, dict)
        )

    if not isinstance(reply, str):
        raise ValueError("LLM returned an empty or unsupported response")

    reply = reply.strip()

    # Remove Markdown fences if present.
    reply = re.sub(r"^```(?:json)?\s*", "", reply, flags=re.IGNORECASE)
    reply = re.sub(r"\s*```$", "", reply)

    # First try parsing the complete response.
    try:
        parsed = json.loads(reply)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fall back to the first JSON object.
    decoder = json.JSONDecoder()

    for index, character in enumerate(reply):
        if character == "{":
            try:
                parsed, _ = decoder.raw_decode(reply[index:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    raise ValueError("Could not find valid JSON in LLM response")


def llm_judge(claim_text, source_meta, passages):
    """Ask Gemini to judge a claim against explicitly identified evidence passages."""
    title = source_meta.get("title", "Unknown Title")
    year = source_meta.get("year", "Unknown Year")

    # Gemini must receive the IDs along with the passage text.
    structured_passages = [
        {
            "id": passage.get("id", f"P{index}"),
            "section": passage.get("section", "Unknown section"),
            "text": passage.get("text", ""),
        }
        for index, passage in enumerate(passages, start=1)
    ]

    passages_json = json.dumps(structured_passages, ensure_ascii=False)

    prompt = (
        "You are an expert scientific peer reviewer.\n"
        "Evaluate whether the cited SOURCE supports the CLAIM.\n\n"
        "Rules:\n"
        "1. Judge the meaning, not just matching keywords.\n"
        "2. Check numbers, percentages, units, and direction of effect.\n"
        "3. Distinguish increases from decreases and correlation from causation.\n"
        "4. Use only the supplied source passages as evidence.\n"
        "5. Do not invent evidence or quotes.\n"
        "6. If only part of the claim is supported, use partially_supported.\n"
        "7. If the evidence contradicts the claim, use contradictory.\n"
        "8. If evidence is insufficient, use needs_review.\n"
        "9. Select the passage that most directly supports your judgment.\n"
        "10. The evidence_quote must be copied exactly from that passage.\n\n"
        f"CLAIM:\n{claim_text}\n\n"
        f"SOURCE METADATA:\n{title} ({year})\n\n"
        f"SOURCE PASSAGES:\n{passages_json}\n\n"
        "Return one JSON object and no additional explanation:\n"
        "{\n"
        '  "verdict": "supported",\n'
        '  "explanation": "Short evidence-based explanation.",\n'
        '  "evidence_passage_id": "P1",\n'
        '  "evidence_quote": "Exact words copied from the selected passage.",\n'
        '  "certainty": 0.9\n'
        "}\n"
        "Allowed verdicts: supported, partially_supported, unsupported, "
        "contradictory, needs_review."
    )

    try:
        response = requests.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.LLM_MODEL,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.0,
            },
            timeout=45,
        )

        response.raise_for_status()

        reply = response.json()["choices"][0]["message"]["content"]
        answer = _extract_json(reply)

        verdict = str(answer.get("verdict", "needs_review")).strip().lower()

        if verdict not in VALID_LLM_VERDICTS:
            verdict = "needs_review"

        try:
            certainty = float(answer.get("certainty", 0.0))
        except (TypeError, ValueError):
            certainty = 0.0

        certainty = max(0.0, min(1.0, certainty))

        passage_id = answer.get("evidence_passage_id")
        if passage_id is not None:
            passage_id = str(passage_id).strip()

        return {
            "verdict": verdict,
            "explanation": str(answer.get("explanation", "")).strip(),
            "evidence_passage_id": passage_id,
            "evidence_quote": answer.get("evidence_quote"),
            "certainty": certainty,
            "llm_error": None,
        }

    except Exception as error:
        return {
            "verdict": "needs_review",
            "explanation": "Gemini verification could not be completed.",
            "evidence_passage_id": None,
            "evidence_quote": None,
            "certainty": 0.0,
            "llm_error": str(error),
        }


def _base_result(claim, citation, status, explanation, source, flags, needs_review, confidence):
    """Keep the output structure consistent across every verification path."""
    return {
        "claim_id": claim["id"],
        "claim": claim["text"],
        "citation": citation,
        "status": status,
        "explanation": explanation,
        "evidence": None,
        "flags": flags,
        "source": source,
        "needs_review": needs_review,
        "confidence": confidence,
    }


def verify_claim(claim, ref, source, use_llm):
    """Verify one claim against its cited source."""

    # 1. Uncited claims cannot be evidence-verified without a source.
    if claim["kind"] == "uncited":
        confidence = compute_confidence(
            0, "none", None, 0, False, False, 0.2, False
        )

        result = _base_result(
            claim,
            None,
            "missing_citation",
            "No citation was provided. The claim cannot be evidence-verified.",
            None,
            ["no_citation"],
            True,
            confidence,
        )
        return result

    citation = ", ".join(
        item["raw"] for item in claim.get("citations", [])
    )

    # 2. Reference could not be retrieved.
    if not source or not source.get("found"):
        confidence = compute_confidence(
            0, "none", None, 0, False, False, 0.2, False
        )

        return _base_result(
            claim,
            citation,
            "bad_reference",
            "The cited reference could not be retrieved or identified.",
            source,
            ["reference_not_found"],
            True,
            confidence,
        )

    from src.matching import build_passages, rank_passages

    passages = rank_passages(
        claim["clean_text"],
        build_passages(source),
    )

    numeric_result = numeric_check(claim["clean_text"], passages)
    flags = []

    # 3. Retraction warning.
    if source.get("retracted"):
        flags.append("retracted_source")

    # 4. Numeric discrepancy warning.
    if numeric_result and numeric_result["missing"]:
        flags.append("numeric_mismatch")

    # 5. Old-source warning.
    if source.get("year"):
        try:
            age = date.today().year - int(source["year"])
            if age > getattr(config, "OUTDATED_YEARS", 10):
                flags.append("old_source")
        except (ValueError, TypeError):
            pass

    # 6. No readable evidence.
    if not passages:
        confidence = compute_confidence(
            0,
            source.get("access", "none"),
            numeric_result,
            0,
            False,
            False,
            0.4,
            False,
        )

        result = _base_result(
            claim,
            citation,
            "cannot_verify",
            "The reference was found, but no readable evidence passages were available.",
            source,
            flags + ["no_readable_evidence"],
            True,
            confidence,
        )
        result["numeric_check"] = numeric_result
        return result

    # 7. Gemini verification.
    if use_llm and config.llm_available():
        answer = llm_judge(
            claim["clean_text"],
            source,
            passages,
        )

        selected_id = answer.get("evidence_passage_id")

        selected_passage = next(
            (
                passage for passage in passages
                if passage.get("id") == selected_id
            ),
            None,
        )

        # If Gemini selected an invalid ID, do not pretend its evidence
        # selection was valid.
        if selected_passage is None:
            flags.append("invalid_evidence_selection")

        quote_ok, quote_message = verify_quote(
            answer.get("evidence_quote"),
            passages,
            selected_id if selected_passage else None,
        )

        status = answer["verdict"]

        # Retraction is a source-integrity warning. Do not silently treat
        # it as proof that the scientific statement itself is false.
        if "retracted_source" in flags and status == "supported":
            status = "needs_review"
            explanation = (
                "Gemini found supporting evidence, but the cited paper "
                "is marked as retracted. Its findings should not be treated "
                "as reliable without independent confirmation."
            )
        else:
            explanation = answer.get("explanation", "")

        # A numeric mismatch is a warning for Gemini's assessment,
        # not an automatic proof that the claim is false.
        if "numeric_mismatch" in flags:
            explanation = (
                explanation
                + " A numeric discrepancy was also detected and should be checked."
            ).strip()

        if answer.get("llm_error"):
            flags.append("llm_error")

        if selected_passage:
            evidence_text = selected_passage["text"]
            evidence_section = selected_passage.get("section")
        else:
            evidence_text = None
            evidence_section = None

        similarity = (
            selected_passage.get("score", 0)
            if selected_passage
            else 0
        )

        confidence = compute_confidence(
            similarity,
            source.get("access", "none"),
            numeric_result,
            answer.get("certainty", 0.0),
            quote_ok,
            selected_passage is not None,
        )

        # This is an attention/audit flag, not a requirement to obtain
        # human approval before the automated result can be produced.
        needs_attention = (
            status in {"needs_review", "cannot_verify"}
            or confidence["score"] < 0.4
            or answer.get("llm_error") is not None
            or selected_passage is None
        )

        result = _base_result(
            claim,
            citation,
            status,
            explanation or quote_message,
            source,
            flags,
            needs_attention,
            confidence,
        )

        result["evidence"] = {
            "passage": evidence_text,
            "quote": answer.get("evidence_quote"),
            "verified": quote_ok,
            "section": evidence_section,
        }
        result["numeric_check"] = numeric_result
        result["llm_error"] = answer.get("llm_error")

        return result

    # 8. Offline rule-based mode.
    best_passage = passages[0]

    # This is only a lexical match, not an AI scientific judgment.
    quote_ok = bool(best_passage.get("text"))

    confidence = compute_confidence(
        best_passage.get("score", 0),
        source.get("access", "none"),
        numeric_result,
        0.5,
        quote_ok,
        True,
        0.5,
        False,
    )

    if "retracted_source" in flags or "numeric_mismatch" in flags:
        status = "unsupported"
        explanation = (
            "Offline checks detected a retracted source or numeric discrepancy. "
            "This is a warning, not a full semantic verification."
        )
    elif best_passage.get("score", 0) > 0.3:
        status = "supported"
        explanation = (
            "A relevant passage was found using offline text matching. "
            "This is not equivalent to Gemini semantic verification."
        )
    else:
        status = "needs_review"
        explanation = "Offline matching did not find sufficiently relevant evidence."

    needs_attention = status != "supported" or confidence["score"] < 0.4

    result = _base_result(
        claim,
        citation,
        status,
        explanation,
        source,
        flags,
        needs_attention,
        confidence,
    )

    result["evidence"] = {
        "passage": best_passage["text"],
        "quote": None,
        "verified": quote_ok,
        "section": best_passage.get("section"),
    }
    result["numeric_check"] = numeric_result

    return result
