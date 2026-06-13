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
    finish_campaign_run,
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
                lead, _ = create_or_skip_lead(
                    db,
                    {
                        "company_name": "Example Buyer",
                        "website": "https://example.com",
                        "review_status": "high_confidence",
                    },
                )
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
        self.assertEqual(rows[0]["review_status"], "")

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
        self.assertIn("批量复核", html)
        self.assertIn("补全邮箱", html)
        self.assertIn("验证邮箱", html)
        self.assertIn("701912", html)
        self.assertIn("北美", html)

    def test_homepage_includes_accuracy_review_filters(self) -> None:
        app = make_app(self.db_path)
        status, headers, body = app.handle("GET", "/", b"")
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", html)
        self.assertIn('class="toolbar-group filters"', html)
        self.assertIn("function syncToolbarState()", html)
        self.assertIn("header { grid-template-columns: minmax(0, 1fr); padding: 18px; }", html)
        self.assertIn("高置信", html)
        self.assertIn("待复核", html)
        self.assertIn("供应商误判", html)
        self.assertIn("抓取失败", html)
        self.assertIn('id="previous-page"', html)
        self.assertIn('id="next-page"', html)
        self.assertIn("state.offset", html)
        self.assertIn("params.set('offset'", html)

    def test_homepage_includes_stage_b_product_family_options(self) -> None:
        app = make_app(self.db_path)
        status, _, body = app.handle("GET", "/", b"")
        html = body.decode("utf-8")

        self.assertEqual(status, 200)
        self.assertIn('option value="all">全部产品族</option>', html)
        self.assertIn('option value="roving">粗纱 / Roving</option>', html)
        self.assertIn('option value="woven_fabric">织物 / Woven Fabric</option>', html)
        self.assertIn('option value="mat">毡 / Mat</option>', html)
        self.assertIn("召回质量报告", html)
        self.assertIn('id="recall-report"', html)
        self.assertIn("function loadRecallReport", html)
        self.assertIn("await loadRecallReport(payload.result ? payload.result.run_id : '')", html)
        self.assertIn("loadRecallReport();", html)
        self.assertIn('id="pull-crm-feedback"', html)
        self.assertIn("拉取反馈", html)
        self.assertIn("CRM反馈总结", html)
        self.assertIn('id="crm-feedback-report"', html)
        self.assertIn("function loadCrmFeedbackReport", html)
        self.assertIn("function formatCampaignSummary", html)
        self.assertIn("function formatEnrichSummary", html)
        self.assertIn("function formatVerifySummary", html)
        self.assertIn("function formatPullFeedbackSummary", html)
        self.assertIn("function renderSummaryCard", html)
        self.assertIn('id="campaign-summary"', html)
        self.assertIn("summary-card", html)

    def test_api_leads_supports_review_filter(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "High Confidence",
                    "website": "https://qualified.example",
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

    def test_api_leads_recomputes_stale_persisted_review_status(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "Rejected Supplier",
                    "status": "Rejected",
                    "classification_status": "supplier",
                    "crawl_status": "ok",
                    "review_status": "high_confidence",
                },
            )
            create_or_skip_lead(
                db,
                {
                    "company_name": "Rejected Buyer",
                    "status": "Rejected",
                    "classification_status": "buyer",
                    "crawl_status": "ok",
                    "review_status": "high_confidence",
                },
            )
        finally:
            db.close()

        app = make_app(self.db_path)
        _, _, supplier_body = app.handle("GET", "/api/leads?review=suspected_supplier", b"")
        _, _, review_body = app.handle("GET", "/api/leads?review=needs_review", b"")
        _, _, high_body = app.handle("GET", "/api/leads?review=high_confidence", b"")

        self.assertEqual(
            [lead["company_name"] for lead in json.loads(supplier_body)["leads"]],
            ["Rejected Supplier"],
        )
        self.assertEqual(
            [lead["company_name"] for lead in json.loads(review_body)["leads"]],
            ["Rejected Buyer"],
        )
        self.assertEqual(json.loads(high_body)["leads"], [])

    def test_api_leads_rejects_unsupported_review_without_opening_database(self) -> None:
        app = make_app(self.db_path)

        with patch("leadfinder.webapp.connect") as mocked_connect:
            status, _, body = app.handle("GET", "/api/leads?review=unknown", b"")

        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body.decode("utf-8")), {"error": "invalid review"})
        mocked_connect.assert_not_called()

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

    def test_api_leads_returns_string_explanation_for_malformed_score_evidence(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "Legacy Buyer",
                    "score_evidence": json.dumps(
                        {
                            "additions": [
                                "legacy",
                                {"points": "many", "reason": "legacy", "terms": "abc"},
                            ],
                            "penalties": [None],
                        }
                    ),
                },
            )
        finally:
            db.close()

        status, _, body = make_app(self.db_path).handle("GET", "/api/leads", b"")
        lead = json.loads(body.decode("utf-8"))["leads"][0]

        self.assertEqual(status, 200)
        self.assertIsInstance(lead["score_explanation"], str)

    def test_api_review_filter_applies_limit_after_filtering(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "First Nonmatch",
                    "website": "https://qualified.example",
                    "status": "Qualified",
                    "match_score": 90,
                    "classification_status": "buyer",
                    "market_fit_status": "passed",
                    "crawl_status": "ok",
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

    def test_api_review_filter_finds_match_beyond_first_500_rows(self) -> None:
        db = connect(self.db_path)
        try:
            db.executemany(
                """
                INSERT INTO leads (company_name, status, match_score, review_status)
                VALUES (?, 'Qualified', 90, 'high_confidence')
                """,
                [(f"High Confidence {index:03d}",) for index in range(500)],
            )
            db.execute(
                """
                UPDATE leads
                SET website = 'https://qualified.example',
                    classification_status = 'buyer',
                    market_fit_status = 'passed',
                    crawl_status = 'ok'
                WHERE company_name LIKE 'High Confidence %'
                """
            )
            db.execute(
                """
                INSERT INTO leads (company_name, status, match_score, review_status)
                VALUES ('Match Beyond 500', 'Discovered', 40, 'needs_review')
                """
            )
            db.commit()
        finally:
            db.close()

        status, _, body = make_app(self.db_path).handle(
            "GET",
            "/api/leads?review=needs_review&limit=1",
            b"",
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual([lead["company_name"] for lead in payload["leads"]], ["Match Beyond 500"])

    def test_api_review_filter_scans_in_bounded_chunks(self) -> None:
        first_chunk = [
            {
                "company_name": f"Nonmatch {index:03d}",
                "status": "Qualified",
                "match_score": 90,
                "website": "https://qualified.example",
                "classification_status": "buyer",
                "market_fit_status": "passed",
                "crawl_status": "ok",
            }
            for index in range(500)
        ]
        second_chunk = [{"company_name": "Later Match", "status": "Discovered"}]
        app = make_app(self.db_path)

        with patch("leadfinder.webapp.list_leads", side_effect=[first_chunk, second_chunk]) as mocked_list:
            status, _, body = app.handle(
                "GET",
                "/api/leads?review=needs_review&limit=1",
                b"",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual([lead["company_name"] for lead in payload["leads"]], ["Later Match"])
        self.assertEqual(
            mocked_list.call_args_list,
            [
                unittest.mock.call(unittest.mock.ANY, status=None, limit=500, offset=0),
                unittest.mock.call(unittest.mock.ANY, status=None, limit=500, offset=500),
            ],
        )

    def test_api_leads_supports_result_offset_without_review_filter(self) -> None:
        db = connect(self.db_path)
        try:
            for name in ("First", "Second", "Third"):
                create_or_skip_lead(db, {"company_name": name})
        finally:
            db.close()

        status, _, body = make_app(self.db_path).handle(
            "GET",
            "/api/leads?limit=1&offset=1",
            b"",
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual([lead["company_name"] for lead in payload["leads"]], ["Second"])
        self.assertEqual(payload["offset"], 1)
        self.assertEqual(payload["limit"], 1)

    def test_api_review_filter_supports_result_offset_beyond_source_chunk(self) -> None:
        db = connect(self.db_path)
        try:
            db.executemany(
                """
                INSERT INTO leads (company_name, status, match_score)
                VALUES (?, 'Discovered', 40)
                """,
                [(f"Needs Review {index:03d}",) for index in range(502)],
            )
            db.commit()
        finally:
            db.close()

        status, _, body = make_app(self.db_path).handle(
            "GET",
            "/api/leads?review=needs_review&limit=500&offset=500",
            b"",
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(
            [lead["company_name"] for lead in payload["leads"]],
            ["Needs Review 001", "Needs Review 000"],
        )
        self.assertEqual(payload["offset"], 500)
        self.assertEqual(payload["limit"], 500)

    def test_api_leads_rejects_invalid_offset(self) -> None:
        app = make_app(self.db_path)

        for offset in ("", "invalid", "-1"):
            with self.subTest(offset=offset):
                status, _, body = app.handle("GET", f"/api/leads?offset={offset}", b"")
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body.decode("utf-8")), {"error": "invalid offset"})

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

    def test_api_recall_report_returns_rows(self) -> None:
        db = connect(self.db_path)
        try:
            run = create_campaign_run(db, {"name": "HS7019 recall", "hs_code": "7019"})
            record_provider_event(
                db,
                run["id"],
                provider="Serper",
                event_type="search",
                status="ok",
                cost_units=1,
                message='{"country":"Germany","locale":"de-DE","product_family":"roving","query":"demo"}',
            )
            create_or_skip_lead(
                db,
                {
                    "company_name": "Example Buyer",
                    "country_region": "Germany",
                    "website": "https://buyer.example",
                    "status": "Qualified",
                    "campaign_run_id": run["id"],
                    "query_locale": "de-DE",
                    "product_family": "roving",
                },
            )
            finish_campaign_run(db, run["id"], status="Completed", created=1, skipped=0, errors=0, quality_after={"total": 1})
        finally:
            db.close()

        app = make_app(self.db_path)
        status, headers, body = app.handle("GET", f"/api/recall-report?run_id={run['id']}", b"")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(payload["run"]["id"], run["id"])
        self.assertEqual(payload["rows"][0]["country"], "Germany")
        self.assertEqual(payload["rows"][0]["product_family"], "roving")
        self.assertEqual(payload["rows"][0]["qualified_count"], 1)

    def test_api_crm_state_hides_connection_error_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            with patch("leadfinder.webapp.crm_status", side_effect=RuntimeError("api_key=secret")):
                status, _, body = app.handle("GET", "/api/crm-state", b"")

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertNotIn("secret", payload["error"])

    def test_api_crm_feedback_report_returns_rows(self) -> None:
        db = connect(self.db_path)
        try:
            create_or_skip_lead(
                db,
                {
                    "company_name": "CRM Buyer",
                    "website": "https://crm.example",
                    "country_region": "Germany",
                    "product_family": "roving",
                    "classification_status": "buyer",
                    "discovery_query": "demo query",
                    "crm_outcome": "valid_customer",
                },
            )
        finally:
            db.close()

        status, headers, body = make_app(self.db_path).handle("GET", "/api/crm-feedback-report", b"")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(payload["rows"][0]["country"], "Germany")
        self.assertEqual(payload["rows"][0]["valid_customer"], 1)

    def test_api_pull_crm_feedback_returns_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp) / "leadfinder.sqlite")
            expected = {
                "matched": 2,
                "updated": 2,
                "unmatched": 0,
                "errors": 0,
                "outcomes": {"valid_customer": 1},
            }
            with patch("leadfinder.webapp.crm_status", return_value={"available": True}):
                with patch("leadfinder.webapp.pull_crm_feedback", return_value=expected):
                    status, headers, body = app.handle(
                        "POST",
                        "/api/pull-crm-feedback",
                        json.dumps({"limit": 50}).encode("utf-8"),
                    )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(body.decode("utf-8"))["result"], expected)

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
