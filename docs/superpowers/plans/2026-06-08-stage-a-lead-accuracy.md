# Stage A Lead Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make lead qualification decisions explainable and prevent low-confidence leads from consuming Apollo, Hunter, or CRM sync capacity.

**Architecture:** Add a small evidence layer that turns scoring and classification signals into structured JSON. Keep the existing SQLite-backed CLI and stdlib webapp, add only focused columns needed for display and gating, and keep the CRM export schema unchanged. Hunter enrichment will use a single eligibility helper so UI and CLI paths share the same credit gate.

**Tech Stack:** Python stdlib, SQLite, unittest, existing local HTTP workbench.

---

## File Structure

- Create `leadfinder/evidence.py`
  - Owns score evidence extraction, score breakdown formatting, classification label normalization, and enrichment eligibility.
  - Keeps evidence logic out of `webapp.py` and avoids expanding `scoring.py` into a display module.
- Modify `leadfinder/scoring.py`
  - Continue returning `match_score`, `product_fit`, and `fit_reason`.
  - Add `score_evidence` JSON text and make `fit_reason` use the same evidence source.
- Modify `leadfinder/classifier.py`
  - Keep the existing `classify_company_site()` shape.
  - Add normalized categories and explanation text while preserving current callers.
- Modify `leadfinder/db.py`
  - Add new lead columns through the existing migration pattern.
  - Include the new fields in `LEAD_FIELDS`.
- Modify `leadfinder/contact_enrichment.py`
  - Use the eligibility helper before Hunter domain search and existing-email verification.
- Modify `leadfinder/webapp.py`
  - Add workbench filters and display evidence summaries.
  - Keep existing endpoint style and synchronous request handling.
- Test files:
  - Modify `tests/test_leadfinder.py`.
  - Modify `tests/test_contact_enrichment.py`.
  - Modify `tests/test_webapp.py`.
  - Add `tests/test_evidence.py`.

---

### Task 1: Structured Score Evidence

**Files:**
- Create: `leadfinder/evidence.py`
- Modify: `leadfinder/scoring.py`
- Test: `tests/test_evidence.py`
- Test: `tests/test_leadfinder.py`

- [ ] **Step 1: Write failing evidence tests**

Create `tests/test_evidence.py`:

```python
from __future__ import annotations

import json
import unittest

from leadfinder.evidence import (
    enrichment_eligible,
    lead_classification_label,
    parse_score_evidence,
    score_reason_text,
)


class EvidenceTests(unittest.TestCase):
    def test_parse_score_evidence_returns_empty_structure_for_blank_value(self) -> None:
        evidence = parse_score_evidence("")

        self.assertEqual(evidence["additions"], [])
        self.assertEqual(evidence["penalties"], [])
        self.assertEqual(evidence["matched_terms"], [])

    def test_score_reason_text_formats_additions_and_penalties(self) -> None:
        text = score_reason_text(
            {
                "additions": [
                    {"points": 25, "reason": "downstream application", "terms": ["pultrusion"]},
                    {"points": 15, "reason": "target market evidence", "terms": ["Canada"]},
                ],
                "penalties": [
                    {"points": -30, "reason": "supplier language", "terms": ["exporter"]},
                ],
                "matched_terms": ["pultrusion", "Canada", "exporter"],
            }
        )

        self.assertIn("+25 downstream application: pultrusion", text)
        self.assertIn("+15 target market evidence: Canada", text)
        self.assertIn("-30 supplier language: exporter", text)

    def test_lead_classification_label_maps_existing_categories(self) -> None:
        self.assertEqual(lead_classification_label("downstream_customer"), "buyer")
        self.assertEqual(lead_classification_label("distributor_or_importer"), "distributor")
        self.assertEqual(lead_classification_label("noise"), "directory")
        self.assertEqual(lead_classification_label("supplier"), "supplier")
        self.assertEqual(lead_classification_label(""), "unknown")

    def test_enrichment_eligible_requires_passed_classification_market_and_score(self) -> None:
        eligible = {
            "company_name": "Qualified Buyer",
            "status": "Qualified",
            "match_score": 75,
            "website": "https://buyer.example",
            "classification_status": "buyer",
            "market_fit_status": "passed",
            "crawl_status": "ok",
        }
        supplier = {**eligible, "classification_status": "supplier"}
        weak = {**eligible, "match_score": 42}
        failed_market = {**eligible, "market_fit_status": "failed"}
        failed_crawl = {**eligible, "crawl_status": "error"}

        self.assertTrue(enrichment_eligible(eligible, min_score=50))
        self.assertFalse(enrichment_eligible(supplier, min_score=50))
        self.assertFalse(enrichment_eligible(weak, min_score=50))
        self.assertFalse(enrichment_eligible(failed_market, min_score=50))
        self.assertFalse(enrichment_eligible(failed_crawl, min_score=50))


if __name__ == "__main__":
    unittest.main()
```

