from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cli import main
from leadfinder.db import connect, create_campaign_run, create_or_skip_lead, record_provider_event
from leadfinder.recall import recall_report


def _structured_serper_message(country: str, locale: str, product_family: str, query: str) -> str:
    return json.dumps(
        {
            "country": country,
            "locale": locale,
            "product_family": product_family,
            "query": query,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


class RecallReportTests(unittest.TestCase):
    def test_recall_report_uses_latest_run_and_groups_queries_and_leads(self) -> None:
        usa_query_1 = 'site:.us "fiberglass roving" "pultrusion"'
        usa_query_2 = '"fiberglass roving" "FRP" USA'
        germany_query = 'site:.de "glasfaser roving" "pultrusion"'

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                older_run = create_campaign_run(db, {"name": "older"})
                record_provider_event(
                    db,
                    older_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message=_structured_serper_message("Canada", "en-CA", "roving", '"fiberglass roving" Canada'),
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Older Buyer",
                        "website": "https://older.example",
                        "campaign_run_id": older_run["id"],
                        "country_region": "Canada",
                        "query_locale": "en-CA",
                        "product_family": "roving",
                        "status": "Qualified",
                    },
                )

                latest_run = create_campaign_run(db, {"name": "latest"})
                record_provider_event(
                    db,
                    latest_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message=_structured_serper_message("USA", "en-US", "roving", usa_query_1),
                )
                record_provider_event(
                    db,
                    latest_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message=_structured_serper_message("USA", "en-US", "roving", usa_query_2),
                )
                record_provider_event(
                    db,
                    latest_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message="query completed",
                )
                record_provider_event(
                    db,
                    latest_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="error",
                    cost_units=0,
                    message=_structured_serper_message("USA", "en-US", "roving", '"fiberglass roving" failed'),
                )
                record_provider_event(
                    db,
                    latest_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message=_structured_serper_message("Germany", "de-DE", "roving", germany_query),
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Qualified Buyer",
                        "website": "https://qualified.example",
                        "campaign_run_id": latest_run["id"],
                        "country_region": "USA",
                        "query_locale": "en-US",
                        "product_family": "roving",
                        "status": "Qualified",
                        "email": "sales@qualified.example",
                        "email_verification_status": "valid",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Rejected Buyer",
                        "website": "https://rejected.example",
                        "campaign_run_id": latest_run["id"],
                        "country_region": "USA",
                        "query_locale": "en-US",
                        "product_family": "roving",
                        "status": "Rejected",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "French Buyer",
                        "website": "https://france.example",
                        "campaign_run_id": latest_run["id"],
                        "country_region": "France",
                        "query_locale": "fr-FR",
                        "product_family": "woven_fabric",
                        "status": "Qualified",
                        "email": "bonjour@france.example",
                    },
                )

                report = recall_report(db)
            finally:
                db.close()

        self.assertEqual(report["run"]["id"], latest_run["id"])
        groups = {
            (group["country"], group["locale"], group["product_family"]): group
            for group in report["groups"]
        }

        usa_group = groups[("USA", "en-US", "roving")]
        self.assertEqual(usa_group["search_terms"], [usa_query_1, usa_query_2])
        self.assertEqual(usa_group["serper_queries"], 2)
        self.assertEqual(usa_group["leads_created"], 2)
        self.assertEqual(usa_group["qualified_count"], 1)
        self.assertEqual(usa_group["rejected_count"], 1)
        self.assertEqual(usa_group["valid_email_count"], 1)
        self.assertEqual(usa_group["qualified_per_query"], 0.5)

        germany_group = groups[("Germany", "de-DE", "roving")]
        self.assertEqual(germany_group["search_terms"], [germany_query])
        self.assertEqual(germany_group["serper_queries"], 1)
        self.assertEqual(germany_group["leads_created"], 0)
        self.assertEqual(germany_group["qualified_per_query"], 0)

        france_group = groups[("France", "fr-FR", "woven_fabric")]
        self.assertEqual(france_group["search_terms"], [])
        self.assertEqual(france_group["serper_queries"], 0)
        self.assertEqual(france_group["leads_created"], 1)
        self.assertEqual(france_group["qualified_count"], 1)
        self.assertEqual(france_group["valid_email_count"], 1)
        self.assertEqual(france_group["qualified_per_query"], 0)

        self.assertNotIn(("Canada", "en-CA", "roving"), groups)

    def test_cli_recall_report_outputs_requested_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            db = connect(db_path)
            try:
                requested_run = create_campaign_run(db, {"name": "requested"})
                record_provider_event(
                    db,
                    requested_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message=_structured_serper_message("Mexico", "es-MX", "mesh", '"fiberglass mesh" importer Mexico'),
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Mexico Buyer",
                        "website": "https://mexico.example",
                        "campaign_run_id": requested_run["id"],
                        "country_region": "Mexico",
                        "query_locale": "es-MX",
                        "product_family": "mesh",
                        "status": "Qualified",
                    },
                )
                latest_run = create_campaign_run(db, {"name": "latest"})
                record_provider_event(
                    db,
                    latest_run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message=_structured_serper_message("Germany", "de-DE", "roving", '"glasfaser roving" Deutschland'),
                )
            finally:
                db.close()

            original_db = os.environ.get("LEADFINDER_DB_PATH")
            os.environ["LEADFINDER_DB_PATH"] = str(db_path)
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    exit_code = main(["recall-report", "--run-id", str(requested_run["id"])])
            finally:
                if original_db is None:
                    os.environ.pop("LEADFINDER_DB_PATH", None)
                else:
                    os.environ["LEADFINDER_DB_PATH"] = original_db

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["run"]["id"], requested_run["id"])
        self.assertEqual(
            payload["groups"],
            [
                {
                    "country": "Mexico",
                    "locale": "es-MX",
                    "product_family": "mesh",
                    "search_terms": ['"fiberglass mesh" importer Mexico'],
                    "serper_queries": 1,
                    "leads_created": 1,
                    "qualified_count": 1,
                    "rejected_count": 0,
                    "valid_email_count": 0,
                    "qualified_per_query": 1.0,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
