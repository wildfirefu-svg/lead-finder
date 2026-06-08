# Private Lead System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add measurable lead-quality reporting, make source costs explicit, add CSV/manual source aggregation for bill-of-lading platforms and SaaS enrichment results, then add a local private web workbench for reviewing and managing leads.

**Architecture:** Phase 1 keeps the existing Python CLI and SQLite database, first adding quality and provider-cost reports so improvements and spending can be measured, then adding a focused CSV import layer that normalizes external lead rows into the current `leads` table. Phase 2 adds a local stdlib HTTP workbench that reads and updates the same SQLite database without adding package dependencies. Phase 3 adds optional paid API connectors only after quality reporting proves they are worth the spend.

**Tech Stack:** Python standard library, SQLite, `argparse`, `unittest`, `http.server`, vanilla HTML/CSS/JS.

---

## Scope And Order

Build this in three separate releases:

1. **Release A: source aggregation and quality controls**
   Establish lead-quality and provider-cost reports, then import leads from external CSV/manual files produced by 外贸邦, 易之家, Apollo.io, Snov.io, or spreadsheets. Preserve source evidence in `source_name`, `notes`, and `raw_text`; dedupe through the existing database rules; improve scoring for real buyer signals.

2. **Release B: private local workbench**
   Add a local browser UI for filtering, reviewing, updating status, and exporting leads from the same database. Do not add cloud sync, email sending, paid enrichment, or CRM database writes in this release.

3. **Release C: optional paid API connectors**
   Treat Serper, Apollo.io, Snov.io, and Bright Data as optional paid or free-credit providers. Use official APIs first. Use Bright Data only for public web pages that do not require login, do not sit behind paywalls, and are allowed by the target site's terms.

The current workspace is not a git repository. Each task includes a version-control checkpoint. If execution happens after `git init`, commit at the checkpoint; otherwise run `git status` and record the expected `fatal: not a git repository` result.

## Provider Cost Policy

- **Public/free core:** UN Comtrade, local SQLite, manual CSV import, and exported CRM CSV.
- **Free-credit or paid search:** Serper. It has a free trial allowance, but continued usage requires credits.
- **Free-credit or paid contact enrichment:** Apollo.io and Snov.io. Prefer official API or exported CSV; do not scrape logged-in SaaS dashboards.
- **Paid public web collection:** Bright Data. Use only for public web pages and only after Release A quality metrics show where paid collection is needed.
- **Quality gate:** paid providers are justified only if they increase `high_quality` or `high_quality_rate` compared with the pre-provider baseline.

## File Structure

### Create

- `leadfinder/importers.py`
  Normalizes CSV rows from external lead sources into the existing lead dictionary shape.

- `leadfinder/quality.py`
  Computes measurable lead-quality metrics from existing lead rows.

- `leadfinder/providers.py`
  Classifies sources by cost model, allowed use, and whether they are paid/API-backed.

- `leadfinder/webapp.py`
  Local HTTP server, API endpoints, and static HTML response for the private workbench.

- `tests/test_importers.py`
  Unit tests for CSV import normalization, source metadata, and dedupe integration.

- `tests/test_quality.py`
  Unit tests for quality metrics and the CLI quality report.

- `tests/test_providers.py`
  Unit tests for provider cost classification and the CLI provider report.

- `tests/test_webapp.py`
  Unit tests for workbench JSON endpoints and status updates.

### Modify

- `cli.py`
  Add `quality-report`, `provider-report`, and `import-csv` for Release A and `serve` for Release B.

- `leadfinder/scoring.py`
  Add buyer-source and contact-source signals while keeping the existing keyword model.

- `leadfinder/db.py`
  Add focused list/update helpers only if the web workbench needs them. Keep the table schema compatible with existing `data/leadfinder.sqlite`.

- `README.md`
  Document the new zero-cost workflow and the correct unittest discovery command.

---

## Release A: Source Aggregation

### Task 1: Lead Quality Baseline Report

**Files:**
- Create: `leadfinder/quality.py`
- Modify: `cli.py`
- Test: `tests/test_quality.py`

- [ ] **Step 1: Write failing tests for quality metrics**

Create `tests/test_quality.py` with:

```python
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from cli import main
from leadfinder.db import connect, create_or_skip_lead
from leadfinder.quality import quality_report


class QualityReportTests(unittest.TestCase):
    def test_quality_report_counts_high_quality_leads(self) -> None:
        report = quality_report(
            [
                {
                    "source_type": "Website",
                    "match_score": 42,
                    "email": "",
                    "website": "https://weak.example",
                    "company_name": "Weak Search Result",
                },
                {
                    "source_type": "Bill of Lading",
                    "match_score": 76,
                    "email": "",
                    "website": "https://buyer.example",
                    "company_name": "Real Buyer",
                },
                {
                    "source_type": "SaaS Contact",
                    "match_score": 68,
                    "email": "sales@example.com",
                    "website": "https://contact.example",
                    "company_name": "Contact Buyer",
                },
            ],
            min_score=50,
        )

        self.assertEqual(report["total"], 3)
        self.assertEqual(report["high_score"], 2)
        self.assertEqual(report["with_email"], 1)
        self.assertEqual(report["with_buyer_evidence"], 1)
        self.assertEqual(report["high_quality"], 2)
        self.assertEqual(report["high_quality_rate"], 0.667)

    def test_cli_quality_report_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Bill of Lading",
                        "company_name": "Example Buyer",
                        "website": "https://example.com",
                        "match_score": 80,
                    },
                )
            finally:
                db.close()

            original_db = os.environ.get("LEADFINDER_DB_PATH")
            os.environ["LEADFINDER_DB_PATH"] = str(db_path)
            try:
                exit_code = main(["quality-report", "--min-score", "50"])
            finally:
                if original_db is None:
                    os.environ.pop("LEADFINDER_DB_PATH", None)
                else:
                    os.environ["LEADFINDER_DB_PATH"] = original_db

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run quality tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_quality
```

