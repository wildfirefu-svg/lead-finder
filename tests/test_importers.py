from __future__ import annotations

import os
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
            original_env = os.environ.get("LEADFINDER_DB_PATH")
            os.environ["LEADFINDER_DB_PATH"] = str(db_path)
            try:
                exit_code = main(["import-csv", "--input", str(csv_path), "--source", "Apollo.io"])
            finally:
                if original_env is None:
                    os.environ.pop("LEADFINDER_DB_PATH", None)
                else:
                    os.environ["LEADFINDER_DB_PATH"] = original_env

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
