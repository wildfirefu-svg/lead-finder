# Stage B Lead Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase qualified fiberglass buyer discovery across more countries and product families while preserving every Stage A accuracy and paid-enrichment gate.

**Architecture:** Keep the current synchronous Python + SQLite workflow, but move localized search rules into a dedicated query catalog and persist enough campaign metadata to measure recall by country, locale, product family, and search term. Extend the existing campaign run and workbench flow instead of adding a second pipeline, so Stage B remains a focused expansion of the Stage A system rather than a rewrite.

**Tech Stack:** Python stdlib, SQLite, unittest, existing local HTTP workbench, existing CLI commands.

---

## File Structure

- Create `leadfinder/query_catalog.py`
  - Owns fiberglass HS-to-product-family mapping, localized term seeds, and deterministic per-country query specs.
  - Keeps `leadfinder/serper.py` focused on the Serper transport and result parsing.
- Create `leadfinder/recall.py`
  - Owns recall reporting and productivity summaries by run, country, locale, family, and search term.
  - Avoids overloading `campaigns.py` with analytics formatting logic.
- Modify `leadfinder/serper.py`
  - Keep `SerperClient` and `results_to_leads()` unchanged in shape.
  - Make query building delegate to the new catalog so existing callers stay compatible.
- Modify `leadfinder/campaigns.py`
  - Replace free-form query loops with structured query specs.
  - Persist run metadata on created leads and record structured Serper event messages for recall analysis.
- Modify `leadfinder/db.py`
  - Add minimal lead columns needed for per-run recall reporting.
  - Add a filtered lead-list path for report queries.
- Modify `leadfinder/webapp.py`
  - Expand the campaign product selector to real product families.
  - Add a recall quality report section and API endpoint.
- Modify `cli.py`
  - Widen `campaign --product` choices to the new family slugs.
  - Add `recall-report` for terminal verification without the browser.
- Test files:
  - Create `tests/test_query_catalog.py`.
  - Create `tests/test_recall.py`.
  - Modify `tests/test_campaigns.py`.
  - Modify `tests/test_webapp.py`.
  - Modify `tests/test_leadfinder.py` only if a compatibility assertion for `build_queries()` is needed.
- Modify `README.md`
  - Document Stage B family selection, localized recall reporting, and the new CLI report command.

---

### Task 1: Centralize HS Product Families and Localized Query Specs

**Files:**
- Create: `leadfinder/query_catalog.py`
- Modify: `leadfinder/serper.py`
- Test: `tests/test_query_catalog.py`
- Test: `tests/test_leadfinder.py`

- [ ] **Step 1: Write the failing query-catalog tests**

Create `tests/test_query_catalog.py`:

```python
from __future__ import annotations

import unittest

from leadfinder.query_catalog import build_query_specs, product_families_for_hs


class QueryCatalogTests(unittest.TestCase):
    def test_product_families_for_hs_7019_returns_multiple_fiberglass_families(self) -> None:
        families = product_families_for_hs("7019", "all")

        self.assertEqual(
            families,
            [
                "roving",
                "yarn",
                "woven_fabric",
                "mat",
                "mesh",
                "chopped_strand",
                "tissue",
                "insulation_fabric",
            ],
        )

    def test_product_families_for_specific_hs_prefers_matching_family(self) -> None:
        self.assertEqual(product_families_for_hs("701912", "all"), ["roving"])
        self.assertEqual(product_families_for_hs("701971", "all"), ["tissue"])

    def test_build_query_specs_for_germany_include_locale_family_and_terms(self) -> None:
        specs = build_query_specs("Germany", "701912", "all")

        self.assertTrue(specs)
        self.assertTrue(all(spec["country"] == "Germany" for spec in specs))
        self.assertTrue(all(spec["locale"] == "de-DE" for spec in specs))
        self.assertTrue(all(spec["product_family"] == "roving" for spec in specs))
        self.assertTrue(any("glasfaser" in spec["query"].lower() for spec in specs))
        self.assertTrue(any("GFK" in spec["query"] for spec in specs))

    def test_build_query_specs_for_7019_all_returns_multiple_families(self) -> None:
        specs = build_query_specs("Canada", "7019", "all")
        families = {spec["product_family"] for spec in specs}

        self.assertIn("roving", families)
        self.assertIn("woven_fabric", families)
        self.assertIn("mat", families)
        self.assertTrue(any("Ontario" in spec["query"] for spec in specs))


if __name__ == "__main__":
    unittest.main()
```

