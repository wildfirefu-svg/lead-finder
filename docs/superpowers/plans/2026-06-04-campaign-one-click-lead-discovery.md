# Campaign One-Click Lead Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-click campaign workflow that selects markets with Comtrade, discovers leads with Serper, optionally enriches contacts with Apollo and Hunter, records provider/cost events, and refreshes the local workbench.

**Architecture:** Keep the existing SQLite-backed CLI and stdlib web server. Add campaign audit tables and a `leadfinder.campaigns` runner with injectable provider clients so tests run offline. Apollo and Hunter are optional API clients driven by `.env` keys; CSV-only platforms stay import sources, not automated scrapers.

**Tech Stack:** Python standard library, SQLite, `argparse`, `unittest`, `http.server`, vanilla HTML/CSS/JS.

---

## File Structure

### Create

- `leadfinder/campaigns.py`
  Campaign options, runner, provider orchestration, quality before/after comparison.

- `leadfinder/apollo.py`
  Small official-API client wrapper for Apollo People Search style contact lookup.

- `leadfinder/hunter.py`
  Small official-API client wrapper for Hunter domain search and email verification.

- `tests/test_campaigns.py`
  Offline tests for campaign runner, missing keys, dedupe, provider events, and quality delta.

- `tests/test_apollo_hunter.py`
  Offline tests for request/response mapping in Apollo and Hunter clients.

### Modify

- `leadfinder/config.py`
  Add `apollo_api_key` and `hunter_api_key`.

- `leadfinder/db.py`
  Add `campaign_runs` and `provider_events` tables plus helper functions.

- `leadfinder/providers.py`
  Add CSV-only supplier names from the approved list.

- `cli.py`
  Add `campaign` command.

- `leadfinder/webapp.py`
  Add campaign API endpoint and campaign panel in the workbench.

- `README.md`
  Document campaign usage, provider keys, and the quality gate.

---

### Task 1: Provider API Settings

**Files:**
- Modify: `leadfinder/config.py`
- Test: `tests/test_campaigns.py`

- [ ] **Step 1: Write failing settings test**

Create `tests/test_campaigns.py` with:

```python
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from leadfinder.config import settings


class CampaignSettingsTests(unittest.TestCase):
    def test_settings_loads_apollo_and_hunter_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "APOLLO_API_KEY=apollo-key\n"
                "HUNTER_API_KEY=hunter-key\n",
                encoding="utf-8",
            )
            original_apollo = os.environ.pop("APOLLO_API_KEY", None)
            original_hunter = os.environ.pop("HUNTER_API_KEY", None)
            try:
                cfg = settings(env_path)
            finally:
                if original_apollo is not None:
                    os.environ["APOLLO_API_KEY"] = original_apollo
                else:
                    os.environ.pop("APOLLO_API_KEY", None)
                if original_hunter is not None:
                    os.environ["HUNTER_API_KEY"] = original_hunter
                else:
                    os.environ.pop("HUNTER_API_KEY", None)

        self.assertEqual(cfg.apollo_api_key, "apollo-key")
        self.assertEqual(cfg.hunter_api_key, "hunter-key")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignSettingsTests.test_settings_loads_apollo_and_hunter_keys
```

Expected: fail with `AttributeError` for `apollo_api_key`.

- [ ] **Step 3: Add settings fields**

Modify `leadfinder/config.py`:

```python
@dataclass(frozen=True)
class Settings:
    serper_api_key: str
    apollo_api_key: str
    hunter_api_key: str
    db_path: Path
    max_pages: int
    timeout_seconds: float
```

Update `settings()`:

```python
    return Settings(
        serper_api_key=os.getenv("SERPER_API_KEY", "").strip(),
        apollo_api_key=os.getenv("APOLLO_API_KEY", "").strip(),
        hunter_api_key=os.getenv("HUNTER_API_KEY", "").strip(),
        db_path=Path(os.getenv("LEADFINDER_DB_PATH", "data/leadfinder.sqlite")),
        max_pages=max(1, min(int(os.getenv("LEADFINDER_MAX_PAGES", "5")), 12)),
        timeout_seconds=max(1.0, float(os.getenv("LEADFINDER_TIMEOUT_SECONDS", "12"))),
    )
```

- [ ] **Step 4: Run settings test**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignSettingsTests.test_settings_loads_apollo_and_hunter_keys
```

Expected: `OK`.

---

### Task 2: Campaign Audit Tables

**Files:**
- Modify: `leadfinder/db.py`
- Test: `tests/test_campaigns.py`

- [ ] **Step 1: Add failing DB tests**

Append to `tests/test_campaigns.py`:

```python
import json

