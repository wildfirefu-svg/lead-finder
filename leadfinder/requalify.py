from __future__ import annotations

from dataclasses import dataclass

from .classifier import classification_note, classify_company_site
from .db import list_leads, update_lead
from .enrich import clean_company_name, enrich_site, normalize_domain
from .evidence import review_status_for_lead
from .market_fit import market_fit_note, validate_target_market
from .scoring import score_lead
from .serper import is_excluded_discovery_domain, is_excluded_discovery_url


@dataclass(frozen=True)
class RequalifyOptions:
    limit: int = 100
    min_score: int = 50
    only_unreviewed: bool = True
    timeout_seconds: float = 6.0


def requalify_leads(
    db,
    options: RequalifyOptions,
    *,
    site_enricher=enrich_site,
) -> dict:
    candidates = [
        lead
        for lead in list_leads(db)
        if _is_candidate(lead, options.only_unreviewed)
    ][: max(0, int(options.limit))]
    summary = {
        "reviewed": 0,
        "qualified": 0,
        "rejected": 0,
        "needs_review": 0,
        "errors": 0,
    }

    for lead in candidates:
        summary["reviewed"] += 1
        website = str(lead.get("website", "") or "")
        if (
            is_excluded_discovery_domain(normalize_domain(website))
            or is_excluded_discovery_url(website)
        ):
            updates = {
                "status": "Rejected",
                "classification_status": "directory",
                "classification_evidence": "excluded discovery source",
                "score_evidence": lead.get("score_evidence", ""),
                "fit_reason": _replace_review_notes(
                    lead.get("fit_reason", ""),
                    "Site classification: noise confidence=95 passed=False "
                    "reason=excluded discovery source",
                ),
                "notes": _append_note(
                    lead.get("notes", ""),
                    "Batch review: excluded directory, marketplace, social, report, or document source",
                ),
            }
            updates["review_status"] = review_status_for_lead(
                {**lead, **updates},
                min_score=options.min_score,
            )
            update_lead(
                db,
                lead["id"],
                updates,
            )
            summary["rejected"] += 1
            continue
        try:
            enriched = site_enricher(
                lead["website"],
                defaults=lead,
                max_pages=2,
                timeout=min(float(options.timeout_seconds), 6.0),
            )
        except Exception as error:
            outcome = _review_existing_evidence(db, lead, options, f"website crawl failed: {error}")
            summary[outcome] += 1
            continue

        merged = {**lead, **enriched}
        if not str(merged.get("raw_text", "") or "").strip():
            outcome = _review_existing_evidence(
                db,
                lead,
                options,
                "website crawl returned no readable content",
            )
            summary[outcome] += 1
            continue

        scored = {**merged, **score_lead(merged)}
        classification = classify_company_site(scored)

        if int(scored.get("match_score") or 0) < int(options.min_score):
            _save_review(
                db,
                scored,
                status="Rejected",
                reason=f"Batch review: score<{options.min_score}",
                classification=classification,
                min_score=options.min_score,
            )
            summary["rejected"] += 1
            continue

        if not classification["passed"]:
            status = "Rejected" if classification["category"] in {"supplier", "noise"} else "Discovered"
            _save_review(
                db,
                scored,
                status=status,
                reason=f"Batch review: {classification['reason']}",
                classification=classification,
                min_score=options.min_score,
            )
            summary["rejected" if status == "Rejected" else "needs_review"] += 1
            continue

        market_fit = validate_target_market(scored, scored.get("country_region", ""))
        market_text = market_fit_note(market_fit)
        status = "Qualified" if market_fit["passed"] else "Rejected"
        _save_review(
            db,
            scored,
            status=status,
            reason=f"Batch review: {market_fit['reason']}",
            classification=classification,
            min_score=options.min_score,
            market_text=market_text,
        )
        summary["qualified" if status == "Qualified" else "rejected"] += 1

    return summary


def _is_candidate(lead: dict, only_unreviewed: bool) -> bool:
    if str(lead.get("status", "") or "").strip().lower() == "rejected":
        return False
    if str(lead.get("source_type", "") or "").strip().lower() != "website":
        return False
    if not str(lead.get("website", "") or "").strip():
        return False
    if not only_unreviewed:
        return True
    evidence = " ".join(
        str(lead.get(field, "") or "")
        for field in ("fit_reason", "notes")
    ).lower()
    has_classification = "site classification:" in evidence
    has_terminal_rejection = (
        "site classification: supplier" in evidence
        or "site classification: noise" in evidence
    )
    return not (
        has_classification
        and ("market fit:" in evidence or has_terminal_rejection)
    )