Add this compatibility test to `tests/test_leadfinder.py` near the existing query tests:

```python
    def test_build_queries_keeps_legacy_string_interface(self) -> None:
        queries = build_queries("Germany", "roving", hs_code="701912")

        self.assertTrue(queries)
        self.assertTrue(all(isinstance(query, str) for query in queries))
        self.assertTrue(any("glasfaser" in query.lower() for query in queries))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_query_catalog tests.test_leadfinder -v
```

Expected:

```text
ModuleNotFoundError: No module named 'leadfinder.query_catalog'
```

or:

```text
TypeError: build_queries() got an unexpected keyword argument 'hs_code'
```

- [ ] **Step 3: Create the query catalog**

Create `leadfinder/query_catalog.py`:

```python
from __future__ import annotations

QUERY_EXCLUSIONS = (
    "-site:zauba.com -site:thomasnet.com -site:exporthub.com "
    "-site:seair.co.in -site:volza.com -site:tradeindia.com "
    "-site:alibaba.com -site:made-in-china.com -site:globalsources.com "
    "-site:facebook.com -site:linkedin.com -site:openpr.com "
    "-site:instagram.com -site:pinterest.com -site:youtube.com "
    "-site:prnewswire.com -site:globenewswire.com -site:indexbox.io "
    "-site:justdial.com -site:jec-world.events -site:researchandmarkets.com "
    "-site:tradekey.com -site:kenresearch.com -site:marketreportanalytics.com "
    "-site:marketresearchfuture.com -site:marketresearch.com -site:datainsightsreports.com "
    "-filetype:pdf -site:compositesworld.com -site:scribd.com -site:marketresearch.biz "
    "-site:nasa.gov -site:okorder.com"
)

HS_PRODUCT_FAMILIES = {
    "7019": [
        "roving",
        "yarn",
        "woven_fabric",
        "mat",
        "mesh",
        "chopped_strand",
        "tissue",
        "insulation_fabric",
    ],
    "701911": ["chopped_strand"],
    "701912": ["roving"],
    "701913": ["yarn"],
    "701914": ["mat"],
    "701915": ["mat"],
    "701919": ["roving", "yarn", "mat", "chopped_strand"],
    "701961": ["woven_fabric"],
    "701962": ["woven_fabric"],
    "701963": ["woven_fabric"],
    "701964": ["woven_fabric"],
    "701965": ["mesh"],
    "701966": ["mesh"],
    "701969": ["woven_fabric"],
    "701971": ["tissue"],
    "701972": ["tissue"],
    "701973": ["mesh"],
    "701980": ["insulation_fabric"],
    "701990": ["roving", "yarn", "woven_fabric", "mat", "mesh", "tissue"],
}

PRODUCT_FAMILY_LABELS = {
    "all": "全部",
    "roving": "粗纱 / Roving",
    "yarn": "纱线 / Yarn",
    "woven_fabric": "织物 / Woven Fabric",
    "mat": "毡 / Mat",
    "mesh": "网格布 / Mesh",
    "chopped_strand": "短切原丝 / Chopped Strand",
    "tissue": "薄毡 / Tissue",
    "insulation_fabric": "绝缘布 / Insulation Fabric",
}

COUNTRY_LOCALES = {
    "canada": "en-CA",
    "usa": "en-US",
    "united states": "en-US",
    "mexico": "es-MX",
    "germany": "de-DE",
    "france": "fr-FR",
    "united kingdom": "en-GB",
    "italy": "it-IT",
    "spain": "es-ES",
    "netherlands": "nl-NL",
    "poland": "pl-PL",
    "vietnam": "vi-VN",
    "thailand": "th-TH",
    "indonesia": "id-ID",
    "malaysia": "en-MY",
    "philippines": "en-PH",
    "singapore": "en-SG",
    "india": "en-IN",
    "united arab emirates": "ar-AE",
    "saudi arabia": "ar-SA",
    "turkey": "tr-TR",
    "japan": "ja-JP",
    "south korea": "ko-KR",
    "brazil": "pt-BR",
    "morocco": "fr-MA",
    "south africa": "en-ZA",
}

QUERY_TEMPLATES = {
    "roving": [
        '"fiberglass roving" "pultrusion" "capabilities" {country}',
        '"fiberglass roving" "filament winding" "capabilities" {country}',
        '"fiberglass roving" "FRP" "contact us" {country}',
        '"fiberglass roving" "custom pultrusions" {country}',
    ],
    "yarn": [
        '"glass fiber yarn" "composites" {country}',
        '"fiberglass yarn" buyer {country}',
        '"glass fibre yarn" "FRP" {country}',
    ],
    "woven_fabric": [
        '"fiberglass fabric" importer {country}',
        '"woven roving" buyer {country}',
        '"fiberglass cloth" distributor {country}',
        '"insulation fabric" composites {country}',
    ],
    "mat": [
        '"chopped strand mat" buyer {country}',
        '"glass fiber mat" composites {country}',
        '"FRP" "mat" "contact us" {country}',
    ],
    "mesh": [
        '"fiberglass mesh" importer {country}',
        '"glass fiber mesh" distributor {country}',
        '"reinforcement mesh" composites {country}',
    ],
    "chopped_strand": [
        '"chopped strand" composites {country}',
        '"glass fiber chopped strand" buyer {country}',
        '"thermoplastic" "glass fiber" {country}',
    ],
    "tissue": [
        '"glass fiber tissue" buyer {country}',
        '"fiberglass veil" composites {country}',
        '"surface tissue" FRP {country}',
    ],
    "insulation_fabric": [
        '"insulation fabric" "glass fiber" {country}',
        '"heat resistant fiberglass cloth" {country}',
        '"thermal insulation fabric" composites {country}',
    ],
}

LOCALIZED_TEMPLATES = {
    ("germany", "roving"): [
        'site:.de "glasfaser roving" "pultrusion"',
        'site:.de "GFK" "profile"',
        '"GFK" "Roving" Deutschland',
    ],
    ("france", "roving"): [
        'site:.fr "fibre de verre" "pultrusion"',
        'site:.fr "roving fibre de verre"',
    ],
    ("morocco", "roving"): [
        'site:.ma "fibre de verre" "composite"',
        '"fibre de verre" "Maroc" "composite"',
    ],
    ("canada", "roving"): [
        'site:.ca "fiberglass rebar"',
        'site:.ca "pultrusion" "FRP"',
        '"fiberglass roving" "Ontario" "composites"',
    ],
    ("mexico", "roving"): [
        'site:.mx "fibra de vidrio" "pultrusion"',
        '"fibra de vidrio" "FRP" Mexico',
    ],
    ("germany", "woven_fabric"): [
        'site:.de "glasfasergewebe" "GFK"',
    ],
    ("france", "woven_fabric"): [
        'site:.fr "tissu fibre de verre"',
    ],
    ("brazil", "woven_fabric"): [
        'site:.br "fibra de vidro" "tecido"',
    ],
}


def product_families_for_hs(hs_code: str, selected_product: str = "all") -> list[str]:
    product_key = str(selected_product or "all").strip().lower().replace("-", "_")
    normalized_hs = "".join(char for char in str(hs_code or "") if char.isdigit())
    if product_key and product_key != "all":
        return [product_key]
    return list(HS_PRODUCT_FAMILIES.get(normalized_hs, HS_PRODUCT_FAMILIES["7019"]))


def build_query_specs(country: str, hs_code: str, selected_product: str = "all") -> list[dict]:
    country_name = str(country or "").strip()
    country_key = country_name.lower()
    locale = COUNTRY_LOCALES.get(country_key, "en-US")
    specs: list[dict] = []
    for family in product_families_for_hs(hs_code, selected_product):
        templates = []
        templates.extend(LOCALIZED_TEMPLATES.get((country_key, family), []))
        templates.extend(QUERY_TEMPLATES.get(family, []))
        for template in templates:
            query = f"{template.format(country=country_name)} {QUERY_EXCLUSIONS}".strip()
            specs.append(
                {
                    "country": country_name,
                    "locale": locale,
                    "product_family": family,
                    "query": query,
                }
            )
    deduped: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for spec in specs:
        key = (spec["country"], spec["locale"], spec["product_family"], spec["query"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped
```

