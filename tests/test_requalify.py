from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from leadfinder.db import connect, create_or_skip_lead, list_leads
from leadfinder.requalify import RequalifyOptions, requalify_leads


def downstream_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    return {
        **(defaults or {}),
        "website": url,
        "raw_text": (
            "Pultrusion manufacturer making FRP profiles using fiberglass roving. "
            "Contact us. Wisconsin United States."
        ),
    }


def supplier_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    return {
        **(defaults or {}),
        "website": url,
        "raw_text": (
            "Fiberglass roving manufacturer, direct roving manufacturer, "
            "roving factory and exporter in China."
        ),
    }


class RequalifyTests(unittest.TestCase):
    def test_requalify_qualifies_downstream_market_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "Example Pultrusion",
                        "country_region": "USA",
                        "website": "https://buyer.example",
                        "status": "Discovered",
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(),
                    site_enricher=downstream_enricher,
                )
                lead = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(result["qualified"], 1)
        self.assertEqual(lead["status"], "Qualified")
        self.assertIn("Site classification: downstream_customer", lead["fit_reason"])
        self.assertIn("Market fit: target=USA passed=True", lead["fit_reason"])
        self.assertEqual(lead["classification_status"], "manufacturer")
        self.assertTrue(lead["classification_evidence"])
        self.assertIsInstance(json.loads(lead["score_evidence"]), dict)
        self.assertEqual(lead["review_status"], "high_confidence")

    def test_requalify_rejects_supplier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "Roving Factory",
                        "country_region": "USA",
                        "website": "https://supplier.example",
                        "status": "Discovered",
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(),
                    site_enricher=supplier_enricher,
                )
                lead = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(result["rejected"], 1)
        self.assertEqual(lead["status"], "Rejected")
        self.assertIn("Site classification: supplier", lead["fit_reason"])
        self.assertEqual(lead["classification_status"], "supplier")
        self.assertTrue(lead["classification_evidence"])
        self.assertEqual(lead["review_status"], "suspected_supplier")

    def test_requalify_skips_already_reviewed_by_default(self) -> None:
        calls = 0

        def tracking_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
            nonlocal calls
            calls += 1
            return downstream_enricher(url, defaults)

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "Reviewed Buyer",
                        "country_region": "USA",
                        "website": "https://reviewed.example",
                        "fit_reason": (
                            "Site classification: downstream_customer confidence=80 passed=True\n"
                            "Market fit: target=USA passed=True confidence=60 "
                            "reason=target market evidence"
                        ),
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(only_unreviewed=True),
                    site_enricher=tracking_enricher,
                )
            finally:
                db.close()

        self.assertEqual(result["reviewed"], 0)
        self.assertEqual(calls, 0)

    def test_requalify_rejects_excluded_legacy_source_without_crawl(self) -> None:
        calls = 0

        def tracking_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
            nonlocal calls
            calls += 1
            return downstream_enricher(url, defaults)

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "Importers Directory",
                        "country_region": "USA",
                        "website": "https://www.zauba.com/Buyers-of-fiberglass-roving-mat",
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(),
                    site_enricher=tracking_enricher,
                )
                lead = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(result["rejected"], 1)
        self.assertEqual(lead["status"], "Rejected")
        self.assertEqual(calls, 0)
        self.assertEqual(lead["classification_status"], "directory")
        self.assertTrue(lead["classification_evidence"])
        self.assertEqual(lead["review_status"], "needs_review")

    def test_requalify_uses_existing_evidence_when_crawl_is_empty(self) -> None:
        def empty_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
            return {**(defaults or {}), "website": url, "raw_text": ""}

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "China Roving Factory",
                        "country_region": "USA",
                        "website": "https://supplier.example",
                        "raw_text": "Fiberglass roving manufacturer, roving factory and exporter from China.",
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(),
                    site_enricher=empty_enricher,
                )
                lead = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(lead["status"], "Rejected")
        self.assertEqual(lead["classification_status"], "supplier")
        self.assertTrue(lead["classification_evidence"])
        self.assertIsInstance(json.loads(lead["score_evidence"]), dict)
        self.assertEqual(lead["review_status"], "crawl_failed")

    def test_requalify_marks_unclassified_crawl_error_with_evidence(self) -> None:
        def failing_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
            raise RuntimeError("crawl blocked")

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "Unknown Company",
                        "country_region": "USA",
                        "website": "https://unknown.example",
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(),
                    site_enricher=failing_enricher,
                )
                lead = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(result["errors"], 1)
        self.assertEqual(lead["status"], "Error")
        self.assertEqual(lead["review_status"], "crawl_failed")
        self.assertEqual(lead["classification_status"], "unknown")
        self.assertTrue(lead["classification_evidence"])
        self.assertIsInstance(json.loads(lead["score_evidence"]), dict)

    def test_requalify_continues_when_classification_has_no_market_fit(self) -> None:
        calls = 0

        def tracking_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
            nonlocal calls
            calls += 1
            return downstream_enricher(url, defaults)

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "Partially Reviewed Buyer",
                        "country_region": "USA",
                        "website": "https://buyer.example",
                        "fit_reason": "Site classification: downstream_customer confidence=80 passed=True",
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(only_unreviewed=True),
                    site_enricher=tracking_enricher,
                )
            finally:
                db.close()

        self.assertEqual(result["reviewed"], 1)
        self.assertEqual(calls, 1)

    def test_requalify_retries_unknown_classification(self) -> None:
        calls = 0

        def tracking_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
            nonlocal calls
            calls += 1
            return downstream_enricher(url, defaults)

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "source_type": "Website",
                        "company_name": "Unknown Company",
                        "country_region": "USA",
                        "website": "https://unknown.example",
                        "fit_reason": "Site classification: unknown confidence=30 passed=False",
                    },
                )
                result = requalify_leads(
                    db,
                    RequalifyOptions(only_unreviewed=True),
                    site_enricher=tracking_enricher,
                )
            finally:
                db.close()

        self.assertEqual(result["reviewed"], 1)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