def _save_review(
    db,
    lead: dict,
    *,
    status: str,
    reason: str,
    classification: dict,
    min_score: int,
    market_text: str = "",
) -> None:
    classification_text = classification_note(classification)
    fit_reason = _replace_review_notes(
        lead.get("fit_reason", ""),
        classification_text,
        market_text,
    )
    note_parts = [
        str(lead.get("notes", "") or "").strip(),
        reason,
    ]
    updates = {
        "company_name": lead.get("company_name", ""),
        "email": lead.get("email", ""),
        "industry": lead.get("industry", ""),
        "product_fit": lead.get("product_fit", "Both"),
        "fit_reason": fit_reason,
        "match_score": lead.get("match_score", 0),
        "status": status,
        "crawl_status": lead.get("crawl_status", ""),
        "classification_status": classification["label"],
        "classification_evidence": classification["explanation"],
        "score_evidence": lead.get("score_evidence", ""),
        "market_fit_status": _market_fit_status(market_text),
        "email_verification_status": _email_verification_status(lead),
        "notes": "\n".join(part for part in note_parts if part),
        "raw_text": lead.get("raw_text", ""),
    }
    updates["review_status"] = review_status_for_lead(
        {**lead, **updates},
        min_score=min_score,
    )
    update_lead(db, lead["id"], updates)


def _mark_error(db, lead: dict, message: str, classification: dict) -> None:
    notes = str(lead.get("notes", "") or "").strip()
    update_lead(
        db,
        lead["id"],
        {
            "status": "Error",
            "crawl_status": "error",
            "classification_status": classification["label"],
            "classification_evidence": classification["explanation"],
            "score_evidence": lead.get("score_evidence", ""),
            "review_status": "crawl_failed",
            "notes": "\n".join(part for part in [notes, f"Batch review error: {message}"] if part),
        },
    )


def _review_existing_evidence(
    db,
    lead: dict,
    options: RequalifyOptions,
    crawl_message: str,
) -> str:
    fallback_lead = {
        **lead,
        "company_name": clean_company_name(
            lead.get("company_name", ""),
            [],
            [],
            lead.get("website", ""),
        ),
        "crawl_status": "error",
    }
    scored = {**fallback_lead, **score_lead(fallback_lead)}
    classification = classify_company_site(scored)

    if classification["category"] in {"supplier", "noise"}:
        _save_review(
            db,
            scored,
            status="Rejected",
            reason=f"Batch review fallback: {crawl_message}",
            classification=classification,
            min_score=options.min_score,
        )
        return "rejected"

    if classification["passed"] and int(scored.get("match_score") or 0) >= int(options.min_score):
        market_fit = validate_target_market(scored, scored.get("country_region", ""))
        status = "Qualified" if market_fit["passed"] else "Rejected"
        _save_review(
            db,
            scored,
            status=status,
            reason=f"Batch review fallback: {crawl_message}",
            classification=classification,
            min_score=options.min_score,
            market_text=market_fit_note(market_fit),
        )
        return "qualified" if status == "Qualified" else "rejected"

    _mark_error(db, scored, crawl_message, classification)
    return "errors"


def _replace_review_notes(existing: str, *notes: str) -> str:
    base = str(existing or "").split("\nSite classification:", 1)[0].strip()
    return "\n".join(part for part in [base, *notes] if part)


def _append_note(existing: str, note: str) -> str:
    return "\n".join(part for part in [str(existing or "").strip(), note.strip()] if part)


def _market_fit_status(note: str) -> str:
    text = str(note or "")
    if "passed=True" in text:
        return "passed"
    if "passed=False" in text:
        return "failed"
    return ""


def _email_verification_status(lead: dict) -> str:
    current = str(lead.get("email_verification_status") or "").strip().lower()
    if current:
        return current
    notes = str(lead.get("notes") or "").lower()
    marker = "hunter verification:"
    if marker not in notes:
        return ""
    return notes.split(marker, 1)[1].strip().split(" ", 1)[0]