- [ ] **Step 4: Route legacy query building through the catalog**

Modify `leadfinder/serper.py` imports:

```python
from .query_catalog import QUERY_EXCLUSIONS, build_query_specs
```

Delete the old `YARN_QUERIES`, `FABRIC_QUERIES`, `LOCAL_YARN_QUERIES`, and `LOCAL_FABRIC_QUERIES` constants.

Replace `build_queries()` with:

```python
def build_queries(country: str, product: str = "all", hs_code: str = "7019") -> list[str]:
    return [spec["query"] for spec in build_query_specs(country, hs_code, product)]
```

Keep `results_to_leads()` unchanged.

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_query_catalog tests.test_leadfinder -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add leadfinder/query_catalog.py leadfinder/serper.py tests/test_query_catalog.py tests/test_leadfinder.py
git commit -m "Add localized recall query catalog"
```

Expected:

```text
[main <hash>] Add localized recall query catalog
```

---

### Task 2: Persist Recall Metadata and Use Structured Query Specs in Campaign Runs

**Files:**
- Modify: `leadfinder/db.py`
- Modify: `leadfinder/campaigns.py`
- Modify: `tests/test_campaigns.py`

- [ ] **Step 1: Write the failing campaign metadata tests**

Add these tests to `tests/test_campaigns.py`:

```python
    def test_campaign_persists_recall_metadata_on_created_lead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="all",
                        target_countries=("Germany",),
                        per_market_limit=1,
                        use_serper=True,
                    ),
                    serper_client=FakeSerperClient(),
                    site_enricher=downstream_site_enricher,
                )
                row = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(result["created"], 1)
        self.assertEqual(row["campaign_run_id"], result["run_id"])
        self.assertEqual(row["query_locale"], "de-DE")
        self.assertEqual(row["product_family"], "roving")
        self.assertIn("glasfaser", row["discovery_query"].lower())

    def test_campaign_records_structured_serper_event_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="all",
                        target_countries=("Germany",),
                        per_market_limit=1,
                        use_serper=True,
                    ),
                    serper_client=FakeSerperClient(),
                    site_enricher=downstream_site_enricher,
                )
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        event = next(event for event in events if event["provider"] == "Serper" and event["status"] == "ok")
        payload = json.loads(event["message"])
        self.assertEqual(payload["country"], "Germany")
        self.assertEqual(payload["locale"], "de-DE")
        self.assertEqual(payload["product_family"], "roving")
        self.assertIn("query", payload)
