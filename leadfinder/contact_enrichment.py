from __future__ import annotations

from .db import claim_provider_task, finish_provider_task, list_leads, update_lead
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
        "deduped_tasks": 0,
        "retry_required_tasks": 0,
        "budget_stops": [],
    }

    for lead in candidates:
        domain = normalize_domain(lead.get("website", ""))
        search_decision = claim_provider_task(
            db,
            provider="Hunter.io",
            task_type="domain_search",
            task_key=_hunter_domain_task_key(lead, domain),
            lead_id=int(lead.get("id") or 0),
            run_log_id=_budget_run_log_id(budget_manager),
            metadata={"domain": domain},
        )
        if not search_decision["should_run"]:
            _record_task_skip(summary, search_decision)
            continue
        stop = _check_hunter_budget(budget_manager, 1.0)
        if stop is not None:
            summary["budget_stops"].append(stop)
            finish_provider_task(
                db,
                int(search_decision["task"]["id"]),
                status="budget_stop",
                message=stop["message"],
                metadata={"domain": domain},
            )
            break
        summary["attempted"] += 1
        try:
            search_payload = hunter_client.domain_search(domain)
            _record_hunter_usage(budget_manager, "domain_search", 1.0, domain)
            email_result = hunter_domain_to_email(search_payload)
            finish_provider_task(
                db,
                int(search_decision["task"]["id"]),
                status="completed",
                cost_units=1.0,
                message=domain,
                metadata={"domain": domain, "email": email_result.get("email", "")},
            )
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
            verify_decision = claim_provider_task(
                db,
                provider="Hunter.io",
                task_type="verify_email",
                task_key=_hunter_verify_task_key(lead, email),
                lead_id=int(lead.get("id") or 0),
                run_log_id=_budget_run_log_id(budget_manager),
                metadata={"email": email},
            )
            if not verify_decision["should_run"]:
                _record_task_skip(summary, verify_decision)
                update_lead(
                    db,
                    lead["id"],
                    {
                        "email": email,
                        "notes": notes,
                        **score_lead({**lead, "email": email, "notes": notes}),
                    },
                )
                continue
            stop = _check_hunter_budget(budget_manager, 1.0)
            if stop is not None:
                summary["budget_stops"].append(stop)
                finish_provider_task(
                    db,
                    int(verify_decision["task"]["id"]),
                    status="budget_stop",
                    message=stop["message"],
                    metadata={"email": email},
                )
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
            try:
                verify_payload = hunter_client.verify_email(email)
                _record_hunter_usage(budget_manager, "verify_email", 1.0, email)
                finish_provider_task(
                    db,
                    int(verify_decision["task"]["id"]),
                    status="completed",
                    cost_units=1.0,
                    message=email,
                    metadata={"email": email},
                )
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
            except Exception as verify_error:
                finish_provider_task(
                    db,
                    int(verify_decision["task"]["id"]),
                    status="error",
                    message=email,
                    error=str(verify_error),
                    metadata={"email": email},
                )
                update_lead(
                    db,
                    lead["id"],
                    {"notes": _append_note(notes, f"Hunter verify error: {sanitize_error(verify_error)}")},
                )
                summary["errors"] += 1
        except Exception as error:
            finish_provider_task(
                db,
                int(search_decision["task"]["id"]),
                status="error",
                message=domain,
                error=str(error),
                metadata={"domain": domain},
            )
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
        "deduped_tasks": 0,
        "retry_required_tasks": 0,
        "budget_stops": [],
    }

    for lead in candidates:
        verify_decision = claim_provider_task(
            db,
            provider="Hunter.io",
            task_type="verify_email",
            task_key=_hunter_verify_task_key(lead, lead["email"]),
            lead_id=int(lead.get("id") or 0),
            run_log_id=_budget_run_log_id(budget_manager),
            metadata={"email": lead["email"]},
        )
        if not verify_decision["should_run"]:
            _record_task_skip(summary, verify_decision)
            continue
        stop = _check_hunter_budget(budget_manager, 1.0)
        if stop is not None:
            summary["budget_stops"].append(stop)
            finish_provider_task(
                db,
                int(verify_decision["task"]["id"]),
                status="budget_stop",
                message=stop["message"],
                metadata={"email": lead["email"]},
            )
            break
        summary["attempted"] += 1
        try:
            payload = hunter_client.verify_email(lead["email"])
            _record_hunter_usage(budget_manager, "verify_email", 1.0, lead["email"])
            finish_provider_task(
                db,
                int(verify_decision["task"]["id"]),
                status="completed",
                cost_units=1.0,
                message=lead["email"],
                metadata={"email": lead["email"]},
            )
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
            finish_provider_task(
                db,
                int(verify_decision["task"]["id"]),
                status="error",
                message=lead["email"],
                error=str(error),
                metadata={"email": lead["email"]},
            )
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


def _hunter_domain_task_key(lead: dict, domain: str) -> str:
    return f"lead:{int(lead.get('id') or 0)}|domain:{str(domain or '').strip().lower()}"


def _hunter_verify_task_key(lead: dict, email: str) -> str:
    return f"lead:{int(lead.get('id') or 0)}|email:{str(email or '').strip().lower()}"


def _record_task_skip(summary: dict, decision: dict) -> None:
    if decision.get("skip_status") == "deduped":
        summary["deduped_tasks"] += 1
    elif decision.get("skip_status") == "retry_required":
        summary["retry_required_tasks"] += 1


def _budget_run_log_id(budget_manager) -> int:
    if budget_manager is None:
        return 0
    return int(getattr(budget_manager, "run_log_id", 0) or 0)