Expected: fail with `ModuleNotFoundError: No module named 'leadfinder.quality'`.

- [ ] **Step 3: Implement `leadfinder/quality.py`**

Create `leadfinder/quality.py`:

```python
from __future__ import annotations


BUYER_EVIDENCE_TYPES = {"bill of lading"}
CONTACT_EVIDENCE_TYPES = {"saas contact"}


def quality_report(leads: list[dict], min_score: int = 50) -> dict:
    total = len(leads)
    high_score = 0
    with_email = 0
    with_website = 0
    with_buyer_evidence = 0
    with_contact_evidence = 0
    high_quality = 0

    for lead in leads:
        score = int(lead.get("match_score") or 0)
        source_type = str(lead.get("source_type", "") or "").strip().lower()
        has_email = bool(str(lead.get("email", "") or "").strip())
        has_website = bool(str(lead.get("website", "") or "").strip())
        has_buyer_evidence = source_type in BUYER_EVIDENCE_TYPES
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
```

- [ ] **Step 4: Add `quality-report` CLI command**

Modify `cli.py`.

Add import:

```python
from leadfinder.quality import quality_report
```

Add command handler:

```python
def cmd_quality_report(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        leads = list_leads(db, limit=args.limit)
        report = quality_report(leads, min_score=args.min_score)
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
```

Add parser block before `stats_parser`:

```python
    quality_parser = sub.add_parser("quality-report", help="Show measurable lead-quality metrics.")
    quality_parser.add_argument("--min-score", type=int, default=50)
    quality_parser.add_argument("--limit", type=int, default=None)
    quality_parser.set_defaults(func=cmd_quality_report)
```

- [ ] **Step 5: Run quality tests and all tests**

Run:

```powershell
python -m unittest tests.test_quality
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

- [ ] **Step 6: Record baseline quality before source imports**

Run:

```powershell
python cli.py quality-report --min-score 50
```

Expected on the current empty database: JSON with `"total": 0` and `"high_quality_rate": 0`. On a populated database, save the printed values as the baseline before importing bill-of-lading or SaaS contact rows.

- [ ] **Step 7: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add cli.py leadfinder/quality.py tests/test_quality.py
git commit -m "feat: add lead quality baseline report"
```

### Task 2: Provider Cost Classification Report

**Files:**
- Create: `leadfinder/providers.py`
- Modify: `cli.py`
- Test: `tests/test_providers.py`

- [ ] **Step 1: Write failing tests for provider classification**

Create `tests/test_providers.py` with:

```python
from __future__ import annotations

import json
import unittest

from cli import main
from leadfinder.providers import provider_report, provider_summary


class ProviderReportTests(unittest.TestCase):
    def test_provider_summary_classifies_serper_as_free_credit_or_paid(self) -> None:
        summary = provider_summary("Serper")

        self.assertEqual(summary["provider"], "Serper")
        self.assertEqual(summary["cost_model"], "free_credit_or_paid")
        self.assertTrue(summary["api_backed"])
        self.assertFalse(summary["zero_cost_core"])
        self.assertIn("credits", summary["notes"].lower())

    def test_provider_summary_classifies_bright_data_as_paid_public_web_only(self) -> None:
        summary = provider_summary("Bright Data")

        self.assertEqual(summary["provider"], "Bright Data")
        self.assertEqual(summary["cost_model"], "paid")
        self.assertTrue(summary["api_backed"])
        self.assertFalse(summary["zero_cost_core"])
        self.assertIn("public web", summary["allowed_use"].lower())

    def test_provider_report_contains_free_and_paid_sources(self) -> None:
        report = provider_report()
        providers = {item["provider"]: item for item in report["providers"]}

        self.assertTrue(providers["UN Comtrade"]["zero_cost_core"])
        self.assertFalse(providers["Serper"]["zero_cost_core"])
        self.assertFalse(providers["Apollo.io"]["zero_cost_core"])
        self.assertFalse(providers["Snov.io"]["zero_cost_core"])
        self.assertFalse(providers["Bright Data"]["zero_cost_core"])

    def test_cli_provider_report_returns_zero(self) -> None:
        exit_code = main(["provider-report"])

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run provider tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_providers
```