```

Add a tighter per-country query-budget test:

```python
    def test_campaign_enforces_per_country_query_budget_independently(self) -> None:
        client = RecordingSerperClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="7019",
                        product="all",
                        target_countries=("Germany", "France"),
                        per_market_limit=2,
                        use_serper=True,
                    ),
                    serper_client=client,
                )
            finally:
                db.close()

        germany_queries = [query for query in client.queries if "Germany" in query or "Deutschland" in query]
        france_queries = [query for query in client.queries if "France" in query or "fibre de verre" in query]
        self.assertEqual(len(germany_queries), 2)
        self.assertEqual(len(france_queries), 2)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_campaigns -v
```

Expected:

```text
KeyError: 'campaign_run_id'
```

or:

```text
json.JSONDecodeError
```

because the Serper event message is still plain text.

- [ ] **Step 3: Add minimal recall metadata columns**

In `leadfinder/db.py`, add these columns to the `leads` table after `review_status`:

```python
  campaign_run_id INTEGER NOT NULL DEFAULT 0,
  discovery_query TEXT NOT NULL DEFAULT '',
  query_locale TEXT NOT NULL DEFAULT '',
  product_family TEXT NOT NULL DEFAULT '',
```

Add these fields to `LEAD_FIELDS` after `review_status`:

```python
    "campaign_run_id",
    "discovery_query",
    "query_locale",
    "product_family",
```

Add these fields to `LEAD_STATUS_COLUMNS`:

```python
    "campaign_run_id": "INTEGER NOT NULL DEFAULT 0",
    "discovery_query": "TEXT NOT NULL DEFAULT ''",
    "query_locale": "TEXT NOT NULL DEFAULT ''",
    "product_family": "TEXT NOT NULL DEFAULT ''",
