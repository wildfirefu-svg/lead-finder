from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request

from .db import list_leads, update_lead
from .exporter import CRM_FIELDS
from .security import sanitize_error


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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CRM HTTP {error.code}: {detail}") from error


def _append_note(existing: str, note: str) -> str:
    return "\n".join(part for part in [str(existing or "").strip(), note.strip()] if part)