from leadfinder.db import (
    connect,
    create_campaign_run,
    finish_campaign_run,
    list_campaign_runs,
    record_provider_event,
    list_provider_events,
)


class CampaignDbTests(unittest.TestCase):
    def test_campaign_run_and_provider_events_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run = create_campaign_run(
                    db,
                    {
                        "name": "HS7019 both",
                        "hs_code": "7019",
                        "year": 2024,
                        "product": "both",
                        "market_limit": 2,
                        "per_market_limit": 5,
                        "providers": ["Comtrade", "Serper"],
                        "quality_before": {"total": 0},
                    },
                )
                record_provider_event(
                    db,
                    run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message="query completed",
                )
                finish_campaign_run(
                    db,
                    run["id"],
                    status="Completed",
                    created=3,
                    skipped=1,
                    errors=0,
                    quality_after={"total": 3},
                )
                runs = list_campaign_runs(db)
                events = list_provider_events(db, run["id"])
            finally:
                db.close()

        self.assertEqual(runs[0]["status"], "Completed")
        self.assertEqual(runs[0]["created"], 3)
        self.assertEqual(json.loads(runs[0]["quality_before"])["total"], 0)
        self.assertEqual(json.loads(runs[0]["quality_after"])["total"], 3)
        self.assertEqual(events[0]["provider"], "Serper")
        self.assertEqual(events[0]["cost_units"], 1)
```

- [ ] **Step 2: Run DB test and verify it fails**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignDbTests.test_campaign_run_and_provider_events_are_recorded
```

Expected: fail because DB helper functions do not exist.

- [ ] **Step 3: Extend schema**

In `leadfinder/db.py`, append these table definitions to `SCHEMA` after the lead indexes:

```sql
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
```

- [ ] **Step 4: Add DB helper functions**

Add to `leadfinder/db.py`:

```python
import json
```

Add these functions:

```python
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
        (int(campaign_run_id), provider, event_type, status, float(cost_units), message),
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
```

- [ ] **Step 5: Run DB tests**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignDbTests.test_campaign_run_and_provider_events_are_recorded
```

Expected: `OK`.

---

### Task 3: Apollo And Hunter Clients

**Files:**
- Create: `leadfinder/apollo.py`
- Create: `leadfinder/hunter.py`
- Test: `tests/test_apollo_hunter.py`

- [ ] **Step 1: Write failing client tests**

Create `tests/test_apollo_hunter.py`:

```python
from __future__ import annotations

import unittest

from leadfinder.apollo import ApolloClient, apollo_people_to_contact
from leadfinder.hunter import HunterClient, hunter_domain_to_email, hunter_verification_note


class ApolloHunterTests(unittest.TestCase):
    def test_apollo_people_to_contact_maps_first_person(self) -> None:
        contact = apollo_people_to_contact(
            {
                "people": [
                    {
                        "name": "Jane Buyer",
                        "title": "Purchasing Manager",
                        "organization": {"name": "Example Composites"},
                    }
                ]
            }
        )

        self.assertEqual(contact["contact_name"], "Jane Buyer")
        self.assertIn("Purchasing Manager", contact["notes"])

    def test_hunter_domain_to_email_maps_best_email(self) -> None:
        email = hunter_domain_to_email(
            {
                "data": {
                    "emails": [
                        {"value": "info@example.com", "confidence": 60},
                        {"value": "sales@example.com", "confidence": 91},
                    ]
                }
            }
        )

        self.assertEqual(email["email"], "sales@example.com")
        self.assertIn("confidence=91", email["notes"])

    def test_hunter_verification_note_maps_status(self) -> None:
        note = hunter_verification_note({"data": {"status": "valid", "score": 98}})

        self.assertEqual(note, "Hunter verification: valid score=98")

    def test_clients_report_missing_keys(self) -> None:
        with self.assertRaises(RuntimeError):
            ApolloClient("").people_search("Example", "USA")
        with self.assertRaises(RuntimeError):
            HunterClient("").domain_search("example.com")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run client tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_apollo_hunter
```

Expected: fail because `leadfinder.apollo` and `leadfinder.hunter` do not exist.

- [ ] **Step 3: Implement Apollo client**

Create `leadfinder/apollo.py`:

```python
from __future__ import annotations

import json
import urllib.request


APOLLO_PEOPLE_URL = "https://api.apollo.io/v1/mixed_people/search"