Add this test to `tests/test_leadfinder.py`:

```python
    def test_scoring_returns_structured_evidence(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "country_region": "USA",
                "company_name": "Example Pultrusion",
                "website": "https://buyer.example",
                "raw_text": "Pultrusion manufacturer using fiberglass roving. Contact us.",
            }
        )

        evidence = json.loads(scored["score_evidence"])
        self.assertTrue(any(item["reason"] == "yarn terms" for item in evidence["additions"]))
        self.assertTrue(any(item["reason"] == "company website" for item in evidence["additions"]))
        self.assertEqual(evidence["penalties"], [])
        self.assertIn("+", scored["fit_reason"])
```

Update imports at the top of `tests/test_leadfinder.py`:

```python
import csv
import json
import tempfile
import unittest
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_evidence tests.test_leadfinder -v
```

Expected:

```text
ModuleNotFoundError: No module named 'leadfinder.evidence'
```

or:

```text
KeyError: 'score_evidence'
```

- [ ] **Step 3: Implement evidence helpers**

Create `leadfinder/evidence.py`:

```python
from __future__ import annotations

import json

PASSING_CLASSIFICATIONS = {"buyer", "manufacturer", "distributor"}
PASSING_MARKET_STATUSES = {"passed", "pass", "matched", "ok", "positive"}
PASSING_CRAWL_STATUSES = {"", "ok", "success", "passed", "fetched"}


def evidence_json(evidence: dict) -> str:
    return json.dumps(
        {
            "additions": evidence.get("additions", []),
            "penalties": evidence.get("penalties", []),
            "matched_terms": evidence.get("matched_terms", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def parse_score_evidence(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        return {
            "additions": list(value.get("additions", [])),
            "penalties": list(value.get("penalties", [])),
            "matched_terms": list(value.get("matched_terms", [])),
        }
    if not value:
        return {"additions": [], "penalties": [], "matched_terms": []}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {"additions": [], "penalties": [], "matched_terms": []}
    if not isinstance(parsed, dict):
        return {"additions": [], "penalties": [], "matched_terms": []}
    return {
        "additions": list(parsed.get("additions", [])),
        "penalties": list(parsed.get("penalties", [])),
        "matched_terms": list(parsed.get("matched_terms", [])),
    }


def score_reason_text(evidence: dict) -> str:
    parts: list[str] = []
    for item in evidence.get("additions", []):
        parts.append(_format_item(item, positive=True))
    for item in evidence.get("penalties", []):
        parts.append(_format_item(item, positive=False))
    if not parts:
        return "No fiberglass keywords found yet; review manually."
    return "; ".join(parts)


def lead_classification_label(category: str | None) -> str:
    value = str(category or "").strip().lower()
    mapping = {
        "downstream_customer": "buyer",
        "buyer": "buyer",
        "manufacturer": "manufacturer",
        "distributor_or_importer": "distributor",
        "distributor": "distributor",
        "supplier": "supplier",
        "noise": "directory",
        "directory": "directory",
    }
    return mapping.get(value, "unknown")


def enrichment_eligible(lead: dict, *, min_score: int = 50) -> bool:
    if str(lead.get("status", "") or "") != "Qualified":
        return False
    if int(lead.get("match_score", 0) or 0) < int(min_score):
        return False
    if not str(lead.get("website", "") or "").strip():
        return False
    classification = lead_classification_label(lead.get("classification_status", ""))
    if classification not in PASSING_CLASSIFICATIONS:
        return False
    market_status = str(lead.get("market_fit_status", "") or "").strip().lower()
    if market_status and market_status not in PASSING_MARKET_STATUSES:
        return False
    crawl_status = str(lead.get("crawl_status", "") or "").strip().lower()
    if crawl_status and crawl_status not in PASSING_CRAWL_STATUSES:
        return False
    return True


def _format_item(item: dict, *, positive: bool) -> str:
    points = int(item.get("points", 0) or 0)
    if positive and points > 0:
        prefix = f"+{points}"
    else:
        prefix = str(points)
    reason = str(item.get("reason", "") or "").strip()
    terms = [str(term) for term in item.get("terms", []) if str(term).strip()]
    suffix = f": {', '.join(terms[:5])}" if terms else ""
    return f"{prefix} {reason}{suffix}".strip()
```

