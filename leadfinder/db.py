from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .enrich import normalize_domain, normalize_url
from .security import sanitize_error

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hs_code TEXT NOT NULL,
  year INTEGER NOT NULL,
  country_region TEXT NOT NULL,
  import_value_usd REAL NOT NULL DEFAULT 0,
  source_name TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (hs_code, year, country_region)
);

CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL DEFAULT 'Website',
  source_name TEXT NOT NULL DEFAULT '',
  company_name TEXT NOT NULL DEFAULT '',
  country_region TEXT NOT NULL DEFAULT '',
  market_region TEXT NOT NULL DEFAULT '',
  website TEXT NOT NULL DEFAULT '',
  website_domain TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  contact_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  industry TEXT NOT NULL DEFAULT '',
  product_fit TEXT NOT NULL DEFAULT 'Both',
  fit_reason TEXT NOT NULL DEFAULT '',
  match_score INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'Discovered',
  crawl_status TEXT NOT NULL DEFAULT '',
  classification_status TEXT NOT NULL DEFAULT '',
  market_fit_status TEXT NOT NULL DEFAULT '',
  email_verification_status TEXT NOT NULL DEFAULT '',
  crm_sync_status TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  raw_text TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_domain
ON leads(website_domain)
WHERE website_domain <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email
ON leads(email)
WHERE email <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_company
ON leads(company_name COLLATE NOCASE)
WHERE company_name <> '';

CREATE TABLE IF NOT EXISTS campaign_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL DEFAULT '',
  hs_code TEXT NOT NULL DEFAULT '',
  year INTEGER NOT NULL DEFAULT 0,
  product TEXT NOT NULL DEFAULT 'both',
  market_limit INTEGER NOT NULL DEFAULT 0,
  per_market_limit INTEGER NOT NULL DEFAULT 0,
  providers TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'Running',
  created INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  quality_before TEXT NOT NULL DEFAULT '{}',
  quality_after TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS provider_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_run_id INTEGER NOT NULL,
  provider TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  cost_units REAL NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

LEAD_FIELDS = [
    "source_type",
    "source_name",
    "company_name",
    "country_region",
    "market_region",
    "website",
    "source_url",
    "contact_name",
    "email",
    "industry",
    "product_fit",
    "fit_reason",
    "match_score",
    "status",
    "crawl_status",
    "classification_status",
    "market_fit_status",
    "email_verification_status",
    "crm_sync_status",
    "notes",
    "raw_text",
]

LEAD_STATUS_COLUMNS = {
    "crawl_status": "TEXT NOT NULL DEFAULT ''",
    "classification_status": "TEXT NOT NULL DEFAULT ''",
    "market_fit_status": "TEXT NOT NULL DEFAULT ''",
    "email_verification_status": "TEXT NOT NULL DEFAULT ''",
    "crm_sync_status": "TEXT NOT NULL DEFAULT ''",
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    existing_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(leads)").fetchall()
    }
    for column, definition in LEAD_STATUS_COLUMNS.items():
        if column not in existing_columns:
            db.execute(f"ALTER TABLE leads ADD COLUMN {column} {definition}")
    db.commit()
    return db


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def upsert_market(db: sqlite3.Connection, market: dict) -> None:
    db.execute(
        """
        INSERT INTO markets (hs_code, year, country_region, import_value_usd, source_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hs_code, year, country_region) DO UPDATE SET
          import_value_usd = excluded.import_value_usd,
          source_name = excluded.source_name
        """,
        (
            market.get("hs_code", ""),
            int(market.get("year", 0)),
            market.get("country_region", ""),
            float(market.get("import_value_usd", 0) or 0),
            market.get("source_name", ""),
        ),
    )
    db.commit()


def list_markets(db: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM markets ORDER BY import_value_usd DESC, country_region LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def create_campaign_run(db: sqlite3.Connection, data: dict) -> dict:
    providers = data.get("providers", [])
    db.execute(
        """
        INSERT INTO campaign_runs
          (name, hs_code, year, product, market_limit, per_market_limit, providers, quality_before)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("name", ""),
            data.get("hs_code", ""),
            int(data.get("year", 0)),
            data.get("product", "both"),
            int(data.get("market_limit", 0)),
            int(data.get("per_market_limit", 0)),
            _json_text(providers),
            _json_text(data.get("quality_before", {})),
        ),
    )
    db.commit()
    return dict(db.execute("SELECT * FROM campaign_runs WHERE id = last_insert_rowid()").fetchone())


def finish_campaign_run(
    db: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    created: int,
    skipped: int,
    errors: int,
    quality_after: dict,
) -> dict:
    db.execute(
        """
        UPDATE campaign_runs
        SET status = ?, created = ?, skipped = ?, errors = ?,
            quality_after = ?, finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, int(created), int(skipped), int(errors), _json_text(quality_after), int(run_id)),
    )
    db.commit()
    return dict(db.execute("SELECT * FROM campaign_runs WHERE id = ?", (run_id,)).fetchone())


