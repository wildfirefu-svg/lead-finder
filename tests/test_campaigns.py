from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from leadfinder.config import settings
from leadfinder.db import (
    connect,
    create_campaign_run,
    finish_campaign_run,
    list_campaign_runs,
    list_leads,
    list_provider_events,
    record_provider_event,
)
from leadfinder.campaigns import CampaignOptions, _enrich_optional, run_campaign


class CampaignSettingsTests(unittest.TestCase):
    def test_settings_loads_apollo_and_hunter_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "APOLLO_API_KEY=apollo-key\n"
                "HUNTER_API_KEY=hunter-key\n",
                encoding="utf-8",
            )
            original_apollo = os.environ.pop("APOLLO_API_KEY", None)
            original_hunter = os.environ.pop("HUNTER_API_KEY", None)
            try:
                cfg = settings(env_path)
            finally:
                if original_apollo is not None:
                    os.environ["APOLLO_API_KEY"] = original_apollo
                else:
                    os.environ.pop("APOLLO_API_KEY", None)
                if original_hunter is not None:
                    os.environ["HUNTER_API_KEY"] = original_hunter
                else:
                    os.environ.pop("HUNTER_API_KEY", None)

        self.assertEqual(cfg.apollo_api_key, "apollo-key")
        self.assertEqual(cfg.hunter_api_key, "hunter-key")

    def test_settings_loads_comtrade_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "COMTRADE_API_KEY=primary-key\n"
                "COMTRADE_API_KEY_SECONDARY=secondary-key\n",
                encoding="utf-8",
            )
            original_primary = os.environ.pop("COMTRADE_API_KEY", None)
            original_secondary = os.environ.pop("COMTRADE_API_KEY_SECONDARY", None)
            try:
                cfg = settings(env_path)
            finally:
                if original_primary is not None:
                    os.environ["COMTRADE_API_KEY"] = original_primary
                else:
                    os.environ.pop("COMTRADE_API_KEY", None)
                if original_secondary is not None:
                    os.environ["COMTRADE_API_KEY_SECONDARY"] = original_secondary
                else:
                    os.environ.pop("COMTRADE_API_KEY_SECONDARY", None)

        self.assertEqual(cfg.comtrade_api_key, "primary-key")
        self.assertEqual(cfg.comtrade_api_key_secondary, "secondary-key")


class CampaignDbTests(unittest.TestCase):
    def test_campaign_run_and_provider_events_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run = create_campaign_run(
                    db,
                    {
                        "name": "HS7019 both",
                        "hs_code": "7019",
                        "year": 2024,
                        "product": "both",
                        "market_limit": 2,
                        "per_market_limit": 5,
                        "providers": ["Comtrade", "Serper"],
                        "quality_before": {"total": 0},
                    },
                )
                record_provider_event(
                    db,
                    run["id"],
                    provider="Serper",
                    event_type="search",
                    status="ok",
                    cost_units=1,
                    message="query completed",
                )
                finish_campaign_run(
                    db,
                    run["id"],
                    status="Completed",
                    created=3,
                    skipped=1,
                    errors=0,
                    quality_after={"total": 3},
                )
                runs = list_campaign_runs(db)
                events = list_provider_events(db, run["id"])
            finally:
                db.close()

        self.assertEqual(runs[0]["status"], "Completed")
        self.assertEqual(runs[0]["created"], 3)
        self.assertEqual(json.loads(runs[0]["quality_before"])["total"], 0)
        self.assertEqual(json.loads(runs[0]["quality_after"])["total"], 3)
        self.assertEqual(events[0]["provider"], "Serper")
        self.assertEqual(events[0]["cost_units"], 1)


class FakeSerperClient:
    def search(self, query: str, num: int = 10) -> dict:
        return {
            "organic": [
                {
                    "title": "Example Fiberglass Buyer",
                    "link": "https://buyer.example",
                    "snippet": "Importer of HS 7019 fiberglass roving and fabric.",
                }
            ]
        }


class MixedQualitySerperClient:
    def search(self, query: str, num: int = 10) -> dict:
        return {
            "organic": [
                {
                    "title": "Dictionary definition",
                    "link": "https://weak.example",
                    "snippet": "Dictionary page.",
                },
                {
                    "title": "Example Pultrusion",
                    "link": "https://pultrusion.example",
                    "snippet": "About us: composites manufacturer and pultrusion manufacturer using fiberglass roving for FRP products. Contact us for capabilities.",
                },
            ]
        }


