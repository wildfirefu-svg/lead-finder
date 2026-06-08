from __future__ import annotations

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

    def test_quality_report_counts_classified_buyers_and_excludes_rejected(self) -> None:
        report = quality_report(
            [
                {
                    "source_type": "Website",
                    "status": "Discovered",
                    "match_score": 70,
                    "website": "https://buyer.example",
                    "fit_reason": "Site classification: downstream_customer confidence=80 passed=True",
                },
                {
                    "source_type": "Website",
                    "status": "Rejected",
                    "match_score": 90,
                    "website": "https://noise.example",
                    "fit_reason": "Site classification: downstream_customer confidence=70 passed=True",
                },
            ],
            min_score=50,
        )

        self.assertEqual(report["total"], 1)
        self.assertEqual(report["with_buyer_evidence"], 1)
        self.assertEqual(report["high_quality"], 1)


if __name__ == "__main__":
    unittest.main()