Expected: fail with `ModuleNotFoundError: No module named 'leadfinder.providers'`.

- [ ] **Step 3: Implement `leadfinder/providers.py`**

Create `leadfinder/providers.py`:

```python
from __future__ import annotations


PROVIDERS = {
    "UN Comtrade": {
        "provider": "UN Comtrade",
        "category": "market_data",
        "cost_model": "public_free",
        "api_backed": True,
        "zero_cost_core": True,
        "allowed_use": "Public trade data for target-market selection.",
        "notes": "Use for HS 7019 country prioritization before lead discovery.",
    },
    "Manual CSV": {
        "provider": "Manual CSV",
        "category": "manual_import",
        "cost_model": "public_free",
        "api_backed": False,
        "zero_cost_core": True,
        "allowed_use": "Manual spreadsheet import from user-controlled files.",
        "notes": "Core workflow must work with manual CSV alone.",
    },
    "外贸邦": {
        "provider": "外贸邦",
        "category": "bill_of_lading",
        "cost_model": "manual_or_platform_plan",
        "api_backed": False,
        "zero_cost_core": False,
        "allowed_use": "Manual import of platform-exported or user-copied public bill-of-lading clues.",
        "notes": "Do not scrape logged-in pages unless the account terms explicitly allow it.",
    },
    "易之家": {
        "provider": "易之家",
        "category": "bill_of_lading",
        "cost_model": "manual_or_platform_plan",
        "api_backed": False,
        "zero_cost_core": False,
        "allowed_use": "Manual import of platform-exported or user-copied public bill-of-lading clues.",
        "notes": "Do not scrape logged-in pages unless the account terms explicitly allow it.",
    },
    "Serper": {
        "provider": "Serper",
        "category": "search",
        "cost_model": "free_credit_or_paid",
        "api_backed": True,
        "zero_cost_core": False,
        "allowed_use": "Google SERP API for public web search discovery.",
        "notes": "Has free trial queries; continued use requires paid credits.",
    },
    "Apollo.io": {
        "provider": "Apollo.io",
        "category": "contact_enrichment",
        "cost_model": "free_credit_or_paid",
        "api_backed": True,
        "zero_cost_core": False,
        "allowed_use": "Official API or exported CSV for internal contact enrichment.",
        "notes": "Do not scrape the logged-in SaaS dashboard.",
    },
    "Snov.io": {
        "provider": "Snov.io",
        "category": "contact_enrichment",
        "cost_model": "free_credit_or_paid",
        "api_backed": True,
        "zero_cost_core": False,
        "allowed_use": "Official API or exported CSV for email finding and verification.",
        "notes": "Do not scrape the logged-in SaaS dashboard.",
    },
    "Bright Data": {
        "provider": "Bright Data",
        "category": "public_web_collection",
        "cost_model": "paid",
        "api_backed": True,
        "zero_cost_core": False,
        "allowed_use": "Paid collection for public web pages only.",
        "notes": "Do not use for logged-in pages, paywalled data, or bypassing account restrictions.",
    },
}


ALIASES = {
    "serper.dev": "Serper",
    "serper": "Serper",
    "apollo": "Apollo.io",
    "apollo.io": "Apollo.io",
    "snov": "Snov.io",
    "snov.io": "Snov.io",
    "brightdata": "Bright Data",
    "bright data": "Bright Data",
    "comtrade": "UN Comtrade",
    "un comtrade": "UN Comtrade",
    "waitubang": "外贸邦",
    "yizhijia": "易之家",
}


def provider_summary(name: str) -> dict:
    key = ALIASES.get(str(name or "").strip().lower(), str(name or "").strip())
    return dict(PROVIDERS.get(key, PROVIDERS["Manual CSV"]))


def provider_report() -> dict:
    providers = sorted(PROVIDERS.values(), key=lambda item: (not item["zero_cost_core"], item["provider"]))
    return {"providers": [dict(item) for item in providers]}
```

- [ ] **Step 4: Add `provider-report` CLI command**

Modify `cli.py`.

Add import:

```python
from leadfinder.providers import provider_report
```

Add command handler:

```python
def cmd_provider_report(_: argparse.Namespace) -> int:
    print(json.dumps(provider_report(), ensure_ascii=False, indent=2))
    return 0
```

Add parser block before `stats_parser`:

```python
    provider_parser = sub.add_parser("provider-report", help="Show source provider cost and allowed-use classification.")
    provider_parser.set_defaults(func=cmd_provider_report)
```

- [ ] **Step 5: Run provider tests and all tests**

Run:

```powershell
python -m unittest tests.test_providers
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

- [ ] **Step 6: Record provider cost assumptions**

Run:

```powershell
python cli.py provider-report
```

Expected: JSON classifies `UN Comtrade` and `Manual CSV` as `zero_cost_core: true`, while `Serper`, `Apollo.io`, `Snov.io`, and `Bright Data` are `zero_cost_core: false`.

- [ ] **Step 7: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add cli.py leadfinder/providers.py tests/test_providers.py
git commit -m "feat: classify source provider costs"
```

### Task 3: CSV Import Normalizer