class WeakSnippetSerperClient:
    def search(self, query: str, num: int = 10) -> dict:
        return {
            "organic": [
                {
                    "title": "Local FRP Products",
                    "link": "https://localfrp.example",
                    "snippet": "Fiberglass composite FRP grating and contact information.",
                }
            ]
        }


class RecordingSerperClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, num: int = 10) -> dict:
        self.queries.append(query)
        return {"organic": []}


class UniqueLeadSerperClient:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, num: int = 10) -> dict:
        self.calls += 1
        return {
            "organic": [
                {
                    "title": f"Example Pultrusion {self.calls}",
                    "link": f"https://buyer{self.calls}.example",
                    "snippet": "Custom pultrusions, FRP profiles, pultrusion capabilities, contact us.",
                }
            ]
        }


class FakeApolloClient:
    def people_search(self, company: str, country: str = "", per_page: int = 3) -> dict:
        return {"people": [{"name": "Jane Buyer", "title": "Purchasing Manager"}]}


class TrackingApolloClient(FakeApolloClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def people_search(self, company: str, country: str = "", per_page: int = 3) -> dict:
        self.calls.append((company, country))
        return super().people_search(company, country, per_page)


class FakeHunterClient:
    def domain_search(self, domain: str) -> dict:
        return {"data": {"emails": [{"value": "sales@buyer.example", "confidence": 92}]}}

    def verify_email(self, email: str) -> dict:
        return {"data": {"status": "valid", "score": 95}}


class TrackingHunterClient(FakeHunterClient):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def domain_search(self, domain: str) -> dict:
        self.calls.append(domain)
        return super().domain_search(domain)

class InvalidHunterClient(FakeHunterClient):
    def verify_email(self, email: str) -> dict:
        return {"data": {"status": "invalid", "score": 10}}


def passthrough_site_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    return defaults or {"website": url}


def downstream_site_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    lead = {**(defaults or {}), "website": url}
    lead["raw_text"] = (
        f"{lead.get('raw_text', '')} About us: custom pultrusions, FRP profiles, "
        "pultrusion capabilities, contact us, request a quote. Wisconsin United States."
    )
    return lead


def partial_downstream_site_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    return {
        **downstream_site_enricher(url, defaults),
        "crawl_status": "partial",
    }


def supplier_site_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    lead = {**(defaults or {}), "website": url}
    lead["raw_text"] = (
        f"{lead.get('raw_text', '')} Fiberglass roving manufacturer, direct roving manufacturer, "
        "roving factory, exporter."
    )
    return lead


def failing_site_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    raise RuntimeError("crawl blocked")


def error_status_site_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    return {**(defaults or {}), "website": url, "crawl_status": "error"}


def us_site_for_canada_enricher(url: str, defaults: dict | None = None, **_: object) -> dict:
    lead = {**(defaults or {}), "website": url}
    lead["raw_text"] = (
        f"{lead.get('raw_text', '')} Custom pultrusions, FRP profiles, pultrusion capabilities. "
        "Nevada United States."
    )
    return lead


class CountingSiteEnricher:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url: str, defaults: dict | None = None, **_: object) -> dict:
        self.calls += 1
        return downstream_site_enricher(url, defaults)


