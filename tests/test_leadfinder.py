from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from leadfinder.classifier import classify_company_site
from leadfinder.db import connect, create_or_skip_lead, list_leads, update_lead
from leadfinder.enrich import (
    clean_company_name,
    extract_emails,
    extract_phones,
    fetch_text,
    normalize_domain,
    normalize_url,
    strip_html,
)
from leadfinder.exporter import CRM_FIELDS, export_csv
from leadfinder.market_fit import validate_target_market
from leadfinder.scoring import score_lead
from leadfinder.serper import build_queries, results_to_leads


class LeadFinderTests(unittest.TestCase):
    def test_csv_export_fields_match_crm_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sourced_leads.csv"
            export_csv(
                [
                    {
                        "source_type": "Website",
                        "source_name": "Serper: test",
                        "company_name": "Example Composites",
                        "country_region": "USA",
                        "market_region": "USA",
                        "website": "https://example.com",
                        "source_url": "https://example.com",
                        "contact_name": "",
                        "email": "sales@example.com",
                        "industry": "fiberglass composites",
                        "product_fit": "Both",
                        "fit_reason": "Matched keywords: fiberglass",
                        "match_score": 80,
                        "notes": "Imported from test",
                        "raw_text": "fiberglass fabric and roving",
                    }
                ],
                path,
            )

            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, CRM_FIELDS)
                row = next(reader)
                self.assertEqual(row["company_name"], "Example Composites")
                self.assertEqual(row["product_fit"], "Both")

    def test_email_extraction_ignores_image_like_false_positive(self) -> None:
        self.assertEqual(extract_emails("sales@buyer.com logo@2x.png"), ["sales@buyer.com"])

    def test_email_extraction_ignores_placeholder_addresses(self) -> None:
        self.assertEqual(
            extract_emails("contoso@example.com test@example.net sales@buyer.example"),
            ["sales@buyer.example"],
        )

    def test_phone_extraction_keeps_reasonable_business_numbers(self) -> None:
        phones = extract_phones("Call +1 555 123 4567 or order 123.")
        self.assertIn("+1 555 123 4567", phones)

    def test_url_and_domain_normalization(self) -> None:
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_domain("https://www.example.com/path"), "example.com")

    def test_strip_html_removes_scripts_and_tags(self) -> None:
        self.assertEqual(strip_html("<script>x()</script><p>Fiberglass&nbsp;fabric</p>"), "Fiberglass fabric")

    def test_fetch_text_retries_then_falls_back_to_http(self) -> None:
        calls: list[str] = []

        class Headers:
            def get(self, key, default=""):
                return "text/html" if key == "Content-Type" else default

            def get_content_charset(self):
                return "utf-8"

        class Response:
            headers = Headers()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def read(self, limit):
                return b"<html>ok</html>"

            def geturl(self):
                return "http://example.com"

        def fake_urlopen(request, timeout=12.0):
            calls.append(request.full_url)
            if request.full_url.startswith("https://"):
                raise urllib.error.URLError("certificate verify failed")
            return Response()

        with patch("urllib.request.urlopen", fake_urlopen):
            markup, final_url = fetch_text("https://example.com", retries=1)

        self.assertEqual(markup, "<html>ok</html>")
        self.assertEqual(final_url, "http://example.com")
        self.assertEqual(calls, ["https://example.com", "https://example.com", "http://example.com"])

    def test_company_name_prefers_site_brand_and_domain_over_page_title(self) -> None:
        self.assertEqual(
            clean_company_name("Home - V-ROD fiberglass rebars", ["V-ROD"], [], "https://vrod.ca"),
            "V-ROD",
        )
        self.assertEqual(
            clean_company_name("Home - V-ROD fiberglass rebars", [], [], "https://vrod.ca"),
            "Vrod",
        )

    def test_scoring_identifies_yarn_fit(self) -> None:
        scored = score_lead({"raw_text": "Manufacturer of FRP pipe using fiberglass roving and filament winding."})
        self.assertEqual(scored["product_fit"], "Fiberglass Yarn")
        self.assertGreaterEqual(scored["match_score"], 30)

    def test_scoring_identifies_fabric_fit(self) -> None:
        scored = score_lead({"raw_text": "Supplier of fiberglass fabric, woven roving, and mesh fabric."})
        self.assertEqual(scored["product_fit"], "Fiberglass Fabric")
        self.assertGreaterEqual(scored["match_score"], 30)

    def test_scoring_rewards_bill_of_lading_buyer_evidence(self) -> None:
        scored = score_lead(
            {
                "source_type": "Bill of Lading",
                "notes": "Evidence: public bill-of-lading/import record",
                "raw_text": "Consignee imported HS 7019 fiberglass woven roving from China.",
                "website": "https://buyer.example",
                "company_name": "Example Buyer",
            }
        )
        self.assertGreaterEqual(scored["match_score"], 60)

    def test_scoring_rewards_verified_saas_contact(self) -> None:
        scored = score_lead(
            {
                "source_type": "SaaS Contact",
                "source_name": "Snov.io",
                "email": "sales@example.com",
                "raw_text": "Composite distributor buying fiberglass fabric.",
                "website": "https://buyer.example",
                "company_name": "Example Distributor",
            }
        )
        self.assertGreaterEqual(scored["match_score"], 55)

    def test_scoring_penalizes_directory_search_results(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "company_name": "Fiberglass Roving Mat Importers | Zauba",
                "website": "https://www.zauba.com/Buyers-of-fiberglass-roving-mat",
                "raw_text": "Fiberglass roving importer buyer shipment import data directory.",
            }
        )

        self.assertLess(scored["match_score"], 50)
        evidence = json.loads(scored["score_evidence"])
        self.assertTrue(
            any(item["reason"] == "directory or marketplace source" for item in evidence["penalties"])
        )

    def test_scoring_rewards_downstream_manufacturer_fit(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "company_name": "Example Pultrusion",
                "website": "https://pultrusion.example",
                "raw_text": "About us: composites manufacturer and pultrusion manufacturer using fiberglass roving for FRP products. Contact us for capabilities.",
            }
        )

        self.assertGreaterEqual(scored["match_score"], 70)

    def test_scoring_rewards_frp_application_terms(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "company_name": "FRP Products",
                "website": "https://frp.example",
                "raw_text": "FRP grating, fiberglass rebar, pultruded profiles, fiberglass reinforced plastic products.",
            }
        )

        self.assertGreaterEqual(scored["match_score"], 50)

    def test_scoring_returns_structured_evidence(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "country_region": "USA",
                "company_name": "Example Pultrusion",
                "website": "https://buyer.example",
                "raw_text": "Pultrusion manufacturer using fiberglass roving. Contact us.",
            }
        )

        evidence = json.loads(scored["score_evidence"])
        self.assertTrue(any(item["reason"] == "yarn terms" for item in evidence["additions"]))
        self.assertTrue(any(item["reason"] == "company website" for item in evidence["additions"]))
        self.assertEqual(evidence["penalties"], [])
        self.assertIn("+", scored["fit_reason"])

    def test_scoring_penalizes_social_and_pdf_noise(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "company_name": "Mechanics & Composite Material PDF",
                "website": "https://school.example/mechanics-of-composite-material.pdf",
                "raw_text": "School of aeronautics lecture notes PDF about composites and fiberglass roving.",
            }
        )

        self.assertLess(scored["match_score"], 50)

    def test_scoring_does_not_penalize_company_site_for_social_links_in_notes(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "company_name": "FRP Products",
                "website": "https://fibertech.co.in/frp-grp-grating.html",
                "notes": "Social: https://www.facebook.com/example; https://www.linkedin.com/company/example",
                "raw_text": "FRP grating, FRP pipe, fiberglass reinforced plastic products. Contact us.",
            }
        )

        self.assertGreaterEqual(scored["match_score"], 50)
        self.assertNotIn("directory or marketplace", scored["fit_reason"])

    def test_scoring_penalizes_target_country_mismatch(self) -> None:
        scored = score_lead(
            {
                "source_type": "Website",
                "country_region": "USA",
                "company_name": "China Wholesale C-Glass Fiber Roving Factories",
                "website": "https://supplier.example",
                "raw_text": "China wholesale factories selling fiberglass roving and composites.",
            }
        )

        self.assertLess(scored["match_score"], 50)
        self.assertIn("target-country mismatch", scored["fit_reason"])

    def test_classifier_passes_downstream_customer_sites(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Custom pultrusions, FRP profiles, pultrusion capabilities, request a quote.",
                "website": "https://customer.example",
            }
        )

        self.assertTrue(classification["passed"])
        self.assertEqual(classification["category"], "downstream_customer")

    def test_classifier_returns_normalized_manufacturer_label_and_explanation(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Pultrusion manufacturer making FRP profiles. Contact us for capabilities.",
                "website": "https://buyer.example",
            }
        )

        self.assertTrue(classification["passed"])
        self.assertEqual(classification["category"], "downstream_customer")
        self.assertEqual(classification["label"], "manufacturer")
        self.assertIn("downstream usage evidence", classification["explanation"])
        self.assertIn("pultrusion manufacturer", classification["evidence"])

    def test_classifier_returns_buyer_label_without_manufacturer_evidence(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Custom pultrusions and FRP profiles. Contact us for capabilities.",
                "website": "https://buyer.example",
            }
        )

        self.assertTrue(classification["passed"])
        self.assertEqual(classification["category"], "downstream_customer")
        self.assertEqual(classification["label"], "buyer")

    def test_classifier_preserves_distributor_label(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Stocking distributor of fiberglass supplies. Request a quote.",
                "website": "https://distributor.example",
            }
        )

        self.assertTrue(classification["passed"])
        self.assertEqual(classification["category"], "distributor_or_importer")
        self.assertEqual(classification["label"], "distributor")

    def test_classifier_returns_supplier_label_and_explanation(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Fiberglass roving manufacturer and exporter with roving factory production.",
                "website": "https://supplier.example",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["label"], "supplier")
        self.assertIn("supplier/manufacturer source", classification["explanation"])

    def test_classifier_passes_pultrusion_application_sites(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Pultrusion company serving Canadian FRP applications.",
                "website": "https://www.pultrusion.ca/",
            }
        )

        self.assertTrue(classification["passed"])
        self.assertEqual(classification["category"], "downstream_customer")

    def test_classifier_rejects_roving_supplier_sites(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Fiberglass roving manufacturer, direct roving manufacturer, roving factory, exporter.",
                "website": "https://supplier.example",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "supplier")

    def test_classifier_rejects_roving_supplier_with_application_terms(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": (
                    "Fiberglass manufacturer and exporter selling direct roving "
                    "for pultrusion and filament winding."
                ),
                "website": "https://supplier.example",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "supplier")

    def test_classifier_rejects_roving_producer(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "23 years of experience in fiberglass roving production.",
                "website": "https://supplier.example",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "supplier")

    def test_classifier_rejects_china_roving_product_page(self) -> None:
        classification = classify_company_site(
            {
                "company_name": "China Direct Roving For Filament Winding Factory",
                "raw_text": "Choosing the right fiberglass roving for your application.",
                "website": "https://supplier.example/product",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "supplier")

    def test_classifier_rejects_chinese_roving_catalog(self) -> None:
        classification = classify_company_site(
            {
                "company_name": "Fiberglass Products",
                "raw_text": (
                    "Call +86-13933702587. Products include fiberglass spray up roving, "
                    "fiberglass woven roving, and fiberglass chopped strand mat."
                ),
                "website": "https://supplier.example/products",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "supplier")

    def test_classifier_rejects_supplier_ranking_articles(self) -> None:
        classification = classify_company_site(
            {
                "company_name": "Top 10 Carbon Fiber Suppliers in the USA",
                "raw_text": "Top 10 supplier guide with FRP profiles and fiberglass products.",
                "website": "https://supplier.example/blog/top-10",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "noise")

    def test_classifier_rejects_market_reports(self) -> None:
        classification = classify_company_site(
            {
                "raw_text": "Fiberglass roving market report and market size forecast.",
                "website": "https://report.example",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "noise")

    def test_classifier_rejects_government_research_documents(self) -> None:
        classification = classify_company_site(
            {
                "company_name": "Pultrusion Process Development for Long Space Boom Model",
                "website": "https://ntrs.nasa.gov/citations/19900013312",
                "raw_text": "NASA technical document from a government research center about fiberglass roving pultrusion.",
            }
        )

        self.assertFalse(classification["passed"])
        self.assertEqual(classification["category"], "noise")

    def test_market_fit_passes_canada_evidence(self) -> None:
        fit = validate_target_market(
            {
                "country_region": "Canada",
                "website": "https://buyer.ca",
                "raw_text": "Composite products distributor in Ontario, Canada.",
            },
            "Canada",
        )

        self.assertTrue(fit["passed"])

    def test_market_fit_rejects_us_company_for_canada(self) -> None:
        fit = validate_target_market(
            {
                "country_region": "Canada",
                "website": "https://american.example",
                "raw_text": "American FRP products manufacturer in Nevada, United States.",
            },
            "Canada",
        )

        self.assertFalse(fit["passed"])

    def test_market_fit_passes_canadian_domain_with_brand_noise(self) -> None:
        fit = validate_target_market(
            {
                "country_region": "Canada",
                "website": "https://www.fibergrate.ca/products/molded-gratings/",
                "raw_text": "American brand name, FRP grating products for Canadian customers.",
            },
            "Canada",
        )

        self.assertTrue(fit["passed"])

    def test_market_fit_passes_usa_evidence(self) -> None:
        fit = validate_target_market(
            {
                "country_region": "USA",
                "website": "https://buyer.example",
                "raw_text": "FRP profiles manufacturer in Wisconsin, United States. Contact us.",
            },
            "USA",
        )

        self.assertTrue(fit["passed"])

    def test_market_fit_passes_usa_city_evidence(self) -> None:
        fit = validate_target_market(
            {
                "country_region": "USA",
                "website": "https://buyer.example",
                "raw_text": "Pultrusion manufacturer located in Pittsburgh.",
            },
            "USA",
        )

        self.assertTrue(fit["passed"])

    def test_market_fit_passes_germany_local_evidence(self) -> None:
        fit = validate_target_market(
            {
                "country_region": "Germany",
                "website": "https://kunde.de",
                "raw_text": "GFK pultrusion company in Deutschland.",
            },
            "Germany",
        )

        self.assertTrue(fit["passed"])

    def test_market_fit_rejects_missing_germany_evidence(self) -> None:
        fit = validate_target_market(
            {
                "country_region": "Germany",
                "website": "https://buyer.fr",
                "raw_text": "Composite company in France.",
            },
            "Germany",
        )

        self.assertFalse(fit["passed"])

    def test_db_dedupes_by_domain_email_and_company(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                first, created = create_or_skip_lead(
                    db,
                    {
                        "company_name": "Example Composites",
                        "website": "https://www.example.com/products",
                        "email": "sales@example.com",
                    },
                )
                by_domain, domain_created = create_or_skip_lead(
                    db,
                    {
                        "company_name": "Different Name",
                        "website": "https://example.com/contact",
                    },
                )
                by_email, email_created = create_or_skip_lead(
                    db,
                    {
                        "company_name": "Email Duplicate",
                        "email": "sales@example.com",
                    },
                )
                by_company, company_created = create_or_skip_lead(
                    db,
                    {
                        "company_name": "example composites",
                        "website": "https://other.example",
                    },
                )
            finally:
                db.close()

        self.assertTrue(created)
        self.assertFalse(domain_created)
        self.assertFalse(email_created)
        self.assertFalse(company_created)
        self.assertEqual(first["id"], by_domain["id"])
        self.assertEqual(first["id"], by_email["id"])
        self.assertEqual(first["id"], by_company["id"])

    def test_db_persists_evidence_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                created, was_created = create_or_skip_lead(
                    db,
                    {
                        "company_name": "Evidence Buyer",
                        "website": "https://buyer.example",
                        "classification_status": "buyer",
                        "classification_evidence": "downstream usage evidence",
                        "score_evidence": '{"additions":[],"penalties":[],"matched_terms":[]}',
                        "review_status": "high_confidence",
                    },
                )
                rows = list_leads(db)
            finally:
                db.close()

        self.assertTrue(was_created)
        self.assertEqual(created["classification_status"], "buyer")
        self.assertEqual(rows[0]["classification_evidence"], "downstream usage evidence")
        self.assertEqual(rows[0]["review_status"], "high_confidence")
        self.assertEqual(
            rows[0]["score_evidence"],
            '{"additions":[],"penalties":[],"matched_terms":[]}',
        )

    def test_db_migrates_existing_lead_for_evidence_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leadfinder.sqlite"
            legacy_db = sqlite3.connect(path)
            try:
                legacy_db.executescript(
                    """
                    CREATE TABLE leads (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      source_type TEXT NOT NULL DEFAULT 'Website',
                      source_name TEXT NOT NULL DEFAULT '',
                      company_name TEXT NOT NULL DEFAULT '',
                      country_region TEXT NOT NULL DEFAULT '',
                      market_region TEXT NOT NULL DEFAULT '',
                      website TEXT NOT NULL DEFAULT '',
                      website_domain TEXT NOT NULL DEFAULT '',
                      source_url TEXT NOT NULL DEFAULT '',
                      contact_name TEXT NOT NULL DEFAULT '',
                      email TEXT NOT NULL DEFAULT '',
                      industry TEXT NOT NULL DEFAULT '',
                      product_fit TEXT NOT NULL DEFAULT 'Both',
                      fit_reason TEXT NOT NULL DEFAULT '',
                      match_score INTEGER NOT NULL DEFAULT 0,
                      status TEXT NOT NULL DEFAULT 'Discovered',
                      crawl_status TEXT NOT NULL DEFAULT '',
                      classification_status TEXT NOT NULL DEFAULT '',
                      market_fit_status TEXT NOT NULL DEFAULT '',
                      email_verification_status TEXT NOT NULL DEFAULT '',
                      crm_sync_status TEXT NOT NULL DEFAULT '',
                      notes TEXT NOT NULL DEFAULT '',
                      raw_text TEXT NOT NULL DEFAULT '',
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT INTO leads (
                      company_name,
                      website,
                      website_domain,
                      classification_status
                    ) VALUES (
                      'Legacy Buyer',
                      'https://legacy.example',
                      'legacy.example',
                      'buyer'
                    );
                    """
                )
                legacy_db.commit()
            finally:
                legacy_db.close()

            db = connect(path)
            try:
                rows = list_leads(db)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["company_name"], "Legacy Buyer")
                self.assertEqual(rows[0]["classification_evidence"], "")
                self.assertEqual(rows[0]["score_evidence"], "")
                self.assertEqual(rows[0]["review_status"], "")

                update_lead(
                    db,
                    rows[0]["id"],
                    {
                        "classification_evidence": "legacy downstream evidence",
                        "score_evidence": '{"additions":["legacy"],"penalties":[],"matched_terms":[]}',
                        "review_status": "reviewed",
                    },
                )
                updated = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(
            updated["classification_evidence"],
            "legacy downstream evidence",
        )
        self.assertEqual(
            updated["score_evidence"],
            '{"additions":["legacy"],"penalties":[],"matched_terms":[]}',
        )
        self.assertEqual(updated["review_status"], "reviewed")

    def test_serper_payload_maps_to_leads_for_offline_discovery(self) -> None:
        payload = {
            "organic": [
                {
                    "title": "Example Fiberglass Distributor",
                    "link": "https://buyer.example",
                    "snippet": "Fiberglass fabric and yarn importer.",
                }
            ]
        }
        leads = results_to_leads(payload, "USA", '"fiberglass fabric" importer USA')
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["country_region"], "USA")
        self.assertEqual(leads[0]["website"], "https://buyer.example")

    def test_serper_payload_skips_directory_discovery_domains(self) -> None:
        payload = {
            "organic": [
                {
                    "title": "Fiberglass Roving Mat Importers | Zauba",
                    "link": "https://www.zauba.com/Buyers-of-fiberglass-roving-mat",
                    "snippet": "Import data directory.",
                },
                {
                    "title": "Fiberglass Reinforced Plastic Products",
                    "link": "https://www.facebook.com/groups/example/posts/123",
                    "snippet": "Social post mentioning fiberglass roving.",
                },
                {
                    "title": "Mechanics of composite material",
                    "link": "https://school.example/mechanics-of-composite-material.pdf",
                    "snippet": "Lecture notes mentioning fiberglass roving.",
                },
                {
                    "title": "China's Glass Fibre Market Overview",
                    "link": "https://www.indexbox.io/blog/glass-fibre-market-overview/",
                    "snippet": "Market report mentioning fiberglass roving.",
                },
                {
                    "title": "Pultrusion Process Development for Long Space Boom Model",
                    "link": "https://ntrs.nasa.gov/citations/19900013312",
                    "snippet": "NASA technical document mentioning fiberglass roving.",
                },
                {
                    "title": "Wholesale Fiberglass",
                    "link": "https://www.okorder.com/gl_Morocco/Solar-Inverter/",
                    "snippet": "Marketplace page mentioning fiberglass roving.",
                },
                {
                    "title": "Example Pultrusion",
                    "link": "https://pultrusion.example",
                    "snippet": "Pultrusion manufacturer using fiberglass roving.",
                },
            ]
        }

        leads = results_to_leads(payload, "USA", '"fiberglass roving" "pultrusion" manufacturer USA')

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["company_name"], "Example Pultrusion")

    def test_build_queries_covers_both_product_lines(self) -> None:
        queries = build_queries("USA", "both")
        self.assertTrue(any("roving" in query for query in queries))
        self.assertTrue(any("fabric" in query for query in queries))
        self.assertTrue(all("-site:zauba.com" in query for query in queries))
        self.assertTrue(all("-site:facebook.com" in query for query in queries))
        self.assertTrue(all("-site:instagram.com" in query for query in queries))
        self.assertTrue(all("-site:indexbox.io" in query for query in queries))
        self.assertTrue(all("-filetype:pdf" in query for query in queries))
        self.assertTrue(any("pultrusion" in query for query in queries))

    def test_build_queries_prefers_canada_localized_terms(self) -> None:
        queries = build_queries("Canada", "yarn")

        self.assertIn('site:.ca "FRP grating" "contact"', queries[0])
        self.assertTrue(any("fiberglass rebar" in query for query in queries))
        self.assertTrue(any("Ontario" in query for query in queries))
        self.assertTrue(all("-site:zauba.com" in query for query in queries))
        self.assertTrue(all("-site:marketresearch.com" in query for query in queries))
        self.assertTrue(all("-site:scribd.com" in query for query in queries))
        self.assertTrue(all("-site:nasa.gov" in query for query in queries))
        self.assertTrue(all("-site:okorder.com" in query for query in queries))

    def test_build_queries_uses_local_language_for_germany(self) -> None:
        queries = build_queries("Germany", "yarn")

        self.assertTrue(any("glasfaser" in query.lower() for query in queries))
        self.assertTrue(any("GFK" in query for query in queries))
        self.assertTrue(all("-site:datainsightsreports.com" in query for query in queries))

    def test_build_queries_uses_local_language_for_morocco(self) -> None:
        queries = build_queries("Morocco", "yarn")

        self.assertIn('site:.ma "fibre de verre" "composite"', queries[0])
        self.assertTrue(any("Maroc" in query for query in queries))
        self.assertTrue(all("-site:okorder.com" in query for query in queries))

    def test_build_queries_keeps_legacy_string_interface(self) -> None:
        queries = build_queries("Germany", "roving", hs_code="701912")

        self.assertTrue(queries)
        self.assertTrue(all(isinstance(query, str) for query in queries))
        self.assertTrue(any("glasfaser" in query.lower() for query in queries))

    def test_build_queries_supports_explicit_yarn_family(self) -> None:
        queries = build_queries("Canada", "yarn", hs_code="701913")

        self.assertTrue(queries)
        self.assertTrue(any("glass fiber yarn" in query.lower() for query in queries))
        self.assertFalse(any("Ontario" in query for query in queries))

    def test_build_queries_keeps_legacy_yarn_behavior_for_roving_hs(self) -> None:
        queries = build_queries("Germany", "yarn", hs_code="701912")

        self.assertTrue(queries)
        self.assertTrue(any("pultrusion" in query.lower() for query in queries))
        self.assertTrue(any("glasfaser" in query.lower() for query in queries))

    def test_build_queries_keeps_legacy_yarn_behavior_without_hs_override(self) -> None:
        queries = build_queries("Germany", "yarn")

        self.assertTrue(queries)
        self.assertTrue(any("pultrusion" in query.lower() for query in queries))
        self.assertTrue(any("glasfaser" in query.lower() for query in queries))

    def test_mocked_discovery_rows_can_be_inserted_and_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                payload = {
                    "organic": [
                        {
                            "title": "Example Pultrusion",
                            "link": "https://pultrusion.example",
                            "snippet": "Pultrusion manufacturer using fiberglass roving.",
                        }
                    ]
                }
                for lead in results_to_leads(payload, "USA", "mock query"):
                    create_or_skip_lead(db, {**lead, **score_lead(lead)})
                rows = list_leads(db)
            finally:
                db.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_fit"], "Fiberglass Yarn")


if __name__ == "__main__":
    unittest.main()
