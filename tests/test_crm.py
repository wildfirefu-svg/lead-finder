from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli import main
from leadfinder.crm import crm_status, infer_crm_outcome, pull_crm_feedback, sync_verified_qualified
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

    def test_pull_crm_feedback_matches_by_email_domain_and_company(self) -> None:
        def fake_request(base_url, path, *, method="GET", payload=None, timeout=0):
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/api/leads")
            return {
                "leads": [
                    {
                        "company_name": "Email Match Co",
                        "email": "buyer@emailmatch.example",
                        "status": "Replied",
                        "last_contacted_at": "2026-06-12T09:00:00Z",
                        "notes": "",
                    },
                    {
                        "company_name": "Domain Match Co",
                        "website": "https://domainmatch.example/about",
                        "status": "Sent",
                        "last_contacted_at": "2026-06-10T08:00:00Z",
                        "notes": "",
                    },
                    {
                        "company_name": "Company Match Co",
                        "status": "Drafted",
                        "notes": "wrong_market",
                    },
                    {
                        "company_name": "Ignored Co",
                        "email": "ignore@example.com",
                        "status": "Unsubscribed",
                        "unsubscribed_at": "2026-06-11T01:00:00Z",
                        "notes": "",
                    },
                ]
            }

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Email Match Co",
                        "website": "https://emailmatch.example",
                        "email": "buyer@emailmatch.example",
                        "crm_sync_status": "synced",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Different Company",
                        "website": "https://domainmatch.example/contact",
                        "crm_sync_status": "synced",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Company Match Co",
                        "website": "https://companymatch.example",
                        "crm_sync_status": "duplicate",
                    },
                )
                result = None
                with patch("leadfinder.crm._request_json", fake_request):
                    result = pull_crm_feedback(db, "http://127.0.0.1:5173")
                rows = {lead["website"]: lead for lead in list_leads(db, limit=None)}
            finally:
                db.close()

        self.assertEqual(result["matched"], 3)
        self.assertEqual(result["updated"], 3)
        self.assertEqual(result["unmatched"], 0)
        self.assertEqual(result["outcomes"]["valid_customer"], 1)
        self.assertEqual(result["outcomes"]["duplicate"], 1)
        self.assertEqual(result["outcomes"]["wrong_market"], 0)
        self.assertEqual(rows["https://emailmatch.example"]["crm_followup_status"], "Replied")
        self.assertEqual(rows["https://emailmatch.example"]["crm_last_contact_at"], "2026-06-12T09:00:00Z")
        self.assertEqual(rows["https://emailmatch.example"]["crm_outcome"], "valid_customer")
        self.assertEqual(rows["https://domainmatch.example/contact"]["crm_outcome"], "no_response")
        self.assertEqual(rows["https://companymatch.example"]["crm_outcome"], "duplicate")

    def test_infer_crm_outcome_prefers_explicit_notes_and_unsubscribe(self) -> None:
        self.assertEqual(
            infer_crm_outcome({"status": "Drafted", "notes": "customer tagged as not_buyer"}, {}),
            "not_buyer",
        )
        self.assertEqual(
            infer_crm_outcome({"status": "Unsubscribed", "notes": ""}, {}),
            "do_not_contact",
        )
        self.assertEqual(
            infer_crm_outcome({"status": "Sent", "last_contacted_at": "2026-06-10T08:00:00Z", "notes": ""}, {}),
            "no_response",
        )

    def test_cli_sync_crm_outputs_summary_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "CLI Buyer",
                        "website": "https://cli.example",
                        "email": "buyer@cli.example",
                        "status": "Qualified",
                        "email_verification_status": "valid",
                    },
                )
            finally:
                db.close()

            original_db = os.environ.get("LEADFINDER_DB_PATH")
            original_crm = os.environ.get("LEADFINDER_CRM_URL")
            os.environ["LEADFINDER_DB_PATH"] = str(db_path)
            os.environ["LEADFINDER_CRM_URL"] = "http://127.0.0.1:5173"
            output = io.StringIO()
            try:
                with patch(
                    "cli.sync_verified_qualified",
                    return_value={
                        "attempted": 1,
                        "synced": 1,
                        "duplicates": 0,
                        "errors": 0,
                        "skipped_unverified": 0,
                    },
                ) as mocked_sync:
                    with redirect_stdout(output):
                        exit_code = main(["sync-crm", "--limit", "10"])
            finally:
                if original_db is None:
                    os.environ.pop("LEADFINDER_DB_PATH", None)
                else:
                    os.environ["LEADFINDER_DB_PATH"] = original_db
                if original_crm is None:
                    os.environ.pop("LEADFINDER_CRM_URL", None)
                else:
                    os.environ["LEADFINDER_CRM_URL"] = original_crm

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["synced"], 1)
        mocked_sync.assert_called_once()

    def test_sanitize_error_redacts_query_and_known_secret(self) -> None:
        with patch.dict("os.environ", {"HUNTER_API_KEY": "real-secret"}):
            message = sanitize_error(
                "https://api.example?api_key=real-secret&token=abc real-secret"
            )

        self.assertNotIn("real-secret", message)
        self.assertNotIn("token=abc", message)
        self.assertIn("[redacted]", message)

    def test_crm_status_retries_transient_network_error_once(self) -> None:
        calls = {"count": 0}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({"status": {"ok": True}}).encode("utf-8")

        def fake_urlopen(request, timeout=0):
            calls["count"] += 1
            if calls["count"] == 1:
                raise urllib.error.URLError(socket.gaierror("temporary failure"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            payload = crm_status("http://127.0.0.1:5173")

        self.assertEqual(calls["count"], 2)
        self.assertTrue(payload["available"])


if __name__ == "__main__":
    unittest.main()