class ApolloClient:
    def __init__(self, api_key: str, endpoint: str = APOLLO_PEOPLE_URL, timeout: float = 12.0):
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout

    def people_search(self, company: str, country: str = "", per_page: int = 3) -> dict:
        if not self.api_key:
            raise RuntimeError("APOLLO_API_KEY is required for Apollo enrichment.")
        payload = json.dumps(
            {
                "q_organization_name": company,
                "person_titles": ["purchasing", "procurement", "sourcing", "buyer", "import", "manager"],
                "page": 1,
                "per_page": max(1, min(int(per_page), 10)),
                "organization_locations": [country] if country else [],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "api_key": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "LeadFinder/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def apollo_people_to_contact(payload: dict) -> dict:
    people = payload.get("people") or payload.get("contacts") or []
    if not people:
        return {"contact_name": "", "notes": "Apollo: no matching contact returned"}
    person = people[0]
    name = person.get("name") or " ".join(part for part in [person.get("first_name"), person.get("last_name")] if part)
    title = person.get("title") or ""
    organization = person.get("organization") or {}
    org_name = organization.get("name") or ""
    notes = "Apollo contact"
    if title:
        notes += f": {title}"
    if org_name:
        notes += f" at {org_name}"
    return {"contact_name": name or "", "notes": notes}
```

- [ ] **Step 4: Implement Hunter client**

Create `leadfinder/hunter.py`:

```python
from __future__ import annotations

import json
import urllib.parse
import urllib.request


HUNTER_DOMAIN_URL = "https://api.hunter.io/v2/domain-search"
HUNTER_VERIFY_URL = "https://api.hunter.io/v2/email-verifier"


class HunterClient:
    def __init__(
        self,
        api_key: str,
        domain_endpoint: str = HUNTER_DOMAIN_URL,
        verify_endpoint: str = HUNTER_VERIFY_URL,
        timeout: float = 12.0,
    ):
        self.api_key = api_key
        self.domain_endpoint = domain_endpoint
        self.verify_endpoint = verify_endpoint
        self.timeout = timeout

    def domain_search(self, domain: str) -> dict:
        if not self.api_key:
            raise RuntimeError("HUNTER_API_KEY is required for Hunter enrichment.")
        query = urllib.parse.urlencode({"domain": domain, "api_key": self.api_key})
        with urllib.request.urlopen(f"{self.domain_endpoint}?{query}", timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def verify_email(self, email: str) -> dict:
        if not self.api_key:
            raise RuntimeError("HUNTER_API_KEY is required for Hunter enrichment.")
        query = urllib.parse.urlencode({"email": email, "api_key": self.api_key})
        with urllib.request.urlopen(f"{self.verify_endpoint}?{query}", timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def hunter_domain_to_email(payload: dict) -> dict:
    emails = (payload.get("data") or {}).get("emails") or []
    if not emails:
        return {"email": "", "notes": "Hunter domain search: no email returned"}
    best = sorted(emails, key=lambda item: int(item.get("confidence") or 0), reverse=True)[0]
    value = str(best.get("value") or "").lower()
    confidence = int(best.get("confidence") or 0)
    return {"email": value, "notes": f"Hunter domain search: confidence={confidence}"}


def hunter_verification_note(payload: dict) -> str:
    data = payload.get("data") or {}
    status = data.get("status") or "unknown"
    score = data.get("score")
    if score is None:
        return f"Hunter verification: {status}"
    return f"Hunter verification: {status} score={score}"
```

- [ ] **Step 5: Run client tests**

Run:

```powershell
python -m unittest tests.test_apollo_hunter
```

Expected: `OK`.

---

### Task 4: Campaign Runner

**Files:**
- Create: `leadfinder/campaigns.py`
- Test: `tests/test_campaigns.py`

- [ ] **Step 1: Add failing campaign runner tests**

Append to `tests/test_campaigns.py`:

```python
from leadfinder.campaigns import CampaignOptions, run_campaign


class FakeSerperClient:
    def search(self, query: str, num: int = 10) -> dict:
        return {
            "organic": [
                {
                    "title": "Example Fiberglass Buyer",
                    "link": "https://buyer.example",
                    "snippet": "Importer of HS 7019 fiberglass roving and fabric.",
                }
            ]
        }


class FakeApolloClient:
    def people_search(self, company: str, country: str = "", per_page: int = 3) -> dict:
        return {"people": [{"name": "Jane Buyer", "title": "Purchasing Manager"}]}


class FakeHunterClient:
    def domain_search(self, domain: str) -> dict:
        return {"data": {"emails": [{"value": "sales@buyer.example", "confidence": 92}]}}

    def verify_email(self, email: str) -> dict:
        return {"data": {"status": "valid", "score": 95}}


class CampaignRunnerTests(unittest.TestCase):
    def test_campaign_runs_with_fallback_markets_and_fake_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="7019",
                        year=2024,
                        product="both",
                        market_limit=1,
                        per_market_limit=1,
                        min_score=50,
                        use_serper=True,
                        use_apollo=True,
                        use_hunter=True,
                    ),
                    fetch_markets=lambda hs_code, year, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
                    serper_client=FakeSerperClient(),
                    apollo_client=FakeApolloClient(),
                    hunter_client=FakeHunterClient(),
                )
                rows = list_leads(db)
                runs = list_campaign_runs(db)
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["status"], "Completed")
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contact_name"], "Jane Buyer")
        self.assertEqual(rows[0]["email"], "sales@buyer.example")
        self.assertEqual(len(runs), 1)
        self.assertTrue(any(event["provider"] == "Comtrade" and event["status"] == "fallback" for event in events))
        self.assertIn("quality_before", result)
        self.assertIn("quality_after", result)

    def test_campaign_skips_missing_provider_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(use_serper=True, use_apollo=True, use_hunter=True),
                    fetch_markets=lambda hs_code, year, timeout: [],
                    serper_client=None,
                    apollo_client=None,
                    hunter_client=None,
                )
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["created"], 0)
        self.assertTrue(any(event["provider"] == "Serper" and event["status"] == "skipped" for event in events))
        self.assertTrue(any(event["provider"] == "Apollo.io" and event["status"] == "skipped" for event in events))
        self.assertTrue(any(event["provider"] == "Hunter.io" and event["status"] == "skipped" for event in events))