- [ ] **Step 4: Add score evidence to scoring**

Modify `leadfinder/scoring.py` imports:

```python
from __future__ import annotations

from .evidence import evidence_json, score_reason_text
```

Inside `score_lead()`, after all hit lists are calculated and before `score = 0`, create evidence containers:

```python
    additions: list[dict] = []
    penalties: list[dict] = []

    def add(points: int, reason: str, terms: list[str]) -> int:
        if points and terms:
            additions.append({"points": points, "reason": reason, "terms": list(dict.fromkeys(terms))[:8]})
        return points

    def subtract(points: int, reason: str, terms: list[str]) -> int:
        if points and terms:
            penalties.append({"points": -points, "reason": reason, "terms": list(dict.fromkeys(terms))[:8]})
        return points
```

Replace the scoring block with this equivalent evidence-producing block:

```python
    score = 0
    score += add(min(len(general_hits), 5) * 8, "general fiberglass terms", general_hits)
    score += add(min(len(yarn_hits), 5) * 12, "yarn terms", yarn_hits)
    score += add(min(len(fabric_hits), 5) * 12, "fabric terms", fabric_hits)
    if lead.get("email"):
        score += add(14, "email present", [str(lead.get("email"))])
    if lead.get("website"):
        score += add(8, "company website", [str(lead.get("website"))])
    if lead.get("company_name"):
        score += add(6, "company name", [str(lead.get("company_name"))])
    if source_type == "bill of lading":
        score += add(18, "bill of lading buyer evidence", ["bill of lading"])
    if source_type == "saas contact":
        score += add(10, "SaaS contact source", [str(lead.get("source_name", "SaaS Contact") or "SaaS Contact")])
    score += add(min(len(buyer_hits), 4) * 7, "buyer terms", buyer_hits)
    score += add(min(len(downstream_hits), 3) * 10, "downstream application", downstream_hits)
    score += add(min(len(company_evidence_hits), 3) * 4, "company page evidence", company_evidence_hits)
    score -= subtract(min(len(negative_hits), 3) * 15, "negative terms", negative_hits)
    if is_directory_source:
        score -= subtract(35, "directory or marketplace source", [source_location])
    if mismatch_hits:
        score -= subtract(45, "target-country mismatch", mismatch_hits)
```

Replace the old `fit_reason` construction with:

```python
    matched = yarn_hits + fabric_hits + general_hits + buyer_hits + downstream_hits + company_evidence_hits
    evidence = {
        "additions": additions,
        "penalties": penalties,
        "matched_terms": list(dict.fromkeys(matched))[:12],
    }
    fit_reason = score_reason_text(evidence)
```

Return `score_evidence`:

