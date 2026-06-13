from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .db import list_leads, update_lead
from .enrich import normalize_domain
from .exporter import CRM_FIELDS
from .security import sanitize_error
from .stability import call_with_limited_retry

OUTCOME_LABELS = (
    "valid_customer",
    "not_buyer",
    "wrong_market",
    "duplicate",
    "no_response",
    "do_not_contact",
)


def crm_status(base_url: str, timeout: float = 3.0) -> dict:
    payload = _request_json(base_url, "/api/system/status", timeout=timeout)
    return {"available": True, "status": payload.get("status", {})}


def sync_verified_qualified(
    db,
    base_url: str,
    *,
    limit: int = 50,
    timeout: float = 8.0,
) -> dict:
    candidates = [
        lead
        for lead in list_leads(db, status="Qualified")
        if str(lead.get("email") or "").strip()
        and _is_verified(lead)
        and str(lead.get("crm_sync_status") or "").lower() not in {"synced", "duplicate"}
    ][: max(0, int(limit))]
    summary = {
        "attempted": 0,
        "synced": 0,
        "duplicates": 0,
        "errors": 0,
        "skipped_unverified": sum(
            1
            for lead in list_leads(db, status="Qualified")
            if str(lead.get("email") or "").strip() and not _is_verified(lead)
        ),
    }

    for lead in candidates:
        summary["attempted"] += 1
        try:
            imported = _request_json(
                base_url,
                "/api/sourced-leads/import-csv",
                method="POST",
                payload={
                    "source_type": "Website",
                    "source_name": "Lead Finder",
                    "market_region": lead.get("market_region", ""),
                    "csv_text": _lead_csv(lead),
                },
                timeout=timeout,
            )
            sourced = next(iter(imported.get("created") or imported.get("skipped") or []), None)
            if not sourced:
                raise RuntimeError("CRM did not return an imported source row")
            result = _request_json(
                base_url,
                f"/api/sourced-leads/{int(sourced['id'])}/import",
                method="POST",
                payload={},
                timeout=timeout,
            )
            duplicate = bool(result.get("duplicate"))
            status = "duplicate" if duplicate else "synced"
            update_lead(db, lead["id"], {"crm_sync_status": status})
            summary["duplicates" if duplicate else "synced"] += 1
        except Exception as error:
            update_lead(
                db,
                lead["id"],
                {
                    "crm_sync_status": "error",
                    "notes": _append_note(
                        lead.get("notes", ""),
                        f"CRM sync error: {sanitize_error(error)}",
                    ),
                },
            )
            summary["errors"] += 1
    return summary


def pull_crm_feedback(
    db,
    base_url: str,
    *,
    limit: int | None = None,
    timeout: float = 8.0,
) -> dict:
    payload = _request_json(base_url, "/api/leads", timeout=timeout)
    remote_leads = payload.get("leads") if isinstance(payload, dict) else []
    if not isinstance(remote_leads, list):
        remote_leads = []
    matched = 0
    updated = 0
    unmatched = 0
    errors = 0
    outcome_counts = {label: 0 for label in OUTCOME_LABELS}
    remote_index = _build_remote_index(remote_leads)
    local_rows = list_leads(db, limit=None)
    if limit is not None:
        local_rows = local_rows[: max(0, int(limit))]

    for lead in local_rows:
        remote = _match_remote_lead(lead, remote_index)
        if remote is None:
            unmatched += 1
            continue
        matched += 1
        try:
            outcome = infer_crm_outcome(remote, lead)
            updates = {
                "crm_followup_status": str(remote.get("status") or "").strip(),
                "crm_last_contact_at": str(remote.get("last_contacted_at") or "").strip(),
                "crm_outcome": outcome,
            }
            current = {
                "crm_followup_status": str(lead.get("crm_followup_status") or "").strip(),
                "crm_last_contact_at": str(lead.get("crm_last_contact_at") or "").strip(),
                "crm_outcome": str(lead.get("crm_outcome") or "").strip(),
            }
            if updates != current:
                update_lead(db, lead["id"], updates)
                updated += 1
            if outcome in outcome_counts:
                outcome_counts[outcome] += 1
        except Exception:
            errors += 1
    return {
        "matched": matched,
        "updated": updated,
        "unmatched": unmatched,
        "errors": errors,
        "outcomes": outcome_counts,
    }


def infer_crm_outcome(remote_lead: dict, local_lead: dict | None = None) -> str:
    notes = str(remote_lead.get("notes") or "").strip().lower()
    status = str(remote_lead.get("status") or "").strip()
    if status == "Unsubscribed" or str(remote_lead.get("unsubscribed_at") or "").strip():
        return "do_not_contact"
    if (local_lead or {}).get("crm_sync_status") == "duplicate":
        return "duplicate"
    explicit = _explicit_outcome(notes)
    if explicit:
        return explicit
    if status == "Replied":
        return "valid_customer"
    if status == "Sent" and str(remote_lead.get("last_contacted_at") or "").strip():
        return "no_response"
    return ""


def _is_verified(lead: dict) -> bool:
    status = str(lead.get("email_verification_status") or "").lower()
    notes = str(lead.get("notes") or "").lower()
    return status == "valid" or "hunter verification: valid" in notes


def _lead_csv(lead: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CRM_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerow(
        {
            field: " ".join(str(lead.get(field, "") or "").splitlines())
            for field in CRM_FIELDS
        }
    )
    return output.getvalue()


def _build_remote_index(remote_leads: list[dict]) -> dict[str, dict[str, dict]]:
    by_email: dict[str, dict] = {}
    by_domain: dict[str, dict] = {}
    by_company: dict[str, dict] = {}
    for lead in remote_leads:
        email = str(lead.get("email") or "").strip().lower()
        if email and email not in by_email:
            by_email[email] = lead
        domain = normalize_domain(lead.get("website", ""))
        if domain and domain not in by_domain:
            by_domain[domain] = lead
        company = str(lead.get("company_name") or "").strip().lower()
        if company and company not in by_company:
            by_company[company] = lead
    return {"by_email": by_email, "by_domain": by_domain, "by_company": by_company}


def _match_remote_lead(local_lead: dict, remote_index: dict[str, dict[str, dict]]) -> dict | None:
    email = str(local_lead.get("email") or "").strip().lower()
    if email and email in remote_index["by_email"]:
        return remote_index["by_email"][email]
    domain = normalize_domain(local_lead.get("website", ""))
    if domain and domain in remote_index["by_domain"]:
        return remote_index["by_domain"][domain]
    company = str(local_lead.get("company_name") or "").strip().lower()
    if company and company in remote_index["by_company"]:
        return remote_index["by_company"][company]
    return None


def _explicit_outcome(notes: str) -> str:
    for label in OUTCOME_LABELS:
        pattern = rf"(?<![a-z_]){re.escape(label)}(?![a-z_])"
        if re.search(pattern, notes):
            return label
    return ""


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float,
) -> dict:
    parsed = urllib.parse.urlparse(str(base_url or "").strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("CRM URL must use local HTTP")
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        return call_with_limited_retry(
            lambda: _read_json_response(request, timeout),
            retries=1,
        )
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CRM HTTP {error.code}: {detail}") from error


def _append_note(existing: str, note: str) -> str:
    return "\n".join(part for part in [str(existing or "").strip(), note.strip()] if part)


def _read_json_response(request, timeout: float) -> dict:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")