```

- [ ] **Step 2: Run campaign tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignRunnerTests
```

Expected: fail because `leadfinder.campaigns` does not exist.

- [ ] **Step 3: Implement campaign runner**

Create `leadfinder/campaigns.py` with these public names:

```python
from __future__ import annotations

from dataclasses import dataclass

from .apollo import apollo_people_to_contact
from .db import (
    create_campaign_run,
    create_or_skip_lead,
    finish_campaign_run,
    list_leads,
    record_provider_event,
    update_lead,
)
from .enrich import normalize_domain
from .hunter import hunter_domain_to_email, hunter_verification_note
from .markets import fallback_markets, fetch_comtrade_markets
from .quality import quality_report
from .scoring import score_lead
from .serper import build_queries, results_to_leads


@dataclass(frozen=True)
class CampaignOptions:
    hs_code: str = "7019"
    year: int = 2024
    product: str = "both"
    market_limit: int = 5
    per_market_limit: int = 20
    min_score: int = 50
    use_serper: bool = True
    use_apollo: bool = False
    use_hunter: bool = False
    timeout_seconds: float = 12.0


def _append_note(existing: str, note: str) -> str:
    parts = [part for part in [existing.strip(), note.strip()] if part]
    return "\n".join(parts)


def run_campaign(
    db,
    options: CampaignOptions,
    *,
    fetch_markets=fetch_comtrade_markets,
    serper_client=None,
    apollo_client=None,
    hunter_client=None,
) -> dict:
    quality_before = quality_report(list_leads(db), min_score=options.min_score)
    providers = ["Comtrade"]
    if options.use_serper:
        providers.append("Serper")
    if options.use_apollo:
        providers.append("Apollo.io")
    if options.use_hunter:
        providers.append("Hunter.io")

    run = create_campaign_run(
        db,
        {
            "name": f"HS{options.hs_code} {options.product}",
            "hs_code": options.hs_code,
            "year": options.year,
            "product": options.product,
            "market_limit": options.market_limit,
            "per_market_limit": options.per_market_limit,
            "providers": providers,
            "quality_before": quality_before,
        },
    )
    run_id = run["id"]
    created = 0
    skipped = 0
    errors = 0

    try:
        try:
            markets = fetch_markets(options.hs_code, options.year, options.timeout_seconds)
            record_provider_event(db, run_id, provider="Comtrade", event_type="markets", status="ok", cost_units=0, message=f"markets={len(markets)}")
        except Exception as error:
            markets = fallback_markets(options.hs_code, options.year)
            record_provider_event(db, run_id, provider="Comtrade", event_type="markets", status="fallback", cost_units=0, message=str(error))

        selected_markets = markets[: max(0, int(options.market_limit))]

        if options.use_serper and serper_client is None:
            record_provider_event(db, run_id, provider="Serper", event_type="search", status="skipped", cost_units=0, message="SERPER_API_KEY missing or client unavailable")
        elif options.use_serper:
            for market in selected_markets:
                country = market.get("country_region", "")
                for query in build_queries(country, options.product):
                    try:
                        payload = serper_client.search(query, num=max(1, min(options.per_market_limit, 100)))
                        record_provider_event(db, run_id, provider="Serper", event_type="search", status="ok", cost_units=1, message=query)
                    except Exception as error:
                        errors += 1
                        record_provider_event(db, run_id, provider="Serper", event_type="search", status="error", cost_units=0, message=str(error))
                        continue
                    for lead in results_to_leads(payload, country, query):
                        scored = {**lead, **score_lead(lead)}
                        row, was_created = create_or_skip_lead(db, scored)
                        created += int(was_created)
                        skipped += int(not was_created)
                        if was_created:
                            _enrich_optional(db, row, options, apollo_client, hunter_client, run_id)
                        if created >= options.market_limit * options.per_market_limit:
                            break
                    if created >= options.market_limit * options.per_market_limit:
                        break

        if options.use_apollo and apollo_client is None:
            record_provider_event(db, run_id, provider="Apollo.io", event_type="contact", status="skipped", cost_units=0, message="APOLLO_API_KEY missing or client unavailable")
        if options.use_hunter and hunter_client is None:
            record_provider_event(db, run_id, provider="Hunter.io", event_type="email", status="skipped", cost_units=0, message="HUNTER_API_KEY missing or client unavailable")

        quality_after = quality_report(list_leads(db), min_score=options.min_score)
        final = finish_campaign_run(
            db,
            run_id,
            status="Completed",
            created=created,
            skipped=skipped,
            errors=errors,
            quality_after=quality_after,
        )
        return {
            "run_id": run_id,
            "status": final["status"],
            "created": created,
            "skipped": skipped,
            "errors": errors,
            "quality_before": quality_before,
            "quality_after": quality_after,
        }
    except Exception:
        quality_after = quality_report(list_leads(db), min_score=options.min_score)
        finish_campaign_run(db, run_id, status="Error", created=created, skipped=skipped, errors=errors + 1, quality_after=quality_after)
        raise


def _enrich_optional(db, lead: dict, options: CampaignOptions, apollo_client, hunter_client, run_id: int) -> None:
    updates: dict = {}
    notes = lead.get("notes", "")

    if options.use_apollo and apollo_client is not None and lead.get("company_name"):
        try:
            payload = apollo_client.people_search(lead["company_name"], lead.get("country_region", ""))
            contact = apollo_people_to_contact(payload)
            if contact.get("contact_name"):
                updates["contact_name"] = contact["contact_name"]
            notes = _append_note(notes, contact.get("notes", ""))
            record_provider_event(db, run_id, provider="Apollo.io", event_type="contact", status="ok", cost_units=1, message=lead["company_name"])
        except Exception as error:
            record_provider_event(db, run_id, provider="Apollo.io", event_type="contact", status="error", cost_units=0, message=str(error))

    domain = normalize_domain(lead.get("website", ""))
    if options.use_hunter and hunter_client is not None and domain:
        try:
            payload = hunter_client.domain_search(domain)
            email = hunter_domain_to_email(payload)
            if email.get("email"):
                updates["email"] = email["email"]
                verify_payload = hunter_client.verify_email(email["email"])
                notes = _append_note(notes, hunter_verification_note(verify_payload))
            notes = _append_note(notes, email.get("notes", ""))
            record_provider_event(db, run_id, provider="Hunter.io", event_type="email", status="ok", cost_units=1.5, message=domain)
        except Exception as error:
            record_provider_event(db, run_id, provider="Hunter.io", event_type="email", status="error", cost_units=0, message=str(error))

    if notes != lead.get("notes", ""):
        updates["notes"] = notes
    if updates:
        merged = {**lead, **updates}
        scored = score_lead(merged)
        update_lead(db, lead["id"], {**updates, **scored})
```