```python
    return {
        "match_score": score,
        "product_fit": product_fit,
        "fit_reason": fit_reason,
        "score_evidence": evidence_json(evidence),
    }
```

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_evidence tests.test_leadfinder -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add leadfinder/evidence.py leadfinder/scoring.py tests/test_evidence.py tests/test_leadfinder.py
git commit -m "Add structured score evidence"
```

Expected:

```text
[main <hash>] Add structured score evidence
```

---

### Task 2: Normalized Classification Evidence

**Files:**
- Modify: `leadfinder/classifier.py`
- Modify: `tests/test_leadfinder.py`

- [ ] **Step 1: Write failing classification tests**

Add these tests to `tests/test_leadfinder.py`:

```python
    def test_classifier_returns_normalized_buyer_label_and_explanation(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Pultrusion manufacturer making FRP profiles. Contact us for capabilities.",
                "website": "https://buyer.example",
            }
        )

        self.assertTrue(classification["passed"])
        self.assertEqual(classification["category"], "downstream_customer")
        self.assertEqual(classification["label"], "buyer")
        self.assertIn("downstream usage evidence", classification["explanation"])
        self.assertIn("pultrusion manufacturer", classification["evidence"])

    def test_classifier_returns_supplier_label_and_explanation(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Fiberglass roving manufacturer and exporter with roving factory production.",
                "website": "https://supplier.example",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["label"], "supplier")
        self.assertIn("supplier/manufacturer source", classification["explanation"])
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_leadfinder -v
```

Expected:

```text
KeyError: 'label'
```

- [ ] **Step 3: Implement normalized labels and explanations**

Modify imports in `leadfinder/classifier.py`:

```python
from __future__ import annotations

from .evidence import lead_classification_label
```

Replace `_result()` with:

```python
def _result(category: str, passed: bool, confidence: int, evidence: list[str], reason: str) -> dict:
    unique_evidence = list(dict.fromkeys(evidence))[:8]
    label = lead_classification_label(category)
    evidence_text = ", ".join(unique_evidence)
    explanation = f"{reason}; evidence={evidence_text}" if evidence_text else reason
    return {
        "category": category,
        "label": label,
        "passed": passed,
        "confidence": confidence,
        "evidence": unique_evidence,
        "reason": reason,
        "explanation": explanation,
    }
```

Update `classification_note()`:

```python
def classification_note(classification: dict) -> str:
    evidence = ", ".join(classification.get("evidence", []))
    suffix = f"; evidence={evidence}" if evidence else ""
    label = classification.get("label") or lead_classification_label(classification.get("category"))
    return (
        f"Site classification: {classification['category']} "
        f"label={label} "
        f"confidence={classification['confidence']} "
        f"passed={classification['passed']} "
        f"reason={classification['reason']}{suffix}"
    )
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_leadfinder -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add leadfinder/classifier.py tests/test_leadfinder.py
git commit -m "Normalize classification evidence"
```

Expected:

```text
[main <hash>] Normalize classification evidence
```

---

### Task 3: Persist Evidence Fields

**Files:**
- Modify: `leadfinder/db.py`
- Modify: `tests/test_leadfinder.py`

- [ ] **Step 1: Write failing persistence test**

Add this test to `tests/test_leadfinder.py`:

```python
    def test_db_persists_evidence_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                created, was_created = create_or_skip_lead(
                    db,
                    {
                        "company_name": "Evidence Buyer",
                        "website": "https://buyer.example",
                        "classification_status": "buyer",
                        "classification_evidence": "downstream usage evidence",
                        "score_evidence": '{"additions":[],"penalties":[],"matched_terms":[]}',
                        "review_status": "high_confidence",
                    },
                )
                rows = list_leads(db)
            finally:
                db.close()

        self.assertTrue(was_created)
        self.assertEqual(created["classification_status"], "buyer")
        self.assertEqual(rows[0]["classification_evidence"], "downstream usage evidence")
        self.assertEqual(rows[0]["review_status"], "high_confidence")
        self.assertIn("additions", rows[0]["score_evidence"])
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
python -m unittest tests.test_leadfinder -v
```

Expected:

```text
KeyError: 'classification_evidence'
```

- [ ] **Step 3: Add schema columns**

Modify the `leads` table definition in `leadfinder/db.py` by adding these columns after `classification_status`:

```python
  classification_evidence TEXT NOT NULL DEFAULT '',
  score_evidence TEXT NOT NULL DEFAULT '',
  review_status TEXT NOT NULL DEFAULT '',
```

Add these fields to `LEAD_FIELDS` after `classification_status`:

```python
    "classification_evidence",
    "score_evidence",
    "review_status",
```

Add these fields to `LEAD_STATUS_COLUMNS`:

```python
    "classification_evidence": "TEXT NOT NULL DEFAULT ''",
    "score_evidence": "TEXT NOT NULL DEFAULT ''",
    "review_status": "TEXT NOT NULL DEFAULT ''",
