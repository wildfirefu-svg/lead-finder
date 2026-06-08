from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from leadfinder.crm import sync_verified_qualified
from leadfinder.db import connect, create_or_skip_lead, list_leads
from leadfinder.security import sanitize_error


class CrmSyncTests(unittest.TestCase):
    def test_syncs_only_verified_qualified_leads(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_request(base_url, path, *, method="GET", payload=None, timeout):
            calls.append((method, path))
            if path == "/api/sourced-leads/import-csv":
                self.assertEqual(len(payload["csv_text"].splitlines()), 2)
                return {"created": [{"id": 7}], "skipped": []}
            return {"lead": {"id": 9}, "sourced_lead": {"id": 7}, "duplicate": False}

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Verified Buyer",
                        "website": "https://verified.example",
                        "email": "buyer@verified.example",
                        "status": "Qualified",
                        "email_verification_status": "valid",
                        "notes": "Hunter verification: valid\nSecond line",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Unverified Buyer",
                        "website": "https://unverified.example",
                        "email": "info@unverified.example",
                        "status": "Qualified",
                    },
                )
                with patch("leadfinder.crm._request_json", fake_request):
                    result = sync_verified_qualified(db, "http://127.0.0.1:5173")
                rows = {lead["company_name"]: lead for lead in list_leads(db)}
            finally:
                db.close()

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["skipped_unverified"], 1)
        self.assertEqual(rows["Verified Buyer"]["crm_sync_status"], "synced")
        self.assertEqual(rows["Unverified Buyer"]["crm_sync_status"], "")
        self.assertEqual(
            calls,
            [
                ("POST", "/api/sourced-leads/import-csv"),
                ("POST", "/api/sourced-leads/7/import"),
            ],
        )

    def test_sanitize_error_redacts_query_and_known_secret(self) -> None:
        with patch.dict("os.environ", {"HUNTER_API_KEY": "real-secret"}):
            message = sanitize_error(
                "https://api.example?api_key=real-secret&token=abc real-secret"
            )

        self.assertNotIn("real-secret", message)
        self.assertNotIn("token=abc", message)
        self.assertIn("[redacted]", message)


if __name__ == "__main__":
    unittest.main()
