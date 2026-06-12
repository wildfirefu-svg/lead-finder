from __future__ import annotations

from .db import list_leads

OUTCOME_LABELS = (
    "valid_customer",
    "not_buyer",
    "wrong_market",
    "duplicate",
    "no_response",
    "do_not_contact",
)


def crm_feedback_report(db) -> dict:
    rows_by_key: dict[tuple[str, str, str, str], dict] = {}
    totals = {label: 0 for label in OUTCOME_LABELS}
    totals["rows"] = 0
    totals["leads"] = 0

    for lead in list_leads(db, limit=None):
        outcome = str(lead.get("crm_outcome") or "").strip().lower()
        if outcome not in OUTCOME_LABELS:
            continue
        key = (
            str(lead.get("country_region") or "").strip(),
            str(lead.get("product_family") or "").strip(),
            str(lead.get("classification_status") or "").strip(),
            str(lead.get("discovery_query") or "").strip(),
        )
        row = rows_by_key.setdefault(
            key,
            {
                "country": key[0],
                "product_family": key[1],
                "classification_status": key[2],
                "discovery_query": key[3],
                "leads": 0,
                **{label: 0 for label in OUTCOME_LABELS},
                "suggestion": "needs_manual_confirmation",
            },
        )
        row["leads"] += 1
        row[outcome] += 1
        totals[outcome] += 1
        totals["leads"] += 1

    rows = sorted(
        rows_by_key.values(),
        key=lambda item: (
            -item["valid_customer"],
            item["do_not_contact"],
            item["wrong_market"],
            item["not_buyer"],
            item["country"],
            item["product_family"],
            item["classification_status"],
            item["discovery_query"],
        ),
    )
    for row in rows:
        row["suggestion"] = _suggestion(row)
    totals["rows"] = len(rows)
    return {"rows": rows, "totals": totals}


def _suggestion(row: dict) -> str:
    if int(row.get("do_not_contact") or 0) > 0:
        return "do_not_contact"
    positive = int(row.get("valid_customer") or 0)
    negative = sum(
        int(row.get(label) or 0)
        for label in ("not_buyer", "wrong_market", "duplicate", "no_response")
    )
    if positive > 0 and positive >= negative:
        return "prioritize_follow_up"
    return "needs_manual_confirmation"