```

- [ ] **Step 4: Run persistence test and verify it passes**

Run:

```powershell
python -m unittest tests.test_leadfinder -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add leadfinder/db.py tests/test_leadfinder.py
git commit -m "Persist lead evidence fields"
```

Expected:

```text
[main <hash>] Persist lead evidence fields
```

---

### Task 4: Apply Credit Gates Before Hunter

**Files:**
- Modify: `leadfinder/contact_enrichment.py`
- Modify: `tests/test_contact_enrichment.py`

- [ ] **Step 1: Write failing Hunter gate tests**

Add this test to `tests/test_contact_enrichment.py`:

```python
    def test_hunter_enrichment_skips_supplier_unknown_and_crawl_failures(self) -> None:
        class CountingHunter(FakeHunter):
            def __init__(self) -> None:
                self.domain_calls = 0

            def domain_search(self, domain: str) -> dict:
                self.domain_calls += 1
                return super().domain_search(domain)

        hunter = CountingHunter()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Eligible Buyer",
                        "website": "https://buyer.example",
                        "status": "Qualified",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Supplier",
                        "website": "https://supplier.example",
                        "status": "Qualified",
                        "match_score": 85,
                        "classification_status": "supplier",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Unknown",
                        "website": "https://unknown.example",
                        "status": "Qualified",
                        "match_score": 80,
                        "classification_status": "unknown",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Crawl Failed",
                        "website": "https://failed.example",
                        "status": "Qualified",
                        "match_score": 80,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "error",
                    },
                )
                result = enrich_qualified_emails(db, hunter, limit=10)
                rows = {lead["company_name"]: lead for lead in list_leads(db)}
            finally:
                db.close()

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(hunter.domain_calls, 1)
        self.assertEqual(rows["Eligible Buyer"]["email"], "sales@buyer.example")
        self.assertEqual(rows["Supplier"]["email"], "")
        self.assertEqual(rows["Unknown"]["email"], "")
        self.assertEqual(rows["Crawl Failed"]["email"], "")
```

Add this test for existing-email verification:

```python
    def test_existing_email_verification_uses_same_credit_gate(self) -> None:
        class CountingHunter(FakeHunter):
            def __init__(self) -> None:
                self.verify_calls = 0

            def verify_email(self, email: str) -> dict:
                self.verify_calls += 1
                return super().verify_email(email)

        hunter = CountingHunter()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Eligible Buyer",
                        "website": "https://buyer.example",
                        "email": "sales@buyer.example",
                        "status": "Qualified",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Supplier",
                        "website": "https://supplier.example",
                        "email": "sales@supplier.example",
                        "status": "Qualified",
                        "match_score": 85,
                        "classification_status": "supplier",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                result = verify_existing_qualified_emails(db, hunter, limit=10)
                rows = {lead["company_name"]: lead for lead in list_leads(db)}
            finally:
                db.close()

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["valid"], 1)
        self.assertEqual(hunter.verify_calls, 1)
        self.assertEqual(rows["Eligible Buyer"]["email_verification_status"], "valid")
        self.assertEqual(rows["Supplier"]["email_verification_status"], "")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_contact_enrichment -v
```

Expected:

```text
FAIL: test_hunter_enrichment_skips_supplier_unknown_and_crawl_failures
```

The failure should show more than one Hunter attempt before the gate is added.

- [ ] **Step 3: Use eligibility helper in Hunter enrichment**

Modify imports in `leadfinder/contact_enrichment.py`:

```python
from .evidence import enrichment_eligible
```

In `enrich_qualified_emails()`, replace the candidate filter with:

```python
    candidates = [
        lead
        for lead in list_leads(db, status="Qualified")
        if not str(lead.get("email", "") or "").strip()
        and enrichment_eligible(lead, min_score=50)
        and normalize_domain(lead.get("website", ""))
        and "hunter domain search:" not in str(lead.get("notes", "") or "").lower()
    ][: max(0, int(limit))]