```

Extend `list_leads()` to accept an optional run filter:

```python
def list_leads(
    db: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int | None = 100,
    offset: int = 0,
    campaign_run_id: int | None = None,
) -> list[dict]:
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if campaign_run_id is not None:
        clauses.append("campaign_run_id = ?")
        params.append(int(campaign_run_id))
    sql = "SELECT * FROM leads"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Use structured query specs in the campaign loop**

Modify `leadfinder/campaigns.py` imports:

```python
import json

from .query_catalog import build_query_specs
```

Replace the current query loop:

```python
                queries = build_queries(country, effective_product)
                query_limit = max(4, min(8, int(options.per_market_limit)))
                for query in queries[:query_limit]:
```

with:

```python
                query_specs = build_query_specs(country, options.hs_code, effective_product)
                query_limit = max(1, int(options.per_market_limit))
                for spec in query_specs[:query_limit]:
                    query = spec["query"]
```

Replace the Serper provider event with structured JSON text:

```python
                        record_provider_event(
                            db,
                            run_id,
                            provider="Serper",
                            event_type="search",
                            status="ok",
                            cost_units=1,
                            message=json.dumps(
                                {
                                    "country": spec["country"],
                                    "locale": spec["locale"],
                                    "product_family": spec["product_family"],
                                    "query": query,
                                },
                                ensure_ascii=False,
                            ),
                        )
```

Before calling `_crawl_score_and_classify()`, add the query metadata to the scored lead:

```python
                        scored = {
                            **lead,
                            **score_lead(lead),
                            "campaign_run_id": run_id,
                            "discovery_query": query,
                            "query_locale": spec["locale"],
                            "product_family": spec["product_family"],
                        }
```

Leave all Stage A skip gates unchanged.

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_campaigns -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add leadfinder/db.py leadfinder/campaigns.py tests/test_campaigns.py
git commit -m "Persist recall metadata for campaign runs"
```

Expected:

```text
[main <hash>] Persist recall metadata for campaign runs
```

---

### Task 3: Add Recall Reporting for CLI and Browser Consumers

**Files:**
- Create: `leadfinder/recall.py`
- Modify: `cli.py`
- Test: `tests/test_recall.py`

- [ ] **Step 1: Write the failing recall-report tests**

Create `tests/test_recall.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from leadfinder.db import connect, create_campaign_run, create_or_skip_lead, finish_campaign_run, record_provider_event
from leadfinder.recall import recall_report


