from __future__ import annotations


BUYER_EVIDENCE_TYPES = {"bill of lading"}
CONTACT_EVIDENCE_TYPES = {"saas contact"}
BUYER_CLASSIFICATIONS = (
    "site classification: downstream_customer",
    "site classification: distributor_or_importer",
)


def quality_report(leads: list[dict], min_score: int = 50) -> dict:
    active_leads = [
        lead
        for lead in leads
        if str(lead.get("status", "") or "").strip().lower() != "rejected"
    ]
    total = len(active_leads)
    high_score = 0
    with_email = 0
    with_website = 0
    with_buyer_evidence = 0
    with_contact_evidence = 0
    high_quality = 0

    for lead in active_leads:
        score = int(lead.get("match_score") or 0)
        source_type = str(lead.get("source_type", "") or "").strip().lower()
        evidence_text = " ".join(
            str(lead.get(field, "") or "")
            for field in ("fit_reason", "notes")
        ).lower()
        has_email = bool(str(lead.get("email", "") or "").strip())
        has_website = bool(str(lead.get("website", "") or "").strip())
        has_buyer_evidence = source_type in BUYER_EVIDENCE_TYPES or any(
            classification in evidence_text for classification in BUYER_CLASSIFICATIONS
        )
        has_contact_evidence = source_type in CONTACT_EVIDENCE_TYPES

        high_score += int(score >= min_score)
        with_email += int(has_email)
        with_website += int(has_website)
        with_buyer_evidence += int(has_buyer_evidence)
        with_contact_evidence += int(has_contact_evidence)
        high_quality += int(score >= min_score and has_website and (has_email or has_buyer_evidence or has_contact_evidence))

    return {
        "total": total,
        "min_score": min_score,
        "high_score": high_score,
        "with_email": with_email,
        "with_website": with_website,
        "with_buyer_evidence": with_buyer_evidence,
        "with_contact_evidence": with_contact_evidence,
        "high_quality": high_quality,
        "high_quality_rate": round(high_quality / total, 3) if total else 0,
    }
