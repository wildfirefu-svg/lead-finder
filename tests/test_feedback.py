from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from leadfinder.db import connect, create_or_skip_lead
from leadfinder.feedback import crm_feedback_report


class CrmFeedbackReportTests(unittest.TestCase):
    def test_feedback_report_groups_by_country_query_family_and_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Buyer A",
                        "website": "https://a.example",
                        "country_region": "Germany",
                        "product_family": "roving",
                        "classification_status": "buyer",
                        "discovery_query": 'site:.de "glasfaser roving"',
                        "crm_outcome": "valid_customer",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Buyer B",
                        "website": "https://b.example",
                        "country_region": "Germany",
                        "product_family": "roving",
                        "classification_status": "buyer",
                        "discovery_query": 'site:.de "glasfaser roving"',
                        "crm_outcome": "no_response",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Buyer C",
                        "website": "https://c.example",
                        "country_region": "France",
                        "product_family": "woven_fabric",
                        "classification_status": "distributor",
                        "discovery_query": 'site:.fr "tissu fibre de verre"',
                        "crm_outcome": "do_not_contact",
                    },
                )
                report = crm_feedback_report(db)
            finally:
                db.close()

        self.assertEqual(report["totals"]["rows"], 2)
        self.assertEqual(report["totals"]["leads"], 3)
        self.assertEqual(report["totals"]["valid_customer"], 1)
        self.assertEqual(report["totals"]["no_response"], 1)
        self.assertEqual(report["totals"]["do_not_contact"], 1)

        rows = {
            (row["country"], row["product_family"], row["classification_status"], row["discovery_query"]): row
            for row in report["rows"]
        }
        germany = rows[("Germany", "roving", "buyer", 'site:.de "glasfaser roving"')]
        self.assertEqual(germany["valid_customer"], 1)
        self.assertEqual(germany["no_response"], 1)
        self.assertEqual(germany["suggestion"], "prioritize_follow_up")

        france = rows[("France", "woven_fabric", "distributor", 'site:.fr "tissu fibre de verre"')]
        self.assertEqual(france["do_not_contact"], 1)
        self.assertEqual(france["suggestion"], "do_not_contact")


if __name__ == "__main__":
    unittest.main()