**Files:**
- Create: `leadfinder/importers.py`
- Test: `tests/test_importers.py`

- [ ] **Step 1: Write failing tests for normalized external rows**

Create `tests/test_importers.py` with:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from leadfinder.db import connect, list_leads
from leadfinder.importers import import_csv, normalize_source_row


class ImporterTests(unittest.TestCase):
    def test_bill_of_lading_row_maps_to_existing_lead_fields(self) -> None:
        row = {
            "Importer": "Example Composites LLC",
            "Country": "USA",
            "Website": "example.com",
            "Product": "HS 7019 fiberglass woven roving shipment",
            "Shipment Summary": "Consignee imported fiberglass fabric from China.",
        }

        lead = normalize_source_row(row, source="外贸邦")

        self.assertEqual(lead["source_type"], "Bill of Lading")
        self.assertEqual(lead["source_name"], "外贸邦")
        self.assertEqual(lead["company_name"], "Example Composites LLC")
        self.assertEqual(lead["country_region"], "USA")
        self.assertEqual(lead["market_region"], "USA")
        self.assertEqual(lead["website"], "https://example.com")
        self.assertIn("HS 7019", lead["raw_text"])
        self.assertIn("Source: 外贸邦", lead["notes"])

    def test_saas_contact_row_preserves_email_and_contact_source(self) -> None:
        row = {
            "Company": "Fabric Buyer GmbH",
            "Country": "Germany",
            "Email": "Sales@Buyer.Example",
            "Contact Name": "Maria Schmidt",
            "Industry": "Composite distributor",
        }

        lead = normalize_source_row(row, source="Snov.io")

        self.assertEqual(lead["source_type"], "SaaS Contact")
        self.assertEqual(lead["source_name"], "Snov.io")
        self.assertEqual(lead["email"], "sales@buyer.example")
        self.assertEqual(lead["contact_name"], "Maria Schmidt")
        self.assertIn("Contact source: Snov.io", lead["notes"])

    def test_import_csv_inserts_and_dedupes_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "leads.csv"
            csv_path.write_text(
                "Company,Country,Website,Email,Product\n"
                "Example Composites,USA,example.com,sales@example.com,fiberglass roving\n"
                "Example Composites,USA,https://www.example.com/contact,,fiberglass fabric\n",
                encoding="utf-8",
            )
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = import_csv(db, csv_path, source="Apollo.io")
                rows = list_leads(db)
            finally:
                db.close()

        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_name"], "Apollo.io")
        self.assertGreater(rows[0]["match_score"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new importer tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_importers
```

Expected: fail with `ModuleNotFoundError: No module named 'leadfinder.importers'`.

- [ ] **Step 3: Implement `leadfinder/importers.py`**

Create `leadfinder/importers.py`:

```python
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .db import create_or_skip_lead
from .enrich import normalize_url
from .scoring import score_lead


BILL_OF_LADING_SOURCES = {"外贸邦", "易之家", "waitubang", "yizhijia", "bill_of_lading"}
SAAS_CONTACT_SOURCES = {"apollo.io", "apollo", "snov.io", "snov"}

ALIASES = {
    "company_name": ["company_name", "company", "company name", "importer", "buyer", "consignee", "organization", "account"],
    "country_region": ["country_region", "country", "region", "market", "destination country"],
    "market_region": ["market_region", "market", "country", "region", "destination country"],
    "website": ["website", "domain", "company website", "url", "site"],
    "source_url": ["source_url", "source url", "url", "profile url", "apollo url", "snov url"],
    "contact_name": ["contact_name", "contact name", "name", "person", "decision maker"],
    "email": ["email", "email address", "work email", "business email"],
    "industry": ["industry", "category", "business type"],
    "raw_text": ["raw_text", "description", "product", "shipment summary", "bill summary", "notes", "hs code"],
}


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped: int


def _clean_key(value: str) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _lookup(row: dict[str, str], field: str) -> str:
    cleaned = {_clean_key(key): str(value or "").strip() for key, value in row.items()}
    for alias in ALIASES[field]:
        value = cleaned.get(_clean_key(alias), "")
        if value:
            return value
    return ""


def _source_type(source: str) -> str:
    key = source.strip().lower()
    if key in BILL_OF_LADING_SOURCES:
        return "Bill of Lading"
    if key in SAAS_CONTACT_SOURCES:
        return "SaaS Contact"
    return "Manual CSV"


def normalize_source_row(row: dict[str, str], source: str) -> dict:
    country = _lookup(row, "country_region")
    website = _lookup(row, "website")
    source_url = _lookup(row, "source_url") or website
    raw_parts = [
        _lookup(row, "raw_text"),
        _lookup(row, "industry"),
        _lookup(row, "company_name"),
    ]
    raw_text = " ".join(part for part in raw_parts if part).strip()
    notes = [f"Source: {source}"]
    if _source_type(source) == "SaaS Contact":
        notes.append(f"Contact source: {source}")
    if _source_type(source) == "Bill of Lading":
        notes.append("Evidence: public bill-of-lading/import record")

    return {
        "source_type": _source_type(source),
        "source_name": source,
        "company_name": _lookup(row, "company_name"),
        "country_region": country,
        "market_region": _lookup(row, "market_region") or country,
        "website": normalize_url(website) if website else "",
        "source_url": normalize_url(source_url) if source_url else "",
        "contact_name": _lookup(row, "contact_name"),
        "email": _lookup(row, "email").lower(),
        "industry": _lookup(row, "industry"),
        "product_fit": "Both",
        "fit_reason": "",
        "match_score": 0,
        "status": "Discovered",
        "notes": "\n".join(notes),
        "raw_text": raw_text,
    }


def import_csv(db, input_path: str | Path, source: str) -> ImportResult:
    created = 0
    skipped = 0
    with Path(input_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            lead = normalize_source_row(row, source=source)
            scored = {**lead, **score_lead(lead)}
            _, was_created = create_or_skip_lead(db, scored)
            created += int(was_created)
            skipped += int(not was_created)
    return ImportResult(created=created, skipped=skipped)
```

- [ ] **Step 4: Run importer tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_importers
```

Expected: `OK`.

- [ ] **Step 5: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add leadfinder/importers.py tests/test_importers.py
git commit -m "feat: import external lead CSV sources"
```

### Task 4: CLI Command For External CSV Sources

**Files:**
- Modify: `cli.py`
- Test: `tests/test_importers.py`

- [ ] **Step 1: Add failing CLI test**

Append to `ImporterTests` in `tests/test_importers.py`:

```python
    def test_cli_import_csv_command_reports_created_and_skipped(self) -> None:
        from cli import main

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "apollo.csv"
            db_path = Path(tmp) / "leadfinder.sqlite"
            csv_path.write_text(
                "Company,Country,Website,Email,Product\n"
                "Example Composites,USA,example.com,sales@example.com,fiberglass roving\n",
                encoding="utf-8",
            )
            original_env = __import__("os").environ.get("LEADFINDER_DB_PATH")
            __import__("os").environ["LEADFINDER_DB_PATH"] = str(db_path)
            try:
                exit_code = main(["import-csv", "--input", str(csv_path), "--source", "Apollo.io"])
            finally:
                if original_env is None:
                    __import__("os").environ.pop("LEADFINDER_DB_PATH", None)
                else:
                    __import__("os").environ["LEADFINDER_DB_PATH"] = original_env

        self.assertEqual(exit_code, 0)
```

- [ ] **Step 2: Run the CLI test and verify it fails**

Run:

```powershell
python -m unittest tests.test_importers.ImporterTests.test_cli_import_csv_command_reports_created_and_skipped
```

Expected: fail because `import-csv` is not a recognized subcommand.

- [ ] **Step 3: Add CLI command**

Modify `cli.py`:

```python
from leadfinder.importers import import_csv
```

Add this function near the other command handlers:

```python
def cmd_import_csv(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        result = import_csv(db, args.input, source=args.source)
    finally:
        db.close()
    print(f"Imported CSV source={args.source}. created={result.created}, skipped={result.skipped}")
    return 0
```

Add this parser block inside `build_parser()` before `enrich`:

```python
    import_csv_parser = sub.add_parser("import-csv", help="Import leads from external CSV sources such as bill-of-lading platforms, Apollo, or Snov.")
    import_csv_parser.add_argument("--input", required=True, type=lambda value: __import__("pathlib").Path(value))
    import_csv_parser.add_argument("--source", required=True)
    import_csv_parser.set_defaults(func=cmd_import_csv)
```

- [ ] **Step 4: Run CLI test and all tests**

Run:

```powershell
python -m unittest tests.test_importers.ImporterTests.test_cli_import_csv_command_reports_created_and_skipped
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

- [ ] **Step 5: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add cli.py tests/test_importers.py
git commit -m "feat: add external CSV import command"
```

### Task 5: Improve Lead Scoring For Real Buyer Signals

**Files:**
- Modify: `leadfinder/scoring.py`
- Test: `tests/test_leadfinder.py`

- [ ] **Step 1: Add failing scoring tests**

Append to `LeadFinderTests` in `tests/test_leadfinder.py`:

```python
    def test_scoring_rewards_bill_of_lading_buyer_evidence(self) -> None:
        scored = score_lead(
            {
                "source_type": "Bill of Lading",
                "notes": "Evidence: public bill-of-lading/import record",
                "raw_text": "Consignee imported HS 7019 fiberglass woven roving from China.",
                "website": "https://buyer.example",
                "company_name": "Example Buyer",
            }
        )
        self.assertGreaterEqual(scored["match_score"], 60)

    def test_scoring_rewards_verified_saas_contact(self) -> None:
        scored = score_lead(
            {
                "source_type": "SaaS Contact",
                "source_name": "Snov.io",
                "email": "sales@example.com",
                "raw_text": "Composite distributor buying fiberglass fabric.",
                "website": "https://buyer.example",
                "company_name": "Example Distributor",
            }
        )
        self.assertGreaterEqual(scored["match_score"], 55)
```

- [ ] **Step 2: Run the scoring tests and verify at least one fails**

Run:

```powershell
python -m unittest tests.test_leadfinder.LeadFinderTests.test_scoring_rewards_bill_of_lading_buyer_evidence tests.test_leadfinder.LeadFinderTests.test_scoring_rewards_verified_saas_contact
```

Expected: at least one assertion fails with the current scoring thresholds.

- [ ] **Step 3: Add buyer and contact signals to `score_lead`**

Modify `leadfinder/scoring.py`.

Add near the existing term lists:

```python
BUYER_TERMS = [
    "importer",
    "buyer",
    "consignee",
    "distributor",
    "manufacturer",
    "pultrusion",
    "frp pipe",
    "shipment",
    "imported",
    "hs 7019",
]
```

Inside `score_lead()`, after `negative_hits = _hits(text, NEGATIVE_TERMS)`, add:

```python
    buyer_hits = _hits(text, BUYER_TERMS)
    source_type = str(lead.get("source_type", "") or "").lower()
```

After existing website/company score additions, add:

```python
    if source_type == "bill of lading":
        score += 18
    if source_type == "saas contact":
        score += 10
    score += min(len(buyer_hits), 4) * 7
```

Change:

```python
    matched = yarn_hits + fabric_hits + general_hits
```

to:

```python
    matched = yarn_hits + fabric_hits + general_hits + buyer_hits
```

- [ ] **Step 4: Run scoring tests and all tests**

Run:

```powershell
python -m unittest tests.test_leadfinder.LeadFinderTests.test_scoring_rewards_bill_of_lading_buyer_evidence tests.test_leadfinder.LeadFinderTests.test_scoring_rewards_verified_saas_contact
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

- [ ] **Step 5: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add leadfinder/scoring.py tests/test_leadfinder.py
git commit -m "feat: score buyer evidence and contact sources"
```

### Task 6: README Workflow For Cost-Aware Lead Intake

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README commands**

Add these commands under `## Commands` in `README.md`:

```powershell
python cli.py provider-report
python cli.py quality-report --min-score 50
python cli.py import-csv --input exports/waitubang.csv --source 外贸邦
python cli.py import-csv --input exports/yizhijia.csv --source 易之家
python cli.py import-csv --input exports/apollo.csv --source Apollo.io
python cli.py import-csv --input exports/snov.csv --source Snov.io
python cli.py quality-report --min-score 50
python -m unittest discover -s tests -p test_*.py
```

- [ ] **Step 2: Add source policy notes**

Add this section to `README.md`:

```markdown
## Cost-aware source workflow

- Use UN Comtrade to choose target countries for HS 7019 fiberglass products.
- Use Serper discovery for public company websites when free trial or paid credits are available.
- Use 外贸邦 / 易之家 manually for public bill-of-lading clues, then import exported or copied CSV rows with `import-csv`.
- Use Apollo.io / Snov.io free credits manually for email discovery, then import their CSV output with `import-csv`.
- Keep Serper, Apollo.io, Snov.io, and Bright Data as optional paid or free-credit sources. Their quotas and credit systems can change, so the core workflow must still work without them.
- Use Bright Data only for public web pages. Do not use it for logged-in SaaS pages, paywalled data, or bypassing account restrictions.
- Do not scrape bill-of-lading or SaaS platforms unless their terms allow it for the account being used.
```

- [ ] **Step 3: Verify README mentions the correct test command**

Run:

```powershell
Select-String -Path README.md -Pattern "python -m unittest discover -s tests -p test_*.py"
```

Expected: one matching README line.

- [ ] **Step 4: Run the documented test command**

Run:

```powershell
python -m unittest discover -s tests -p test_*.py
```

Expected: `OK`.

- [ ] **Step 5: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add README.md
git commit -m "docs: document zero-cost lead source workflow"
```

---

## Release B: Private Local Workbench

### Task 7: Web API For Leads, Stats, And Status Updates

**Files:**
- Create: `leadfinder/webapp.py`
- Test: `tests/test_webapp.py`

- [ ] **Step 1: Write failing web API tests**

Create `tests/test_webapp.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from leadfinder.db import connect, create_or_skip_lead, list_leads
from leadfinder.webapp import make_app


class WebAppTests(unittest.TestCase):
    def test_api_leads_returns_json_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Example Buyer",
                        "country_region": "USA",
                        "website": "https://example.com",
                        "match_score": 75,
                        "status": "Discovered",
                    },
                )
            finally:
                db.close()

            app = make_app(db_path)
            status, headers, body = app.handle("GET", "/api/leads", b"")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["leads"][0]["company_name"], "Example Buyer")

    def test_api_status_update_changes_lead_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                lead, _ = create_or_skip_lead(db, {"company_name": "Example Buyer", "website": "https://example.com"})
            finally:
                db.close()

            app = make_app(db_path)
            status, _, body = app.handle(
                "POST",
                f"/api/leads/{lead['id']}/status",
                json.dumps({"status": "Qualified"}).encode("utf-8"),
            )
            db = connect(db_path)
            try:
                rows = list_leads(db)
            finally:
                db.close()

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["lead"]["status"], "Qualified")
        self.assertEqual(rows[0]["status"], "Qualified")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run web tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_webapp