- [ ] **Step 4: Run campaign runner tests**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignRunnerTests
```

Expected: `OK`.

---

### Task 5: CLI Campaign Command

**Files:**
- Modify: `cli.py`
- Test: `tests/test_campaigns.py`

- [ ] **Step 1: Add failing CLI campaign test**

Append to `tests/test_campaigns.py`:

```python
class CampaignCliTests(unittest.TestCase):
    def test_cli_campaign_runs_without_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            original_db = os.environ.get("LEADFINDER_DB_PATH")
            original_serper = os.environ.pop("SERPER_API_KEY", None)
            original_apollo = os.environ.pop("APOLLO_API_KEY", None)
            original_hunter = os.environ.pop("HUNTER_API_KEY", None)
            os.environ["LEADFINDER_DB_PATH"] = str(db_path)
            try:
                from cli import main

                exit_code = main(["campaign", "--market-limit", "1", "--per-market-limit", "1", "--no-serper"])
            finally:
                if original_db is None:
                    os.environ.pop("LEADFINDER_DB_PATH", None)
                else:
                    os.environ["LEADFINDER_DB_PATH"] = original_db
                if original_serper is not None:
                    os.environ["SERPER_API_KEY"] = original_serper
                if original_apollo is not None:
                    os.environ["APOLLO_API_KEY"] = original_apollo
                if original_hunter is not None:
                    os.environ["HUNTER_API_KEY"] = original_hunter

        self.assertEqual(exit_code, 0)
