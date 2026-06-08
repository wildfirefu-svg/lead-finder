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