class CampaignRunnerTests(unittest.TestCase):
    def test_campaign_runs_with_fallback_markets_and_fake_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="7019",
                        year=2024,
                        product="both",
                        market_limit=1,
                        per_market_limit=1,
                        min_score=50,
                        use_serper=True,
                        use_apollo=True,
                        use_hunter=True,
                    ),
                    fetch_markets=lambda hs_code, year, timeout: (_ for _ in ()).throw(RuntimeError("offline")),
                    serper_client=FakeSerperClient(),
                    apollo_client=FakeApolloClient(),
                    hunter_client=FakeHunterClient(),
                    site_enricher=downstream_site_enricher,
                )
                rows = list_leads(db)
                runs = list_campaign_runs(db)
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["status"], "Completed")
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contact_name"], "Jane Buyer")
        self.assertEqual(rows[0]["email"], "sales@buyer.example")
        self.assertEqual(len(runs), 1)
        self.assertTrue(any(event["provider"] == "Comtrade" and event["status"] == "fallback" for event in events))
        self.assertIn("quality_before", result)
        self.assertIn("quality_after", result)

    def test_campaign_does_not_store_invalid_hunter_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="7019",
                        product="both",
                        target_countries=("USA",),
                        per_market_limit=1,
                        min_score=50,
                        use_serper=True,
                        use_hunter=True,
                    ),
                    serper_client=FakeSerperClient(),
                    hunter_client=InvalidHunterClient(),
                    site_enricher=downstream_site_enricher,
                )
                lead = list_leads(db)[0]
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        hunter_event = next(event for event in events if event["provider"] == "Hunter.io")
        self.assertEqual(lead["email"], "")
        self.assertIn("Hunter verification: invalid", lead["notes"])
        self.assertEqual(hunter_event["cost_units"], 2.0)

    def test_campaign_skips_missing_provider_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(use_serper=True, use_apollo=True, use_hunter=True),
                    fetch_markets=lambda hs_code, year, timeout: [],
                    serper_client=None,
                    apollo_client=None,
                    hunter_client=None,
                )
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["created"], 0)
        self.assertTrue(any(event["provider"] == "Serper" and event["status"] == "skipped" for event in events))
        self.assertTrue(any(event["provider"] == "Apollo.io" and event["status"] == "skipped" for event in events))
        self.assertTrue(any(event["provider"] == "Hunter.io" and event["status"] == "skipped" for event in events))

    def test_campaign_uses_selected_countries_without_comtrade(self) -> None:
        def fail_fetch_markets(hs_code: str, year: int, timeout: float) -> list[dict]:
            raise AssertionError("selected countries should bypass Comtrade")

        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        year=2024,
                        product="both",
                        market_limit=1,
                        per_market_limit=1,
                        target_countries=("USA",),
                        use_serper=True,
                    ),
                    fetch_markets=fail_fetch_markets,
                    serper_client=FakeSerperClient(),
                    site_enricher=downstream_site_enricher,
                )
                rows = list_leads(db)
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["status"], "Completed")
        self.assertEqual(result["created"], 1)
        self.assertEqual(rows[0]["country_region"], "USA")
        self.assertTrue(any(event["provider"] == "Region Selection" and event["status"] == "ok" for event in events))
        self.assertFalse(any(event["provider"] == "Comtrade" for event in events))

    def test_campaign_skips_serper_results_below_min_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        year=2024,
                        product="yarn",
                        market_limit=1,
                        per_market_limit=2,
                        target_countries=("USA",),
                        min_score=50,
                        use_serper=True,
                    ),
                    serper_client=MixedQualitySerperClient(),
                    site_enricher=passthrough_site_enricher,
                )
                rows = list_leads(db)
            finally:
                db.close()

        self.assertEqual(result["created"], 1)
        self.assertGreaterEqual(result["skipped"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["company_name"], "Example Pultrusion")

    def test_campaign_allows_weak_snippet_when_site_crawl_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="yarn",
                        target_countries=("USA",),
                        min_score=50,
                        use_serper=True,
                    ),
                    serper_client=WeakSnippetSerperClient(),
                    site_enricher=downstream_site_enricher,
                )
                rows = list_leads(db)
            finally:
                db.close()

        self.assertEqual(result["created"], 1)
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["match_score"], 50)
        self.assertEqual(rows[0]["status"], "Qualified")
        self.assertEqual(rows[0]["classification_status"], "buyer")
        self.assertTrue(rows[0]["classification_evidence"])
        self.assertIsInstance(json.loads(rows[0]["score_evidence"]), dict)
        self.assertEqual(rows[0]["review_status"], "high_confidence")

    def test_campaign_accepts_partial_crawl_and_runs_paid_enrichment(self) -> None:
        hunter = TrackingHunterClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="yarn",
                        target_countries=("USA",),
                        min_score=50,
                        use_serper=True,
                        use_hunter=True,
                    ),
                    serper_client=FakeSerperClient(),
                    hunter_client=hunter,
                    site_enricher=partial_downstream_site_enricher,
                )
                rows = list_leads(db)
            finally:
                db.close()

        self.assertEqual(result["created"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "Qualified")
        self.assertEqual(rows[0]["classification_status"], "buyer")
        self.assertEqual(rows[0]["crawl_status"], "partial")
        self.assertEqual(rows[0]["review_status"], "high_confidence")
        self.assertEqual(rows[0]["email"], "sales@buyer.example")
        self.assertEqual(hunter.calls, ["buyer.example"])

    def test_campaign_skips_supplier_sites_before_contact_enrichment(self) -> None:
        hunter = TrackingHunterClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        year=2024,
                        product="yarn",
                        market_limit=1,
                        per_market_limit=1,
                        target_countries=("USA",),
                        min_score=50,
                        use_serper=True,
                        use_hunter=True,
                    ),
                    serper_client=FakeSerperClient(),
                    hunter_client=hunter,
                    site_enricher=supplier_site_enricher,
                )
                rows = list_leads(db)
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["created"], 0)
        self.assertEqual(rows, [])
        self.assertEqual(hunter.calls, [])
        self.assertTrue(any(event["provider"] == "Site Classifier" and event["status"] == "skipped" for event in events))

    def test_campaign_skips_crawl_failures_before_contact_enrichment(self) -> None:
        hunter = TrackingHunterClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        year=2024,
                        product="yarn",
                        target_countries=("USA",),
                        use_serper=True,
                        use_hunter=True,
                    ),
                    serper_client=FakeSerperClient(),
                    hunter_client=hunter,
                    site_enricher=failing_site_enricher,
                )
                rows = list_leads(db)
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["created"], 0)
        self.assertEqual(rows, [])
        self.assertEqual(hunter.calls, [])
        self.assertTrue(any(event["provider"] == "Site Classifier" and event["status"] == "error" for event in events))

    def test_campaign_skips_explicit_crawl_error_before_paid_enrichment(self) -> None:
        apollo = TrackingApolloClient()
        hunter = TrackingHunterClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="yarn",
                        target_countries=("USA",),
                        use_serper=True,
                        use_apollo=True,
                        use_hunter=True,
                    ),
                    serper_client=FakeSerperClient(),
                    apollo_client=apollo,
                    hunter_client=hunter,
                    site_enricher=error_status_site_enricher,
                )
                rows = list_leads(db)
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(rows, [])
        self.assertEqual(apollo.calls, [])
        self.assertEqual(hunter.calls, [])
        self.assertTrue(
            any(
                event["provider"] == "Site Classifier"
                and event["event_type"] == "crawl"
                and event["status"] == "error"
                for event in events
            )
        )

    def test_optional_enrichment_refuses_lead_that_fails_evidence_gate(self) -> None:
        apollo = TrackingApolloClient()
        hunter = TrackingHunterClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run = create_campaign_run(db, {"name": "evidence gate"})
                _enrich_optional(
                    db,
                    {
                        "id": 1,
                        "company_name": "Unverified Buyer",
                        "country_region": "USA",
                        "website": "https://buyer.example",
                        "status": "Qualified",
                        "match_score": 90,
                        "classification_status": "buyer",
                        "market_fit_status": "failed",
                        "crawl_status": "ok",
                    },
                    CampaignOptions(use_apollo=True, use_hunter=True),
                    apollo,
                    hunter,
                    run["id"],
                )
            finally:
                db.close()

        self.assertEqual(apollo.calls, [])
        self.assertEqual(hunter.calls, [])

    def test_campaign_skips_country_mismatch_before_contact_enrichment(self) -> None:
        hunter = TrackingHunterClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="yarn",
                        target_countries=("Canada",),
                        use_serper=True,
                        use_hunter=True,
                    ),
                    serper_client=FakeSerperClient(),
                    hunter_client=hunter,
                    site_enricher=us_site_for_canada_enricher,
                )
                rows = list_leads(db)
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        self.assertEqual(result["created"], 0)
        self.assertEqual(rows, [])
        self.assertEqual(hunter.calls, [])
        self.assertTrue(any(event["provider"] == "Market Fit" and event["status"] == "skipped" for event in events))

    def test_campaign_maps_specific_roving_hs_to_yarn_queries(self) -> None:
        client = RecordingSerperClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="both",
                        target_countries=("USA",),
                        use_serper=True,
                    ),
                    serper_client=client,
                )
            finally:
                db.close()

        self.assertTrue(client.queries)
        self.assertTrue(any("pultrusion" in query for query in client.queries))
        self.assertFalse(any("fiberglass fabric" in query for query in client.queries))

    def test_campaign_persists_recall_metadata_on_leads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="both",
                        target_countries=("USA",),
                        per_market_limit=1,
                        use_serper=True,
                    ),
                    serper_client=FakeSerperClient(),
                    site_enricher=downstream_site_enricher,
                )
                leads = list_leads(db, campaign_run_id=result["run_id"])
                other_run_leads = list_leads(db, campaign_run_id=result["run_id"] + 1)
            finally:
                db.close()

        self.assertEqual(len(leads), 1)
        self.assertEqual(other_run_leads, [])
        self.assertEqual(leads[0]["campaign_run_id"], result["run_id"])
        self.assertEqual(leads[0]["query_locale"], "en-US")
        self.assertEqual(leads[0]["product_family"], "roving")
        self.assertIn("pultrusion", leads[0]["discovery_query"])

    def test_campaign_records_structured_serper_event_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="both",
                        target_countries=("USA",),
                        per_market_limit=1,
                        use_serper=True,
                    ),
                    serper_client=RecordingSerperClient(),
                )
                events = list_provider_events(db, result["run_id"])
            finally:
                db.close()

        serper_event = next(event for event in events if event["provider"] == "Serper")
        message = json.loads(serper_event["message"])
        self.assertEqual(message["country"], "USA")
        self.assertEqual(message["locale"], "en-US")
        self.assertEqual(message["product_family"], "roving")
        self.assertIn("pultrusion", message["query"])

    def test_campaign_keeps_query_budget_independent_per_country(self) -> None:
        client = RecordingSerperClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="both",
                        target_countries=("USA", "Canada"),
                        per_market_limit=1,
                        use_serper=True,
                    ),
                    serper_client=client,
                )
            finally:
                db.close()

        self.assertEqual(len(client.queries), 2)
        self.assertTrue(any("USA" in query for query in client.queries))
        self.assertTrue(any("Canada" in query or "site:.ca" in query for query in client.queries))

    def test_campaign_skips_duplicates_before_site_crawl(self) -> None:
        enricher = CountingSiteEnricher()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                from leadfinder.db import create_or_skip_lead

                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Existing Buyer",
                        "website": "https://buyer.example",
                        "match_score": 80,
                    },
                )
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="yarn",
                        target_countries=("USA",),
                        use_serper=True,
                    ),
                    serper_client=FakeSerperClient(),
                    site_enricher=enricher,
                )
                rows = list_leads(db)
            finally:
                db.close()

        self.assertEqual(result["created"], 0)
        self.assertGreaterEqual(result["skipped"], 1)
        self.assertEqual(enricher.calls, 0)
        self.assertEqual(len(rows), 1)

    def test_campaign_stops_searching_market_after_per_market_limit(self) -> None:
        client = UniqueLeadSerperClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                result = run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701912",
                        product="yarn",
                        target_countries=("USA",),
                        per_market_limit=1,
                        use_serper=True,
                    ),
                    serper_client=client,
                    site_enricher=downstream_site_enricher,
                )
                rows = list_leads(db)
            finally:
                db.close()

        self.assertEqual(result["created"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(client.calls, 1)

    def test_campaign_limits_queries_for_small_market_sample(self) -> None:
        client = RecordingSerperClient()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                run_campaign(
                    db,
                    CampaignOptions(
                        hs_code="701919",
                        product="yarn",
                        target_countries=("Morocco",),
                        per_market_limit=1,
                        use_serper=True,
                    ),
                    serper_client=client,
                )
            finally:
                db.close()

        self.assertEqual(len(client.queries), 1)
        self.assertTrue(all("Morocco" in query or "Maroc" in query or "site:.ma" in query for query in client.queries))


class CampaignCliTests(unittest.TestCase):
    def test_cli_campaign_runs_without_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "leadfinder.sqlite"
            original_db = os.environ.get("LEADFINDER_DB_PATH")
            original_serper = os.environ.pop("SERPER_API_KEY", None)
            original_apollo = os.environ.pop("APOLLO_API_KEY", None)
            original_hunter = os.environ.pop("HUNTER_API_KEY", None)
            os.environ["LEADFINDER_DB_PATH"] = str(db_path)
            try:
                from cli import main

                exit_code = main(["campaign", "--market-limit", "1", "--per-market-limit", "1", "--no-serper"])
            finally:
                if original_db is None:
                    os.environ.pop("LEADFINDER_DB_PATH", None)
                else:
                    os.environ["LEADFINDER_DB_PATH"] = original_db
                if original_serper is not None:
                    os.environ["SERPER_API_KEY"] = original_serper
                if original_apollo is not None:
                    os.environ["APOLLO_API_KEY"] = original_apollo
                if original_hunter is not None:
                    os.environ["HUNTER_API_KEY"] = original_hunter

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
