from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from leadfinder.contact_enrichment import enrich_qualified_emails, verify_existing_qualified_emails
from leadfinder.db import connect, create_or_skip_lead, list_leads


class FakeHunter:
    def domain_search(self, domain: str) -> dict:
        return {"data": {"emails": [{"value": f"sales@{domain}", "confidence": 95}]}}

    def verify_email(self, email: str) -> dict:
        return {"data": {"status": "valid", "score": 98}}


class InvalidHunter(FakeHunter):
    def verify_email(self, email: str) -> dict:
        return {"data": {"status": "invalid", "score": 10}}


class ContactEnrichmentTests(unittest.TestCase):
    def test_enriches_only_qualified_leads_with_valid_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Qualified Buyer",
                        "website": "https://buyer.example",
                        "status": "Qualified",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Unreviewed Lead",
                        "website": "https://unreviewed.example",
                        "status": "Discovered",
                    },
                )
                result = enrich_qualified_emails(db, FakeHunter(), limit=5)
                rows = {lead["company_name"]: lead for lead in list_leads(db)}
            finally:
                db.close()

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(rows["Qualified Buyer"]["email"], "sales@buyer.example")
        self.assertEqual(rows["Unreviewed Lead"]["email"], "")

    def test_does_not_store_invalid_hunter_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Qualified Buyer",
                        "website": "https://buyer.example",
                        "status": "Qualified",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                result = enrich_qualified_emails(db, InvalidHunter(), limit=5)
                lead = list_leads(db)[0]
            finally:
                db.close()

        self.assertEqual(result["emails_found"], 1)
        self.assertEqual(result["verified"], 0)
        self.assertEqual(lead["email"], "")
        self.assertIn("Hunter verification: invalid", lead["notes"])

    def test_skips_domains_already_searched_by_hunter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Qualified Buyer",
                        "website": "https://buyer.example",
                        "status": "Qualified",
                        "notes": "Hunter domain search: no email returned",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                result = enrich_qualified_emails(db, FakeHunter(), limit=5)
            finally:
                db.close()

        self.assertEqual(result["attempted"], 0)

    def test_verifies_existing_qualified_emails_without_domain_search(self) -> None:
        class VerifyOnlyHunter(FakeHunter):
            def __init__(self) -> None:
                self.domain_calls = 0

            def domain_search(self, domain: str) -> dict:
                self.domain_calls += 1
                return super().domain_search(domain)

        hunter = VerifyOnlyHunter()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Qualified Buyer",
                        "website": "https://buyer.example",
                        "email": "sales@buyer.example",
                        "status": "Qualified",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Already Verified",
                        "website": "https://verified.example",
                        "email": "sales@verified.example",
                        "status": "Qualified",
                        "email_verification_status": "valid",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                result = verify_existing_qualified_emails(db, hunter, limit=5)
                rows = {lead["company_name"]: lead for lead in list_leads(db)}
            finally:
                db.close()

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["valid"], 1)
        self.assertEqual(hunter.domain_calls, 0)
        self.assertEqual(rows["Qualified Buyer"]["email_verification_status"], "valid")
        self.assertEqual(rows["Already Verified"]["email_verification_status"], "valid")

    def test_hunter_enrichment_skips_supplier_unknown_and_crawl_failures(self) -> None:
        class CountingHunter(FakeHunter):
            def __init__(self) -> None:
                self.domain_calls = 0

            def domain_search(self, domain: str) -> dict:
                self.domain_calls += 1
                return super().domain_search(domain)

        hunter = CountingHunter()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Eligible Buyer",
                        "website": "https://buyer.example",
                        "status": "Qualified",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Supplier",
                        "website": "https://supplier.example",
                        "status": "Qualified",
                        "match_score": 85,
                        "classification_status": "supplier",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Unknown",
                        "website": "https://unknown.example",
                        "status": "Qualified",
                        "match_score": 80,
                        "classification_status": "unknown",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Crawl Failed",
                        "website": "https://failed.example",
                        "status": "Qualified",
                        "match_score": 80,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "error",
                    },
                )
                result = enrich_qualified_emails(db, hunter, limit=10)
                rows = {lead["company_name"]: lead for lead in list_leads(db)}
            finally:
                db.close()

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(hunter.domain_calls, 1)
        self.assertEqual(rows["Eligible Buyer"]["email"], "sales@buyer.example")
        self.assertEqual(rows["Supplier"]["email"], "")
        self.assertEqual(rows["Unknown"]["email"], "")
        self.assertEqual(rows["Crawl Failed"]["email"], "")

    def test_existing_email_verification_uses_same_credit_gate(self) -> None:
        class CountingHunter(FakeHunter):
            def __init__(self) -> None:
                self.verify_calls = 0

            def verify_email(self, email: str) -> dict:
                self.verify_calls += 1
                return super().verify_email(email)

        hunter = CountingHunter()
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / "leadfinder.sqlite")
            try:
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Eligible Buyer",
                        "website": "https://buyer.example",
                        "email": "sales@buyer.example",
                        "status": "Qualified",
                        "match_score": 75,
                        "classification_status": "buyer",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                create_or_skip_lead(
                    db,
                    {
                        "company_name": "Supplier",
                        "website": "https://supplier.example",
                        "email": "sales@supplier.example",
                        "status": "Qualified",
                        "match_score": 85,
                        "classification_status": "supplier",
                        "market_fit_status": "passed",
                        "crawl_status": "ok",
                    },
                )
                result = verify_existing_qualified_emails(db, hunter, limit=10)
                rows = {lead["company_name"]: lead for lead in list_leads(db)}
            finally:
                db.close()

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["valid"], 1)
        self.assertEqual(hunter.verify_calls, 1)
        self.assertEqual(rows["Eligible Buyer"]["email_verification_status"], "valid")
        self.assertEqual(rows["Supplier"]["email_verification_status"], "")


if __name__ == "__main__":
    unittest.main()