```

- [ ] **Step 2: Run CLI campaign test and verify it fails**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignCliTests.test_cli_campaign_runs_without_api_keys
```

Expected: fail because `campaign` subcommand does not exist.

- [ ] **Step 3: Add CLI imports and command handler**

Modify `cli.py` imports:

```python
from leadfinder.apollo import ApolloClient
from leadfinder.campaigns import CampaignOptions, run_campaign
from leadfinder.hunter import HunterClient
```

Add handler:

```python
def cmd_campaign(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        result = run_campaign(
            db,
            CampaignOptions(
                hs_code=args.hs,
                year=args.year,
                product=args.product,
                market_limit=args.market_limit,
                per_market_limit=args.per_market_limit,
                min_score=args.min_score,
                use_serper=not args.no_serper and bool(cfg.serper_api_key),
                use_apollo=args.apollo and bool(cfg.apollo_api_key),
                use_hunter=args.hunter and bool(cfg.hunter_api_key),
                timeout_seconds=cfg.timeout_seconds,
            ),
            serper_client=SerperClient(cfg.serper_api_key, timeout=cfg.timeout_seconds) if cfg.serper_api_key and not args.no_serper else None,
            apollo_client=ApolloClient(cfg.apollo_api_key, timeout=cfg.timeout_seconds) if cfg.apollo_api_key and args.apollo else None,
            hunter_client=HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds) if cfg.hunter_api_key and args.hunter else None,
        )
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
```

Add parser block before `stats_parser`:

```python
    campaign = sub.add_parser("campaign", help="Run one-click market selection and lead discovery.")
    campaign.add_argument("--hs", default="7019")
    campaign.add_argument("--year", type=int, default=2024)
    campaign.add_argument("--product", choices=["yarn", "fabric", "both"], default="both")
    campaign.add_argument("--market-limit", type=int, default=5)
    campaign.add_argument("--per-market-limit", type=int, default=20)
    campaign.add_argument("--min-score", type=int, default=50)
    campaign.add_argument("--no-serper", action="store_true")
    campaign.add_argument("--apollo", action="store_true")
    campaign.add_argument("--hunter", action="store_true")
    campaign.set_defaults(func=cmd_campaign)
```

- [ ] **Step 4: Run CLI campaign tests**

Run:

```powershell
python -m unittest tests.test_campaigns.CampaignCliTests.test_cli_campaign_runs_without_api_keys
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

---

### Task 6: Provider Directory Additions For CSV-Only Platforms

**Files:**
- Modify: `leadfinder/providers.py`
- Test: `tests/test_providers.py`

- [ ] **Step 1: Add failing provider directory test**

Append to `tests/test_providers.py`:

```python
    def test_provider_report_includes_csv_only_data_platforms(self) -> None:
        report = provider_report()
        names = {item["provider"] for item in report["providers"]}

        for name in [
            "Panjiva",
            "ImportGenius",
            "ZoomInfo",
            "Lusha",
            "BuiltWith",
            "SimilarWeb",
            "跨境搜",
            "跨境魔方",
            "Tendata",
            "TradeInfo",
            "孚盟软件",
            "信风数据",
            "格兰德",
            "Hunter.io",
        ]:
            self.assertIn(name, names)
