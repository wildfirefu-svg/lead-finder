from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from leadfinder.db import (
    connect,
    create_campaign_run,
    create_or_skip_lead,
    list_leads,
    record_provider_event,
)
from leadfinder.webapp import make_app


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "leadfinder.sqlite"

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

    def test_homepage_returns_workbench_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            status, headers, body = app.handle("GET", "/", b"")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        html = body.decode("utf-8")
        self.assertIn("玻纤外贸获客工作台", html)
        self.assertIn(b"/api/leads", body)
        self.assertIn("开始自动搜寻", html)
        self.assertIn("批量复核旧线索", html)
        self.assertIn("补全合格线索邮箱", html)
        self.assertIn("验证已有邮箱", html)
        self.assertIn("701912", html)
        self.assertIn("北美", html)

    def test_homepage_includes_accuracy_review_filters(self) -> None:
        app = make_app(self.db_path)
        status, headers, body = app.handle("GET", "/", b"")
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn("高置信 Qualified", html)
        self.assertIn("待人工复核", html)
        self.assertIn("疑似供应商误判", html)
        self.assertIn("抓取失败", html)

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

    def test_api_leads_decorates_score_evidence(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "Explained Buyer",
                    "score_evidence": json.dumps(
                        {
                            "additions": [
                                {"points": 20, "reason": "buyer language", "terms": ["fiberglass"]}
                            ],
                            "penalties": [
                                {"points": -10, "reason": "supplier language", "terms": ["manufacturer"]}
                            ],
                        }
                    ),
                },
            )
        finally:
            db.close()

        status, _, body = make_app(self.db_path).handle("GET", "/api/leads", b"")
        lead = json.loads(body.decode("utf-8"))["leads"][0]

        self.assertEqual(status, 200)
        self.assertIn("+20 buyer language: fiberglass", lead["score_explanation"])
        self.assertIn("-10 supplier language: manufacturer", lead["score_explanation"])

    def test_api_review_filter_applies_limit_after_filtering(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "First Nonmatch",
                    "status": "Qualified",
                    "match_score": 90,
                    "review_status": "high_confidence",
                },
            )
            create_or_skip_lead(
                db,
                {
                    "company_name": "Later Match",
                    "status": "Discovered",
                    "match_score": 40,
                    "review_status": "needs_review",
                },
            )
        finally:
            db.close()

        status, _, body = make_app(self.db_path).handle(
            "GET",
            "/api/leads?review=needs_review&limit=1",
            b"",
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual([lead["company_name"] for lead in payload["leads"]], ["Later Match"])

    def test_api_campaign_runs_without_serper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            status, headers, body = app.handle(
                "POST",
                "/api/campaign",
                json.dumps(
                    {
                        "hs_code": "7019",
                        "year": 2024,
                        "product": "both",
                        "target_countries": ["USA"],
                        "per_market_limit": 1,
                        "use_serper": False,
                        "use_apollo": False,
                        "use_hunter": False,
                    }
                ).encode("utf-8"),
            )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["result"]["status"], "Completed")
        self.assertIn("quality_after", payload["result"])

    def test_api_provider_state_reports_key_availability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            status, headers, body = app.handle("GET", "/api/provider-state", b"")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body.decode("utf-8"))
        self.assertIn("serper", payload)
        self.assertIn("apollo", payload)
        self.assertIn("hunter", payload)

    def test_api_stats_counts_qualified_emails_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Qualified Buyer",
                        "website": "https://buyer.example",
                        "email": "sales@buyer.example",
                        "status": "Qualified",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Rejected Supplier",
                        "website": "https://supplier.example",
                        "email": "sales@supplier.example",
                        "status": "Rejected",
                    },
                )
            finally:
                db.close()

            app = make_app(db_path)
            status, _, body = app.handle("GET", "/api/stats", b"")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["qualified_with_email"], 1)

    def test_api_export_qualified_excludes_other_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Qualified Buyer",
                        "website": "https://qualified.example",
                        "status": "Qualified",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Rejected Supplier",
                        "website": "https://rejected.example",
                        "status": "Rejected",
                    },
                )
            finally:
                db.close()

            status, headers, body = make_app(db_path).handle(
                "GET",
                "/api/export-qualified",
                b"",
            )

        text = body.decode("utf-8-sig")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("Qualified Buyer", text)
        self.assertNotIn("Rejected Supplier", text)

    def test_api_usage_returns_latest_campaign_provider_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                run = create_campaign_run(db, {"name": "test"})
                record_provider_event(
                    db,
                    run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=2,
                    message="test",
                )
            finally:
                db.close()

            status, _, body = make_app(db_path).handle("GET", "/api/usage", b"")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["usage"]["Serper"], 2.0)

    def test_api_crm_state_hides_connection_error_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            with patch("leadfinder.webapp.crm_status", side_effect=RuntimeError("api_key=secret")):
                status, _, body = app.handle("GET", "/api/crm-state", b"")

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertNotIn("secret", payload["error"])

    def test_api_requalify_returns_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            expected = {
                "reviewed": 2,
                "qualified": 1,
                "rejected": 1,
                "needs_review": 0,
                "errors": 0,
            }
            with patch("leadfinder.webapp.requalify_leads", return_value=expected):
                status, headers, body = app.handle(
                    "POST",
                    "/api/requalify",
                    json.dumps({"limit": 10, "only_unreviewed": True}).encode("utf-8"),
                )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(body.decode("utf-8"))["result"], expected)

    def test_api_enrich_qualified_requires_hunter_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            with patch("leadfinder.webapp.settings") as mocked_settings:
                mocked_settings.return_value.hunter_api_key = ""
                status, _, body = app.handle(
                    "POST",
                    "/api/enrich-qualified",
                    json.dumps({"limit": 5}).encode("utf-8"),
                )

        self.assertEqual(status, 400)
        self.assertIn("HUNTER_API_KEY missing", body.decode("utf-8"))

    def test_api_verify_qualified_emails_returns_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            expected = {
                "attempted": 1,
                "valid": 1,
                "invalid": 0,
                "other": 0,
                "errors": 0,
            }
            with patch("leadfinder.webapp.settings") as mocked_settings:
                mocked_settings.return_value.hunter_api_key = "hunter-key"
                mocked_settings.return_value.timeout_seconds = 3
                with patch("leadfinder.webapp.verify_existing_qualified_emails", return_value=expected):
                    status, _, body = app.handle(
                        "POST",
                        "/api/verify-qualified-emails",
                        json.dumps({"limit": 5}).encode("utf-8"),
                    )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["result"], expected)


if __name__ == "__main__":
    unittest.main()