```

Expected: fail with `ModuleNotFoundError: No module named 'leadfinder.webapp'`.

- [ ] **Step 3: Implement minimal web app object**

Create `leadfinder/webapp.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .db import connect, list_leads, stats, update_lead


ALLOWED_STATUSES = {"Discovered", "Enriched", "Qualified", "Rejected", "Error"}


@dataclass(frozen=True)
class LocalLeadApp:
    db_path: Path

    def handle(self, method: str, path: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(path)
        if method == "GET" and parsed.path == "/api/leads":
            query = parse_qs(parsed.query)
            status = query.get("status", [None])[0]
            limit_text = query.get("limit", ["100"])[0]
            limit = max(1, min(int(limit_text), 500))
            db = connect(self.db_path)
            try:
                leads = list_leads(db, status=status, limit=limit)
            finally:
                db.close()
            return self.json_response({"leads": leads})

        if method == "GET" and parsed.path == "/api/stats":
            db = connect(self.db_path)
            try:
                payload = stats(db)
            finally:
                db.close()
            return self.json_response(payload)

        match = re.fullmatch(r"/api/leads/(\d+)/status", parsed.path)
        if method == "POST" and match:
            lead_id = int(match.group(1))
            payload = json.loads(body.decode("utf-8") or "{}")
            next_status = str(payload.get("status", "")).strip()
            if next_status not in ALLOWED_STATUSES:
                return self.json_response({"error": "invalid status"}, status=400)
            db = connect(self.db_path)
            try:
                lead = update_lead(db, lead_id, {"status": next_status})
            finally:
                db.close()
            return self.json_response({"lead": lead})

        return self.json_response({"error": "not found"}, status=404)

    def json_response(self, payload: dict, status: int = 200) -> tuple[int, dict[str, str], bytes]:
        return (
            status,
            {"Content-Type": "application/json; charset=utf-8"},
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )


def make_app(db_path: str | Path) -> LocalLeadApp:
    return LocalLeadApp(Path(db_path))
```

- [ ] **Step 4: Run web API tests and all tests**

Run:

```powershell
python -m unittest tests.test_webapp
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

- [ ] **Step 5: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add leadfinder/webapp.py tests/test_webapp.py
git commit -m "feat: add local lead workbench API"
```

### Task 8: Local HTTP Server And CLI `serve`

**Files:**
- Modify: `leadfinder/webapp.py`
- Modify: `cli.py`
- Test: `tests/test_webapp.py`

- [ ] **Step 1: Add failing server smoke test for HTML**

Append to `WebAppTests` in `tests/test_webapp.py`:

```python
    def test_homepage_returns_workbench_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            status, headers, body = app.handle("GET", "/", b"")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn(b"Lead Finder Workbench", body)
        self.assertIn(b"/api/leads", body)
```

- [ ] **Step 2: Run homepage test and verify it fails**

Run:

```powershell
python -m unittest tests.test_webapp.WebAppTests.test_homepage_returns_workbench_html
```

Expected: fail because `/` currently returns JSON 404.

- [ ] **Step 3: Add HTML response and HTTP server**

Modify `leadfinder/webapp.py`.

Add imports:

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
```

Add this constant:

```python
INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lead Finder Workbench</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #1f2933; background: #f6f8fa; }
    header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
    table { width: 100%; border-collapse: collapse; background: #fff; margin-top: 16px; }
    th, td { border-bottom: 1px solid #d9e2ec; padding: 8px; text-align: left; font-size: 14px; }
    th { background: #eef2f6; }
    select, button { font-size: 14px; padding: 6px 8px; }
    .score { font-weight: 700; }
  </style>
</head>
<body>
  <header>
    <h1>Lead Finder Workbench</h1>
    <button id="refresh">Refresh</button>
  </header>
  <table>
    <thead>
      <tr>
        <th>Score</th><th>Company</th><th>Country</th><th>Fit</th><th>Email</th><th>Status</th><th>Source</th>
      </tr>
    </thead>
    <tbody id="leads"></tbody>
  </table>
  <script>
    async function loadLeads() {
      const response = await fetch('/api/leads?limit=200');
      const payload = await response.json();
      document.getElementById('leads').innerHTML = payload.leads.map((lead) => `
        <tr>
          <td class="score">${lead.match_score || 0}</td>
          <td><a href="${lead.website || '#'}" target="_blank">${lead.company_name || ''}</a></td>
          <td>${lead.country_region || ''}</td>
          <td>${lead.product_fit || ''}</td>
          <td>${lead.email || ''}</td>
          <td>${lead.status || ''}</td>
          <td>${lead.source_name || ''}</td>
        </tr>
      `).join('');
    }
    document.getElementById('refresh').addEventListener('click', loadLeads);
    loadLeads();
  </script>
</body>
</html>
"""
```

Inside `LocalLeadApp.handle()`, before `/api/leads`, add:

```python
        if method == "GET" and parsed.path == "/":
            return (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                INDEX_HTML.encode("utf-8"),
            )
```

Add below `make_app()`:

```python
def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    app = make_app(db_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length else b""
            status, headers, response_body = app.handle(self.command, self.path, body)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response_body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Lead Finder Workbench: http://{host}:{port}")
    server.serve_forever()
```

- [ ] **Step 4: Add CLI `serve` command**

Modify `cli.py`:

```python
from leadfinder.webapp import serve
```

Add command handler:

```python
def cmd_serve(args: argparse.Namespace) -> int:
    cfg = settings()
    serve(cfg.db_path, host=args.host, port=args.port)
    return 0
```

Add parser block before `stats_parser`:

```python
    serve_parser = sub.add_parser("serve", help="Run the private local lead workbench.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.set_defaults(func=cmd_serve)
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest tests.test_webapp
python -m unittest discover -s tests -p test_*.py
```

Expected: both commands pass with `OK`.

- [ ] **Step 6: Manual server check**

Run:

```powershell
python cli.py serve --host 127.0.0.1 --port 8765
```

Expected: terminal prints `Lead Finder Workbench: http://127.0.0.1:8765`. Stop the server with `Ctrl+C` after opening the URL.

- [ ] **Step 7: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add cli.py leadfinder/webapp.py tests/test_webapp.py
git commit -m "feat: serve private local lead workbench"
```

### Task 9: README For Two-Stage Operating Workflow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add staged workflow section**

Add this section to `README.md`:

```markdown
## Recommended operating flow

### Stage 1: source aggregation

1. Pick target countries with `python cli.py markets --hs 7019 --year 2024`.
2. Check cost assumptions with `python cli.py provider-report`.
3. Run public discovery with `python cli.py discover --country USA --limit 100` when Serper free trial or paid credits are available.
4. Record the baseline with `python cli.py quality-report --min-score 50`.
5. Import bill-of-lading CSV rows with `python cli.py import-csv --input exports/waitubang.csv --source 外贸邦`.
6. Import free-credit or paid SaaS contact CSV rows with `python cli.py import-csv --input exports/snov.csv --source Snov.io`.
7. Enrich websites with `python cli.py enrich --limit 100`.
8. Recheck quality with `python cli.py quality-report --min-score 50`.
9. Export CRM CSV with `python cli.py export --output exports/sourced_leads.csv --min-score 50`.

### Stage 2: private workbench

Run `python cli.py serve` and open `http://127.0.0.1:8765`.

Use the workbench to review leads, inspect source and fit, and decide which leads should be exported for CRM follow-up.
```

- [ ] **Step 2: Verify commands in README still run or are documented examples**

Run:

```powershell
python cli.py stats
python -m unittest discover -s tests -p test_*.py
```

Expected: `stats` prints JSON and tests pass with `OK`.

- [ ] **Step 3: Version-control checkpoint**

Run:

```powershell
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If execution happens in an initialized repository, commit:

```powershell
git add README.md
git commit -m "docs: add staged lead generation workflow"
```

---

## Final Verification

- [ ] **Run all unit tests**

```powershell
python -m unittest discover -s tests -p test_*.py
```

Expected: all tests pass with `OK`.

- [ ] **Check CLI help includes new commands**

```powershell
python cli.py --help
```

Expected: subcommands include `quality-report`, `import-csv`, and `serve`.

- [ ] **Check provider report works**

```powershell
python cli.py provider-report
```

Expected: JSON classifies `Serper`, `Apollo.io`, `Snov.io`, and `Bright Data` as not part of the zero-cost core.

- [ ] **Check quality report works**

```powershell
python cli.py quality-report --min-score 50
```

Expected: JSON with `total`, `high_score`, `with_email`, `with_buyer_evidence`, `with_contact_evidence`, `high_quality`, and `high_quality_rate`.

- [ ] **Quality improvement gate**

After importing a real sample from 外贸邦 / 易之家 / Apollo.io / Snov.io, run:

```powershell
python cli.py quality-report --min-score 50
```

Expected: `high_quality` should increase compared with the pre-import baseline. If `high_quality_rate` drops, inspect the imported CSV mapping before proceeding to the web workbench.

- [ ] **Check empty database still works**

```powershell
python cli.py stats
```

Expected: JSON with `leads`, `markets`, `by_status`, and `by_product_fit`.

- [ ] **Run a local workbench smoke check**

```powershell
python cli.py serve --host 127.0.0.1 --port 8765
```

Expected: `http://127.0.0.1:8765` opens a lead table. Stop with `Ctrl+C`.

## Self-Review

- Spec coverage: Release A covers measurable quality reporting, 外贸邦 / 易之家 / Apollo.io / Snov.io through CSV/manual import, source preservation, dedupe, and scoring. Release B covers the private local workbench with lead listing and status updates.
- Placeholder scan: No unresolved placeholder language is present in this plan.
- Type consistency: `quality_report`, `ImportResult`, `normalize_source_row`, `import_csv`, `make_app`, and `serve` names are introduced before later tasks use them. Existing fields match `leadfinder.db.LEAD_FIELDS`.
- Scope check: Email sending, paid API automation, platform scraping, and CRM database writes are intentionally outside this plan.