```

- [ ] **Step 2: Run provider test and verify it fails**

Run:

```powershell
python -m unittest tests.test_providers.ProviderReportTests.test_provider_report_includes_csv_only_data_platforms
```

Expected: fail because these provider names are missing.

- [ ] **Step 3: Add providers**

In `leadfinder/providers.py`, add entries with:

```python
"Panjiva": {
    "provider": "Panjiva",
    "category": "trade_data",
    "cost_model": "paid_or_contract",
    "api_backed": False,
    "zero_cost_core": False,
    "allowed_use": "CSV import from user-authorized trade data exports.",
    "notes": "Do not scrape logged-in or paid member pages.",
},
```

Repeat the same structure with provider-specific `category`:

- `ImportGenius`: `trade_data`
- `ZoomInfo`: `contact_database`
- `Lusha`: `contact_enrichment`
- `BuiltWith`: `website_intelligence`
- `SimilarWeb`: `traffic_intelligence`
- `跨境搜`: `trade_data`
- `跨境魔方`: `trade_data`
- `Tendata`: `trade_data`
- `TradeInfo`: `trade_data`
- `孚盟软件`: `crm_intelligence`
- `信风数据`: `contact_enrichment`
- `格兰德`: `trade_data`
- `Hunter.io`: `contact_enrichment`, `cost_model` `free_credit_or_paid`, `api_backed` `True`, allowed use `Official API or exported CSV for domain email search and verification.`

Add aliases:

```python
"hunter": "Hunter.io",
"hunter.io": "Hunter.io",
"importgenius": "ImportGenius",
"similarweb": "SimilarWeb",
"builtwith": "BuiltWith",
"panjiva": "Panjiva",
"zoominfo": "ZoomInfo",
"lusha": "Lusha",
"tendata": "Tendata",
"tradeinfo": "TradeInfo",
```

- [ ] **Step 4: Run provider tests**

Run:

```powershell
python -m unittest tests.test_providers
```

Expected: `OK`.

---

### Task 7: Web Campaign API And UI Panel

**Files:**
- Modify: `leadfinder/webapp.py`
- Test: `tests/test_webapp.py`

- [ ] **Step 1: Add failing web campaign API test**

Append to `tests/test_webapp.py`:

```python
    def test_api_campaign_runs_without_serper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            status, headers, body = app.handle(
                "POST",
                "/api/campaign",
                json.dumps(
                    {
                        "hs_code": "7019",
                        "year": 2024,
                        "product": "both",
                        "market_limit": 1,
                        "per_market_limit": 1,
                        "use_serper": False,
                        "use_apollo": False,
                        "use_hunter": False,
                    }
                ).encode("utf-8"),
            )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["result"]["status"], "Completed")
        self.assertIn("quality_after", payload["result"])
```

- [ ] **Step 2: Run web campaign test and verify it fails**

Run:

```powershell
python -m unittest tests.test_webapp.WebAppTests.test_api_campaign_runs_without_serper
```

Expected: fail because `/api/campaign` is not implemented.

- [ ] **Step 3: Add webapp imports**

Modify `leadfinder/webapp.py` imports:

```python
from .apollo import ApolloClient
from .campaigns import CampaignOptions, run_campaign
from .config import settings
from .hunter import HunterClient
from .serper import SerperClient
```

- [ ] **Step 4: Add `/api/campaign` endpoint**

In `LocalLeadApp.handle()`, before the status update route:

```python
        if method == "POST" and parsed.path == "/api/campaign":
            cfg = settings()
            payload = json.loads(body.decode("utf-8") or "{}")
            use_serper = bool(payload.get("use_serper", True)) and bool(cfg.serper_api_key)
            use_apollo = bool(payload.get("use_apollo", False)) and bool(cfg.apollo_api_key)
            use_hunter = bool(payload.get("use_hunter", False)) and bool(cfg.hunter_api_key)
            options = CampaignOptions(
                hs_code=str(payload.get("hs_code") or "7019"),
                year=int(payload.get("year") or 2024),
                product=str(payload.get("product") or "both"),
                market_limit=max(1, min(int(payload.get("market_limit") or 5), 20)),
                per_market_limit=max(1, min(int(payload.get("per_market_limit") or 20), 100)),
                min_score=int(payload.get("min_score") or 50),
                use_serper=use_serper,
                use_apollo=use_apollo,
                use_hunter=use_hunter,
                timeout_seconds=cfg.timeout_seconds,
            )
            db = connect(self.db_path)
            try:
                result = run_campaign(
                    db,
                    options,
                    serper_client=SerperClient(cfg.serper_api_key, timeout=cfg.timeout_seconds) if use_serper else None,
                    apollo_client=ApolloClient(cfg.apollo_api_key, timeout=cfg.timeout_seconds) if use_apollo else None,
                    hunter_client=HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds) if use_hunter else None,
                )
            finally:
                db.close()
            return self.json_response({"result": result})
```

- [ ] **Step 5: Add campaign panel to `INDEX_HTML`**

Add a `<section class="campaign">` before metrics:

```html
    <section class="campaign" aria-label="Campaign controls">
      <div class="campaign-grid">
        <label>HS code <input id="campaign-hs" value="7019"></label>
        <label>Year <input id="campaign-year" type="number" value="2024"></label>
        <label>Product
          <select id="campaign-product">
            <option value="both">Both</option>
            <option value="yarn">Yarn</option>
            <option value="fabric">Fabric</option>
          </select>
        </label>
        <label>Markets <input id="campaign-markets" type="number" value="3" min="1" max="20"></label>
        <label>Per market <input id="campaign-per-market" type="number" value="10" min="1" max="100"></label>
      </div>
      <div class="provider-row">
        <label><input id="campaign-serper" type="checkbox" checked> Serper</label>
        <label><input id="campaign-apollo" type="checkbox"> Apollo</label>
        <label><input id="campaign-hunter" type="checkbox"> Hunter</label>
        <button id="run-campaign" type="button">Run Campaign</button>
      </div>
      <pre id="campaign-summary"></pre>
    </section>
