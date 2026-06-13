from __future__ import annotations

import io
import ssl
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path

from leadfinder.db import connect, create_run_log, record_run_usage
from leadfinder.stability import budget_snapshot, call_with_limited_retry


class StabilityTests(unittest.TestCase):
    def test_budget_snapshot_reports_run_and_daily_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run_log = create_run_log(db, "campaign", metadata={"name": "budget-test"})
                record_run_usage(
                    db,
                    run_log["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=2.0,
                    message="query-1",
                )
                record_run_usage(
                    db,
                    run_log["id"],
                    provider="Hunter.io",
                    event_type="verify_email",
                    status="ok",
                    cost_units=1.0,
                    message="buyer@example.com",
                )

                cfg = types.SimpleNamespace(
                    serper_run_limit=5.0,
                    serper_daily_limit=10.0,
                    apollo_run_limit=3.0,
                    apollo_daily_limit=8.0,
                    hunter_run_limit=4.0,
                    hunter_daily_limit=6.0,
                )

                snapshot = budget_snapshot(db, cfg, run_log["id"])
            finally:
                db.close()

        self.assertEqual(snapshot["Serper"]["run_used"], 2.0)
        self.assertEqual(snapshot["Serper"]["daily_used"], 2.0)
        self.assertEqual(snapshot["Serper"]["run_remaining"], 3.0)
        self.assertEqual(snapshot["Hunter.io"]["run_used"], 1.0)
        self.assertEqual(snapshot["Hunter.io"]["daily_remaining"], 5.0)
        self.assertEqual(snapshot["Apollo.io"]["run_used"], 0.0)
        self.assertEqual(snapshot["Apollo.io"]["daily_remaining"], 8.0)

    def test_call_with_limited_retry_retries_http_5xx_once(self) -> None:
        calls = {"count": 0}

        def flaky_operation():
            calls["count"] += 1
            if calls["count"] == 1:
                raise urllib.error.HTTPError("https://example.com", 503, "retry", {}, io.BytesIO(b""))
            return "ok"

        result = call_with_limited_retry(flaky_operation, retries=1)

        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 2)

    def test_call_with_limited_retry_does_not_retry_http_4xx(self) -> None:
        calls = {"count": 0}

        def failing_operation():
            calls["count"] += 1
            raise urllib.error.HTTPError("https://example.com", 404, "not found", {}, io.BytesIO(b""))

        with self.assertRaises(urllib.error.HTTPError):
            call_with_limited_retry(failing_operation, retries=1)

        self.assertEqual(calls["count"], 1)

    def test_call_with_limited_retry_does_not_retry_ssl_verification_error(self) -> None:
        calls = {"count": 0}

        def ssl_failure():
            calls["count"] += 1
            raise ssl.SSLCertVerificationError("certificate verify failed")

        with self.assertRaises(ssl.SSLCertVerificationError):
            call_with_limited_retry(ssl_failure, retries=1)

        self.assertEqual(calls["count"], 1)


if __name__ == "__main__":
    unittest.main()