class RecallReportTests(unittest.TestCase):
    def test_recall_report_groups_by_country_locale_and_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run = create_campaign_run(db, {"name": "HS7019 recall", "hs_code": "7019"})
                record_provider_event(
                    db,
                    run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message=json.dumps(
                        {
                            "country": "Germany",
                            "locale": "de-DE",
                            "product_family": "roving",
                            "query": 'site:.de "glasfaser roving" "pultrusion"',
                        },
                        ensure_ascii=False,
                    ),
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Example Buyer",
                        "country_region": "Germany",
                        "website": "https://buyer.example",
                        "status": "Qualified",
                        "email": "sales@buyer.example",
                        "email_verification_status": "valid",
                        "campaign_run_id": run["id"],
                        "query_locale": "de-DE",
                        "product_family": "roving",
                        "discovery_query": 'site:.de "glasfaser roving" "pultrusion"',
                    },
                )
                finish_campaign_run(
                    db,
                    run["id"],
                    status="Completed",
                    created=1,
                    skipped=0,
                    errors=0,
                    quality_after={"total": 1},
                )
                report = recall_report(db, run["id"])
            finally:
                db.close()

        self.assertEqual(report["run"]["id"], run["id"])
        self.assertEqual(len(report["rows"]), 1)
        row = report["rows"][0]
        self.assertEqual(row["country"], "Germany")
        self.assertEqual(row["locale"], "de-DE")
        self.assertEqual(row["product_family"], "roving")
        self.assertEqual(row["serper_queries"], 1)
        self.assertEqual(row["leads_created"], 1)
        self.assertEqual(row["qualified_count"], 1)
        self.assertEqual(row["valid_email_count"], 1)
        self.assertEqual(row["qualified_per_query"], 1.0)

    def test_recall_report_uses_latest_run_when_run_id_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                first = create_campaign_run(db, {"name": "older"})
                finish_campaign_run(db, first["id"], status="Completed", created=0, skipped=0, errors=0, quality_after={})
                second = create_campaign_run(db, {"name": "newer"})
                finish_campaign_run(db, second["id"], status="Completed", created=0, skipped=0, errors=0, quality_after={})
                report = recall_report(db)
            finally:
                db.close()

        self.assertEqual(report["run"]["id"], second["id"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_recall -v
```

Expected:

```text
ModuleNotFoundError: No module named 'leadfinder.recall'
```

- [ ] **Step 3: Implement the recall summary helper**

Create `leadfinder/recall.py`:

```python
from __future__ import annotations

import json

from .db import list_campaign_runs, list_leads, list_provider_events


def recall_report(db, run_id: int | None = None) -> dict:
    runs = list_campaign_runs(db, limit=20)
    if not runs:
        return {"run": None, "rows": []}
    run = next((item for item in runs if item["id"] == int(run_id)), runs[0]) if run_id is not None else runs[0]
    events = list_provider_events(db, run["id"])
    leads = list_leads(db, limit=None, campaign_run_id=run["id"])
    grouped: dict[tuple[str, str, str], dict] = {}

    for event in events:
        if event["provider"] != "Serper" or event["event_type"] != "search" or event["status"] != "ok":
            continue
        try:
            payload = json.loads(event["message"])
        except json.JSONDecodeError:
            continue
        key = (
            str(payload.get("country", "") or ""),
            str(payload.get("locale", "") or ""),
            str(payload.get("product_family", "") or ""),
        )
        row = grouped.setdefault(
            key,
            {
                "country": key[0],
                "locale": key[1],
                "product_family": key[2],
                "search_terms": [],
                "serper_queries": 0,
                "leads_created": 0,
                "qualified_count": 0,
                "rejected_count": 0,
                "valid_email_count": 0,
                "qualified_per_query": 0.0,
            },
        )
        row["serper_queries"] += 1
        query = str(payload.get("query", "") or "").strip()
        if query and query not in row["search_terms"]:
            row["search_terms"].append(query)

    for lead in leads:
        key = (
            str(lead.get("country_region", "") or ""),
            str(lead.get("query_locale", "") or ""),
            str(lead.get("product_family", "") or ""),
        )
        row = grouped.setdefault(
            key,
            {
                "country": key[0],
                "locale": key[1],
                "product_family": key[2],
                "search_terms": [],
                "serper_queries": 0,
                "leads_created": 0,
                "qualified_count": 0,
                "rejected_count": 0,
                "valid_email_count": 0,
                "qualified_per_query": 0.0,
            },
        )
        row["leads_created"] += 1
        if lead.get("status") == "Qualified":
            row["qualified_count"] += 1
        if lead.get("status") == "Rejected":
            row["rejected_count"] += 1
        if str(lead.get("email_verification_status", "") or "").lower() == "valid":
            row["valid_email_count"] += 1

    rows = sorted(grouped.values(), key=lambda item: (-item["qualified_count"], item["country"], item["product_family"]))
    for row in rows:
        queries = max(1, int(row["serper_queries"]))
        row["qualified_per_query"] = round(float(row["qualified_count"]) / queries, 3)
    return {"run": run, "rows": rows}
```

- [ ] **Step 4: Expose the report in the CLI**

Modify `cli.py` imports:

```python
from leadfinder.recall import recall_report
```

Add the command handler:

```python
def cmd_recall_report(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        report = recall_report(db, args.run_id)
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
```

Add the parser entry inside `build_parser()`:

```python
    recall_parser = sub.add_parser("recall-report", help="Show Stage B recall productivity by country and search family.")
    recall_parser.add_argument("--run-id", type=int, default=None)
    recall_parser.set_defaults(func=cmd_recall_report)
```

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_recall -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add leadfinder/recall.py cli.py tests/test_recall.py
git commit -m "Add recall productivity reporting"
```

Expected:

```text
[main <hash>] Add recall productivity reporting
```

---

### Task 4: Add Stage B Controls and Recall Report to the Workbench

**Files:**
- Modify: `leadfinder/webapp.py`
- Modify: `README.md`
- Modify: `tests/test_webapp.py`

- [ ] **Step 1: Write the failing webapp tests**

Add these tests to `tests/test_webapp.py`:

```python
    def test_homepage_includes_stage_b_product_family_options(self) -> None:
        app = make_app(self.db_path)
        status, headers, body = app.handle("GET", "/", b"")
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn('option value="roving"', html)
        self.assertIn('option value="woven_fabric"', html)
        self.assertIn('option value="mat"', html)
        self.assertIn("召回质量报告", html)

    def test_api_recall_report_returns_rows(self) -> None:
        db = connect(self.db_path)
        try:
            run = create_campaign_run(db, {"name": "HS7019 recall", "hs_code": "7019"})
            record_provider_event(
                db,
                run["id"],
                provider="Serper",
                event_type="search",
                status="ok",
                cost_units=1,
                message='{"country":"Germany","locale":"de-DE","product_family":"roving","query":"demo"}',
            )
            create_or_skip_lead(
                db,
                {
                    "company_name": "Example Buyer",
                    "country_region": "Germany",
                    "website": "https://buyer.example",
                    "status": "Qualified",
                    "campaign_run_id": run["id"],
                    "query_locale": "de-DE",
                    "product_family": "roving",
                },
            )
            finish_campaign_run(db, run["id"], status="Completed", created=1, skipped=0, errors=0, quality_after={"total": 1})
        finally:
            db.close()

        app = make_app(self.db_path)
        status, headers, body = app.handle("GET", f"/api/recall-report?run_id={run['id']}", b"")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["rows"][0]["country"], "Germany")
        self.assertEqual(payload["rows"][0]["qualified_count"], 1)
```

If needed, extend imports in `tests/test_webapp.py`:

```python
from leadfinder.db import connect, create_campaign_run, create_or_skip_lead, finish_campaign_run, record_provider_event
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_webapp -v
```

Expected:

```text
FAIL: test_homepage_includes_stage_b_product_family_options
```

or:

```text
AssertionError: 404 != 200
```

for the missing recall API route.

- [ ] **Step 3: Add the recall API endpoint**

Modify `leadfinder/webapp.py` imports:

```python
from .query_catalog import PRODUCT_FAMILY_LABELS
from .recall import recall_report
```

Add this route before the default 404 branch:

```python
        if method == "GET" and parsed.path == "/api/recall-report":
            query = parse_qs(parsed.query, keep_blank_values=True)
            run_id_text = query.get("run_id", [""])[0]
            run_id = int(run_id_text) if run_id_text else None
            db = connect(self.db_path)
            try:
                payload = recall_report(db, run_id)
            finally:
                db.close()
            return self.json_response(payload)
```

- [ ] **Step 4: Expand the campaign UI**

Replace the current product selector options inside `INDEX_HTML`:

```html
            <option value="all">全部产品族</option>
            <option value="roving">粗纱 / Roving</option>
            <option value="yarn">纱线 / Yarn</option>
            <option value="woven_fabric">织物 / Woven Fabric</option>
            <option value="mat">毡 / Mat</option>
            <option value="mesh">网格布 / Mesh</option>
            <option value="chopped_strand">短切原丝 / Chopped Strand</option>
            <option value="tissue">薄毡 / Tissue</option>
            <option value="insulation_fabric">绝缘布 / Insulation Fabric</option>
```

Add this section after the API usage section:

```html
    <section class="campaign" aria-label="召回质量报告">
      <h2 style="margin:0 0 10px;font-size:16px;">召回质量报告</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>国家</th>
              <th>语言/地区</th>
              <th>产品族</th>
              <th>搜索词</th>
              <th>Serper</th>
              <th>创建</th>
              <th>Qualified</th>
              <th>Rejected</th>
              <th>有效邮箱</th>
              <th>Qualified/Query</th>
            </tr>
          </thead>
          <tbody id="recall-report"><tr><td class="empty" colspan="10">暂无召回报表。</td></tr></tbody>
        </table>
      </div>
    </section>
```

Add the JavaScript loader:

```javascript
    async function loadRecallReport(runId = '') {
      const params = new URLSearchParams();
      if (runId) params.set('run_id', String(runId));
      const url = params.size ? `/api/recall-report?${params.toString()}` : '/api/recall-report';
      const response = await fetch(url);
      const payload = await response.json();
      const rows = payload.rows || [];
      const tbody = document.getElementById('recall-report');
      if (!rows.length) {
        tbody.innerHTML = '<tr><td class="empty" colspan="10">暂无召回报表。</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map((row) => `
        <tr>
          <td>${esc(row.country)}</td>
          <td>${esc(row.locale)}</td>
          <td>${esc(row.product_family)}</td>
          <td class="reason">${esc((row.search_terms || []).join(' | '))}</td>
          <td>${row.serper_queries || 0}</td>
          <td>${row.leads_created || 0}</td>
          <td>${row.qualified_count || 0}</td>
          <td>${row.rejected_count || 0}</td>
          <td>${row.valid_email_count || 0}</td>
          <td>${row.qualified_per_query || 0}</td>
        </tr>
      `).join('');
    }
```

Call it on load and after campaigns:

```javascript
      await loadRecallReport(payload.run_id || '');
```

and:

```javascript
    loadRecallReport();
```

- [ ] **Step 5: Update the README for Stage B**

Add this section after `## Campaign workflow`:

```markdown
## Recall workflow

- Use HS codes plus product-family selection to narrow discovery before spending Serper queries.
- Region and country selection still control target markets, but Stage B now tracks productivity per country instead of only total leads.
- Use `python cli.py recall-report` or the workbench recall table to compare which locales and product families produce Qualified buyers and valid emails.
- The success metric is Qualified leads per Serper query, not raw lead volume.
```

Update the example campaign command:

```markdown
python cli.py campaign --hs 701912 --year 2024 --product roving --country Germany --country France --per-market-limit 3
python cli.py recall-report
```

- [ ] **Step 6: Run focused tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_webapp -v
```

Expected:

```text
OK
```

- [ ] **Step 7: Run the full test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected:

```text
OK
```

The exact test count will be higher than Stage A because of the new Stage B test files.

- [ ] **Step 8: Run whitespace and status checks**

Run:

```powershell
git diff --check
git status --short --ignored
```

Expected for `git diff --check`:

```text
```

Expected for `git status --short --ignored`:

```text
 M README.md
!! .codegraph/
!! .env
!! __pycache__/
!! data/
!! exports/
```

Other tracked file modifications should already have been committed in earlier tasks.

- [ ] **Step 9: Commit Task 4**

Run:

```powershell
git add leadfinder/webapp.py README.md tests/test_webapp.py
git commit -m "Add Stage B recall reporting workbench"
```

Expected:

```text
[main <hash>] Add Stage B recall reporting workbench
```

- [ ] **Step 10: Push the completed Stage B branch state**

Run:

```powershell
git push
git status --short --branch
```

Expected:

```text
## main...origin/main
```

or the current feature branch name tracking its remote with no additional tracked changes.

---

## Self-Review

### Spec Coverage

- Localized search terms are covered by Task 1.
- HS product families and HS-to-family selection are covered by Task 1 and Task 4.
- Region-to-country batch behavior is preserved and made measurable in Task 2.
- Recall quality reporting is implemented in Task 3 and surfaced in Task 4.
- Stage A classification and enrichment gates remain in place because Task 2 modifies only query planning and metadata persistence, not the existing evidence gate logic.
- Tests cover localized terms, family mapping, per-country budgets, and recall reporting.

### Placeholder Scan

This plan avoids placeholders such as "add validation later" or "write tests for the above." Every task names exact files, concrete tests, concrete commands, and the minimal code shape needed to implement the stage.

### Type Consistency

- `product_families_for_hs()` and `build_query_specs()` are introduced in Task 1 before campaign code consumes them in Task 2.
- `campaign_run_id`, `discovery_query`, `query_locale`, and `product_family` are added in Task 2 before recall reporting uses them in Task 3 and Task 4.
- `recall_report()` is introduced in Task 3 before the webapp API route and table use it in Task 4.
- `product` remains the external option name in CLI and campaign requests, but it now accepts Stage B family slugs and `"all"` for compatibility with the current request payload shape.