```

In `verify_existing_qualified_emails()`, replace the candidate filter with:

```python
    candidates = [
        lead
        for lead in list_leads(db, status="Qualified")
        if str(lead.get("email", "") or "").strip()
        and enrichment_eligible(lead, min_score=50)
        and str(lead.get("email_verification_status", "") or "").strip().lower()
        not in {"valid", "invalid", "not_found"}
    ][: max(0, int(limit))]
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_contact_enrichment -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add leadfinder/contact_enrichment.py tests/test_contact_enrichment.py
git commit -m "Gate Hunter enrichment by lead evidence"
```

Expected:

```text
[main <hash>] Gate Hunter enrichment by lead evidence
```

---

### Task 5: Workbench Review Filters and Evidence Display

**Files:**
- Modify: `leadfinder/webapp.py`
- Modify: `tests/test_webapp.py`

- [ ] **Step 1: Write failing webapp tests**

Add this test to `tests/test_webapp.py`:

```python
    def test_homepage_includes_accuracy_review_filters(self) -> None:
        app = make_app(self.db_path)
        status, headers, body = app.handle("GET", "/", b"")
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn("高置信 Qualified", html)
        self.assertIn("待人工复核", html)
        self.assertIn("疑似供应商误判", html)
        self.assertIn("抓取失败", html)
```

Add this API test to `tests/test_webapp.py`:

```python
    def test_api_leads_supports_review_filter(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "High Confidence",
                    "status": "Qualified",
                    "match_score": 82,
                    "classification_status": "buyer",
                    "market_fit_status": "passed",
                    "crawl_status": "ok",
                    "review_status": "high_confidence",
                },
            )
            create_or_skip_lead(
                db,
                {
                    "company_name": "Needs Review",
                    "status": "Discovered",
                    "match_score": 45,
                    "classification_status": "unknown",
                    "review_status": "needs_review",
                },
            )
        finally:
            db.close()

        app = make_app(self.db_path)
        status, headers, body = app.handle("GET", "/api/leads?review=high_confidence", b"")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual([lead["company_name"] for lead in payload["leads"]], ["High Confidence"])
```

If `tests/test_webapp.py` does not already import `connect` and `create_or_skip_lead`, add:

```python
from leadfinder.db import connect, create_or_skip_lead
```

- [ ] **Step 2: Run webapp tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_webapp -v
```

Expected:

```text
FAIL: test_homepage_includes_accuracy_review_filters
```

or:

```text
FAIL: test_api_leads_supports_review_filter
```

- [ ] **Step 3: Add review filtering in the API**

In `leadfinder/webapp.py`, import the helper:

```python
from .evidence import enrichment_eligible, parse_score_evidence, score_reason_text
```

In the `/api/leads` handler, after reading `status`, read review filter:

```python
            review = query.get("review", [None])[0]
```

After `leads = list_leads(...)`, apply review filtering:

```python
                leads = [_decorate_lead_for_display(lead) for lead in leads]
                if review:
                    leads = [lead for lead in leads if lead.get("review_status") == review]
```

Add this helper near other module-level helper functions in `leadfinder/webapp.py`:

```python
def _decorate_lead_for_display(lead: dict) -> dict:
    evidence = parse_score_evidence(lead.get("score_evidence", ""))
    display = dict(lead)
    display["score_explanation"] = score_reason_text(evidence)
    if not display.get("review_status"):
        display["review_status"] = _review_status(display)
    return display


def _review_status(lead: dict) -> str:
    if str(lead.get("crawl_status", "") or "").lower() not in {"", "ok", "success", "passed", "fetched"}:
        return "crawl_failed"
    if str(lead.get("classification_status", "") or "").lower() == "supplier":
        return "suspected_supplier"
    if enrichment_eligible(lead, min_score=50):
        return "high_confidence"
    return "needs_review"
```

- [ ] **Step 4: Add review filter controls to the workbench HTML**

In `INDEX_HTML`, add these buttons near the existing status filters:

```html
      <button type="button" data-review="">全部复核状态</button>
      <button type="button" data-review="high_confidence">高置信 Qualified</button>
      <button type="button" data-review="needs_review">待人工复核</button>
      <button type="button" data-review="suspected_supplier">疑似供应商误判</button>
      <button type="button" data-review="crawl_failed">抓取失败</button>
```