```

Add CSS:

```css
    .campaign {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 12px;
      margin-bottom: 14px;
    }
    .campaign-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 10px;
    }
    .campaign label {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    input {
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 6px 8px;
      font: inherit;
    }
    .provider-row {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 10px;
    }
    #campaign-summary {
      margin: 10px 0 0;
      white-space: pre-wrap;
      color: var(--muted);
    }
```

Add JS:

```javascript
    async function runCampaign() {
      const summary = document.getElementById('campaign-summary');
      summary.textContent = 'Running campaign... small limits are recommended because API credits may be spent.';
      const response = await fetch('/api/campaign', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          hs_code: document.getElementById('campaign-hs').value,
          year: Number(document.getElementById('campaign-year').value),
          product: document.getElementById('campaign-product').value,
          market_limit: Number(document.getElementById('campaign-markets').value),
          per_market_limit: Number(document.getElementById('campaign-per-market').value),
          use_serper: document.getElementById('campaign-serper').checked,
          use_apollo: document.getElementById('campaign-apollo').checked,
          use_hunter: document.getElementById('campaign-hunter').checked
        })
      });
      const payload = await response.json();
      summary.textContent = JSON.stringify(payload.result || payload, null, 2);
      await loadLeads();
    }
    document.getElementById('run-campaign').addEventListener('click', runCampaign);
```

- [ ] **Step 6: Run web tests**

Run:

```powershell
python -m unittest tests.test_webapp
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

---

### Task 8: README And Visual Verification

**Files:**
- Modify: `README.md`
- Screenshot outputs: `exports/leadfinder_workbench.png`, `exports/leadfinder_workbench_mobile.png`

- [ ] **Step 1: Update README**

Add under commands:

```powershell
python cli.py campaign --hs 7019 --year 2024 --product both --market-limit 3 --per-market-limit 10
python cli.py campaign --hs 7019 --year 2024 --product both --market-limit 3 --per-market-limit 10 --apollo --hunter
```

Add notes:

```markdown
## Campaign workflow

The `campaign` command runs Comtrade market selection, Serper discovery, optional Apollo contact lookup, optional Hunter email lookup and verification, then records quality before and after the run.

Serper, Apollo, and Hunter are optional credit-based providers. Missing API keys disable those providers rather than failing the whole campaign.

Use small limits first:

```powershell
python cli.py campaign --market-limit 1 --per-market-limit 3
```
```

- [ ] **Step 2: Run all tests**

Run:

```powershell
python -m unittest discover -s tests -p test_*.py
```

Expected: `OK`.

- [ ] **Step 3: Verify CLI help**

Run:

```powershell
python cli.py --help
```

Expected: subcommands include `campaign`.

- [ ] **Step 4: Verify no-key campaign does not fail**

Run:

```powershell
python cli.py campaign --market-limit 1 --per-market-limit 1 --no-serper
```

Expected: JSON with `status` `Completed`, `created` `0`, and `quality_after`.

- [ ] **Step 5: Visual check desktop and mobile**

Start server:

```powershell
python cli.py serve --host 127.0.0.1 --port 8765
```

Use Playwright to capture desktop and mobile screenshots. Expected:

- Campaign panel is visible above metrics.
- Text fits on 390px mobile width.
- No campaign controls overlap lead table.
- Empty state remains visible.

- [ ] **Step 6: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add README.md cli.py leadfinder tests exports docs
git commit -m "feat: add one-click lead discovery campaign"
```

---

## Final Verification

- [ ] Run `python -m unittest discover -s tests -p test_*.py`; expected `OK`.
- [ ] Run `python cli.py campaign --market-limit 1 --per-market-limit 1 --no-serper`; expected completed JSON.
- [ ] Run `python cli.py provider-report`; expected Hunter and CSV-only providers listed.
- [ ] Run `python cli.py quality-report --min-score 50`; expected JSON metrics.
- [ ] Start `python cli.py serve`; expected workbench at `http://127.0.0.1:8765/`.
- [ ] Visually verify desktop and mobile workbench screenshots.

## Self-Review

- Spec coverage: The plan covers Comtrade, Serper, Apollo, Hunter, CSV-only provider directory entries, campaign audit tables, CLI, web UI, and quality gates.
- Placeholder scan: No unresolved placeholder language is present.
- Type consistency: `CampaignOptions`, `run_campaign`, `ApolloClient`, `HunterClient`, `create_campaign_run`, and `record_provider_event` are introduced before dependent tasks use them.
- Scope check: The plan does not automate logged-in SaaS dashboards, paid member pages, email sending, CRM writes, or Bright Data.