def record_provider_event(
    db: sqlite3.Connection,
    campaign_run_id: int,
    *,
    provider: str,
    event_type: str,
    status: str,
    cost_units: float,
    message: str,
) -> dict:
    db.execute(
        """
        INSERT INTO provider_events
          (campaign_run_id, provider, event_type, status, cost_units, message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(campaign_run_id),
            provider,
            event_type,
            status,
            float(cost_units),
            sanitize_error(message),
        ),
    )
    db.commit()
    return dict(db.execute("SELECT * FROM provider_events WHERE id = last_insert_rowid()").fetchone())


def list_campaign_runs(db: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM campaign_runs ORDER BY started_at DESC, id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_provider_events(db: sqlite3.Connection, campaign_run_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM provider_events WHERE campaign_run_id = ? ORDER BY id",
        (int(campaign_run_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def latest_provider_usage(db: sqlite3.Connection) -> dict:
    run = db.execute(
        "SELECT * FROM campaign_runs ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if not run:
        return {"run": None, "usage": {"Serper": 0, "Hunter.io": 0, "Apollo.io": 0}}
    usage = {"Serper": 0.0, "Hunter.io": 0.0, "Apollo.io": 0.0}
    for row in db.execute(
        """
        SELECT provider, SUM(cost_units) AS total
        FROM provider_events
        WHERE campaign_run_id = ?
        GROUP BY provider
        """,
        (run["id"],),
    ).fetchall():
        if row["provider"] in usage:
            usage[row["provider"]] = float(row["total"] or 0)
    return {"run": dict(run), "usage": usage}


def find_duplicate(db: sqlite3.Connection, lead: dict) -> dict | None:
    domain = normalize_domain(lead.get("website", ""))
    if domain:
        row = db.execute("SELECT * FROM leads WHERE website_domain = ? LIMIT 1", (domain,)).fetchone()
        if row:
            return dict(row)
    email = (lead.get("email") or "").strip().lower()
    if email:
        row = db.execute("SELECT * FROM leads WHERE lower(email) = ? LIMIT 1", (email,)).fetchone()
        if row:
            return dict(row)
    company = (lead.get("company_name") or "").strip()
    if company:
        row = db.execute("SELECT * FROM leads WHERE lower(company_name) = lower(?) LIMIT 1", (company,)).fetchone()
        if row:
            return dict(row)
    return None


def create_or_skip_lead(db: sqlite3.Connection, lead: dict) -> tuple[dict, bool]:
    normalized = {field: lead.get(field, "") for field in LEAD_FIELDS}
    normalized["source_type"] = normalized["source_type"] or "Website"
    normalized["product_fit"] = normalized["product_fit"] or "Both"
    normalized["status"] = normalized["status"] or "Discovered"
    normalized["website"] = normalize_url(normalized["website"]) if normalized["website"] else ""
    normalized["source_url"] = normalize_url(normalized["source_url"]) if normalized["source_url"] else normalized["website"]
    normalized["website_domain"] = normalize_domain(normalized["website"])
    normalized["email"] = str(normalized["email"] or "").strip().lower()
    normalized["match_score"] = int(normalized["match_score"] or 0)

    duplicate = find_duplicate(db, normalized)
    if duplicate:
        return duplicate, False

    fields = [*LEAD_FIELDS, "website_domain"]
    placeholders = ", ".join("?" for _ in fields)
    db.execute(
        f"INSERT INTO leads ({', '.join(fields)}) VALUES ({placeholders})",
        tuple(normalized[field] for field in fields),
    )
    db.commit()
    row = db.execute("SELECT * FROM leads WHERE id = last_insert_rowid()").fetchone()
    return dict(row), True


def update_lead(db: sqlite3.Connection, lead_id: int, updates: dict) -> dict:
    allowed = set(LEAD_FIELDS)
    next_updates = {key: value for key, value in updates.items() if key in allowed}
    if "website" in next_updates:
        next_updates["website"] = normalize_url(next_updates["website"])
        next_updates["website_domain"] = normalize_domain(next_updates["website"])
    if "email" in next_updates:
        next_updates["email"] = str(next_updates["email"] or "").strip().lower()
    if "match_score" in next_updates:
        next_updates["match_score"] = int(next_updates["match_score"] or 0)
    if not next_updates:
        row = db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row)
    assignments = ", ".join(f"{key} = ?" for key in next_updates)
    db.execute(
        f"UPDATE leads SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (*next_updates.values(), lead_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row)


def list_leads(db: sqlite3.Connection, status: str | None = None, limit: int | None = None) -> list[dict]:
    sql = "SELECT * FROM leads"
    params: list[object] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += """
      ORDER BY
        CASE status
          WHEN 'Qualified' THEN 0
          WHEN 'Discovered' THEN 1
          WHEN 'Enriched' THEN 2
          WHEN 'Error' THEN 3
          WHEN 'Rejected' THEN 4
          ELSE 5
        END,
        match_score DESC, updated_at DESC, id DESC
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def stats(db: sqlite3.Connection) -> dict:
    total = db.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"]
    by_status = {
        row["status"]: row["count"]
        for row in db.execute("SELECT status, COUNT(*) AS count FROM leads GROUP BY status").fetchall()
    }
    by_fit = {
        row["product_fit"]: row["count"]
        for row in db.execute("SELECT product_fit, COUNT(*) AS count FROM leads GROUP BY product_fit").fetchall()
    }
    markets = db.execute("SELECT COUNT(*) AS count FROM markets").fetchone()["count"]
    qualified_with_email = db.execute(
        "SELECT COUNT(*) AS count FROM leads WHERE status = 'Qualified' AND trim(email) <> ''"
    ).fetchone()["count"]
    return {
        "leads": total,
        "markets": markets,
        "qualified_with_email": qualified_with_email,
        "by_status": by_status,
        "by_product_fit": by_fit,
    }