In the JavaScript state object, add:

```javascript
      review: ''
```

When building the `/api/leads` URL, append:

```javascript
      if (state.review) {
        params.set('review', state.review);
      }
```

Add review button event binding near existing filter bindings:

```javascript
    document.querySelectorAll('[data-review]').forEach(button => {
      button.addEventListener('click', () => {
        state.review = button.dataset.review || '';
        loadLeads();
      });
    });
```

In the lead row rendering, add `score_explanation`, `classification_evidence`, and `review_status` to the visible detail text:

```javascript
        const evidence = [
          lead.review_status ? `复核: ${lead.review_status}` : '',
          lead.classification_status ? `分类: ${lead.classification_status}` : '',
          lead.classification_evidence ? `分类依据: ${lead.classification_evidence}` : '',
          lead.score_explanation ? `评分依据: ${lead.score_explanation}` : ''
        ].filter(Boolean).join(' | ');
```

Use `evidence` in the existing notes/detail area for each row.

- [ ] **Step 5: Run webapp tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_webapp -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add leadfinder/webapp.py tests/test_webapp.py
git commit -m "Add accuracy review filters"
```

Expected:

```text
[main <hash>] Add accuracy review filters
```

---

### Task 6: Full Verification and Documentation Touch-Up

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README accuracy section**

Add this section to `README.md` after `## Campaign workflow`:

```markdown
## Accuracy gates

Lead Finder qualifies leads through website evidence before spending contact-enrichment credits.

- Classification labels distinguish buyers, downstream manufacturers, distributors, suppliers, directories, and unknown sites.
- Score evidence records additions and penalties so each Qualified or Rejected decision can be reviewed.
- Hunter and Apollo enrichment should run only for Qualified leads that pass classification, market fit, crawl status, and score gates.
- The workbench review filters separate high-confidence Qualified leads, manual-review leads, suspected supplier false positives, and crawl failures.
```

Update the Notes section by replacing:

```markdown
- v1 does not send emails or write into the CRM database.
```

with:

```markdown
- The workbench can sync verified Qualified leads into the local CRM. It does not send emails automatically.
```

- [ ] **Step 2: Run full test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected:

```text
Ran 105 tests
OK
```

The test count may be higher after the new tests. The important expected result is `OK`.

- [ ] **Step 3: Run whitespace and status checks**

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
!! .superpowers/
!! __pycache__/
!! data/
!! debug.log
!! exports/
!! leadfinder/__pycache__/
!! tests/__pycache__/
```

Additional modified source and test files should already have been committed by earlier tasks. If they appear here, inspect before committing.

- [ ] **Step 4: Commit README**

Run:

```powershell
git add README.md
git commit -m "Document lead accuracy gates"
```

Expected:

```text
[main <hash>] Document lead accuracy gates
```

- [ ] **Step 5: Push Stage A branch state**

Run:

```powershell
git push
git status --short --branch
```

Expected:

```text
## main...origin/main
```

with only ignored local runtime files shown when `--ignored` is used.

---

## Self-Review

### Spec Coverage

- Structured evidence is covered by Task 1 and Task 3.
- Classification explanation is covered by Task 2 and Task 5.
- Score explanation is covered by Task 1 and Task 5.
- Review queues are covered by Task 5.
- API credit gating is covered by Task 4.
- CRM export stability is preserved because no task modifies `leadfinder/exporter.py` or `CRM_FIELDS`.
- Tests are included for evidence extraction, classification explanation, score explanation, enrichment gating, and workbench filters.

### Placeholder Scan

This plan does not use open-ended implementation placeholders. Each implementation step names exact files, functions, code snippets, commands, and expected outcomes.

### Type Consistency

- `score_evidence`, `classification_evidence`, and `review_status` are introduced in Task 3 before webapp display uses them in Task 5.
- `enrichment_eligible()` is introduced in Task 1 before contact enrichment uses it in Task 4.
- `lead_classification_label()` is introduced in Task 1 before classifier normalization uses it in Task 2.
- `parse_score_evidence()` and `score_reason_text()` are introduced in Task 1 before webapp display uses them in Task 5.

