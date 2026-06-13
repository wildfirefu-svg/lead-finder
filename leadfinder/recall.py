from __future__ import annotations

import json
import sqlite3


def recall_report(db: sqlite3.Connection, run_id: int | None = None) -> dict:
    run = _load_run(db, run_id)
    if not run:
        return {"run": None, "rows": []}

    serper_groups = _serper_groups(db, run["id"])
    lead_groups = _lead_groups(db, run["id"])
    rows: list[dict] = []

    for key in sorted(set(serper_groups) | set(lead_groups)):
        country, locale, product_family = key
        serper = serper_groups.get(key, {"search_terms": [], "serper_queries": 0})
        leads = lead_groups.get(
            key,
            {
                "leads_created": 0,
                "qualified_count": 0,
                "rejected_count": 0,
                "valid_email_count": 0,
            },
        )
        serper_queries = int(serper["serper_queries"])
        qualified_count = int(leads["qualified_count"])
        rows.append(
            {
                "country": country,
                "locale": locale,
                "product_family": product_family,
                "search_terms": list(serper["search_terms"]),
                "serper_queries": serper_queries,
                "leads_created": int(leads["leads_created"]),
                "qualified_count": qualified_count,
                "rejected_count": int(leads["rejected_count"]),
                "valid_email_count": int(leads["valid_email_count"]),
                "qualified_per_query": round(qualified_count / serper_queries, 3) if serper_queries else 0,
            }
        )

    return {"run": dict(run), "rows": rows}


def _load_run(db: sqlite3.Connection, run_id: int | None) -> sqlite3.Row | None:
    if run_id is not None:
        return db.execute("SELECT * FROM campaign_runs WHERE id = ?", (int(run_id),)).fetchone()
    return db.execute("SELECT * FROM campaign_runs ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()


def _serper_groups(db: sqlite3.Connection, run_id: int) -> dict[tuple[str, str, str], dict]:
    groups: dict[tuple[str, str, str], dict] = {}
    rows = db.execute(
        """
        SELECT message
        FROM provider_events
        WHERE campaign_run_id = ?
          AND provider = 'Serper'
          AND event_type = 'search'
          AND status = 'ok'
        ORDER BY id
        """,
        (int(run_id),),
    ).fetchall()

    for row in rows:
        payload = _parse_event_message(row["message"])
        if not payload:
            continue
        key = (
            str(payload.get("country", "") or "").strip(),
            str(payload.get("locale", "") or "").strip(),
            str(payload.get("product_family", "") or "").strip(),
        )
        group = groups.setdefault(key, {"search_terms": [], "serper_queries": 0, "_seen_terms": set()})
        group["serper_queries"] += 1
        query = str(payload.get("query", "") or "").strip()
        if query and query not in group["_seen_terms"]:
            group["_seen_terms"].add(query)
            group["search_terms"].append(query)

    for group in groups.values():
        group.pop("_seen_terms", None)
    return groups


def _parse_event_message(message: str) -> dict | None:
    try:
        payload = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _lead_groups(db: sqlite3.Connection, run_id: int) -> dict[tuple[str, str, str], dict]:
    groups: dict[tuple[str, str, str], dict] = {}
    rows = db.execute(
        """
        SELECT country_region, query_locale, product_family, status, email, email_verification_status
        FROM leads
        WHERE campaign_run_id = ?
        ORDER BY id
        """,
        (int(run_id),),
    ).fetchall()

    for row in rows:
        key = (
            str(row["country_region"] or "").strip(),
            str(row["query_locale"] or "").strip(),
            str(row["product_family"] or "").strip(),
        )
        group = groups.setdefault(
            key,
            {
                "leads_created": 0,
                "qualified_count": 0,
                "rejected_count": 0,
                "valid_email_count": 0,
            },
        )
        status = str(row["status"] or "").strip().lower()
        group["leads_created"] += 1
        group["qualified_count"] += int(status == "qualified")
        group["rejected_count"] += int(status == "rejected")
        group["valid_email_count"] += int(_has_valid_email(row))

    return groups


def _has_valid_email(row: sqlite3.Row) -> bool:
    email = str(row["email"] or "").strip()
    verification_status = str(row["email_verification_status"] or "").strip().lower()
    if not email:
        return False
    return verification_status == "valid"
