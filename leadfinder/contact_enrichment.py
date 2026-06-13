from __future__ import annotations

from .db import list_leads, update_lead
from .enrich import normalize_domain
from .evidence import enrichment_eligible
from .hunter import hunter_domain_to_email, hunter_verification_note
from .scoring import score_lead
from .security import sanitize_error


def enrich_qualified_emails(db, hunter_client, *, limit: int = 5, budget_manager=None) -> dict:
    candidates = [
        lead
        for lead in list_leads(db, status="Qualified")
        if not str(lead.get("email", "") or "").strip()
        and enrichment_eligible(lead, min_score=50)
        and normalize_domain(lead.get("website", ""))
        and "hunter domain search:" not in str(lead.get("notes", "") or "").lower()
    ][: max(0, int(limit))]
    summary = {
        "attempted": 0,
        "emails_found": 0,
        "verified": 0,
        "no_email": 0,
        "errors": 0,
        "budget_stops": [],
    }

    for lead in candidates:
        stop = _check_hunter_budget(budget_manager, 1.0)
        if stop is not None:
            summary["budget_stops"].append(stop)
            break
        summary["attempted"] += 1
        domain = normalize_domain(lead.get("website", ""))
        try:
            search_payload = hunter_client.domain_search(domain)
            _record_hunter_usage(budget_manager, "domain_search", 1.0, domain)
            email_result = hunter_domain_to_email(search_payload)
            email = email_result.get("email", "")
            notes = _append_note(lead.get("notes", ""), email_result.get("notes", ""))
            if not email:
                update_lead(
                    db,
                    lead["id"],
                    {
                        "notes": notes,
                        "email_verification_status": "not_found",
                    },
                )
                summary["no_email"] += 1
                continue

            summary["emails_found"] += 1
            stop = _check_hunter_budget(budget_manager, 1.0)
            if stop is not None:
                summary["budget_stops"].append(stop)
                update_lead(
                    db,
                    lead["id"],
                    {
                        "email": email,
                        "notes": _append_note(notes, stop["message"]),
                        "email_verification_status": "budget_stopped",
                        **score_lead({**lead, "email": email, "notes": _append_note(notes, stop["message"])}),
                    },
                )
                break
            verify_payload = hunter_client.verify_email(email)
            _record_hunter_usage(budget_manager, "verify_email", 1.0, email)
            verification = hunter_verification_note(verify_payload)
            notes = _append_note(notes, verification)
            verification_status = str((verify_payload.get("data") or {}).get("status") or "").lower()
            updates = {
                "notes": notes,
                "email_verification_status": verification_status or "unknown",
            }
            if verification_status == "valid":
                merged = {**lead, "email": email, "notes": notes}
                updates.update({"email": email, **score_lead(merged)})
                summary["verified"] += 1
            update_lead(db, lead["id"], updates)
        except Exception as error:
            update_lead(
                db,
                lead["id"],
                {"notes": _append_note(lead.get("notes", ""), f"Hunter error: {sanitize_error(error)}")},
            )
            summary["errors"] += 1

    return summary


def verify_existing_qualified_emails(db, hunter_client, *, limit: int = 10, budget_manager=None) -> dict:
    candidates = [
        lead
        for lead in list_leads(db, status="Qualified")
        if str(lead.get("email", "") or "").strip()
        and enrichment_eligible(lead, min_score=50)
        and str(lead.get("email_verification_status", "") or "").strip().lower()
        not in {"valid", "invalid", "not_found"}
    ][: max(0, int(limit))]
    summary = {
        "attempted": 0,
        "valid": 0,
        "invalid": 0,
        "other": 0,
        "errors": 0,
        "budget_stops": [],
    }

    for lead in candidates:
        stop = _check_hunter_budget(budget_manager, 1.0)
        if stop is not None:
            summary["budget_stops"].append(stop)
            break
        summary["attempted"] += 1
        try:
            payload = hunter_client.verify_email(lead["email"])
            _record_hunter_usage(budget_manager, "verify_email", 1.0, lead["email"])
            verification_status = str((payload.get("data") or {}).get("status") or "").lower()
            notes = _append_note(lead.get("notes", ""), hunter_verification_note(payload))
            update_lead(
                db,
                lead["id"],
                {
                    "notes": notes,
                    "email_verification_status": verification_status or "unknown",
                },
            )
            if verification_status == "valid":
                summary["valid"] += 1
            elif verification_status == "invalid":
                summary["invalid"] += 1
            else:
                summary["other"] += 1
        except Exception as error:
            update_lead(
                db,
                lead["id"],
                {"notes": _append_note(lead.get("notes", ""), f"Hunter verify error: {sanitize_error(error)}")},
            )
            summary["errors"] += 1
    return summary


def _append_note(existing: str, note: str) -> str:
    return "\n".join(part for part in [str(existing or "").strip(), str(note or "").strip()] if part)


def _check_hunter_budget(budget_manager, cost_units: float) -> dict | None:
    if budget_manager is None:
        return None
    return budget_manager.check("Hunter.io", cost_units)


def _record_hunter_usage(budget_manager, event_type: str, cost_units: float, message: str) -> None:
    if budget_manager is None:
        return
    budget_manager.record(
        "Hunter.io",
        event_type,
        "ok",
        cost_units,
        message,
    )
