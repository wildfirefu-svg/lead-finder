from __future__ import annotations

import unittest

from leadfinder.apollo import ApolloClient, apollo_people_to_contact
from leadfinder.hunter import HunterClient, hunter_domain_to_email, hunter_verification_note


class ApolloHunterTests(unittest.TestCase):
    def test_apollo_people_to_contact_maps_first_person(self) -> None:
        contact = apollo_people_to_contact(
            {
                "people": [
                    {
                        "name": "Jane Buyer",
                        "title": "Purchasing Manager",
                        "organization": {"name": "Example Composites"},
                    }
                ]
            }
        )

        self.assertEqual(contact["contact_name"], "Jane Buyer")
        self.assertIn("Purchasing Manager", contact["notes"])

    def test_hunter_domain_to_email_maps_best_email(self) -> None:
        email = hunter_domain_to_email(
            {
                "data": {
                    "emails": [
                        {"value": "info@example.com", "confidence": 60},
                        {"value": "sales@example.com", "confidence": 91},
                    ]
                }
            }
        )

        self.assertEqual(email["email"], "sales@example.com")
        self.assertIn("confidence=91", email["notes"])

    def test_hunter_prefers_purchasing_contact_over_generic_high_confidence_email(self) -> None:
        email = hunter_domain_to_email(
            {
                "data": {
                    "emails": [
                        {
                            "value": "sales@example.com",
                            "confidence": 96,
                            "type": "generic",
                        },
                        {
                            "value": "jane@example.com",
                            "confidence": 72,
                            "type": "personal",
                            "position": "Purchasing Manager",
                        },
                    ]
                }
            }
        )

        self.assertEqual(email["email"], "jane@example.com")
        self.assertIn("position=Purchasing Manager", email["notes"])

    def test_hunter_ignores_blank_email_results(self) -> None:
        email = hunter_domain_to_email(
            {
                "data": {
                    "emails": [
                        {"value": "", "confidence": 100},
                        {"value": "buyer@example.com", "confidence": 80},
                    ]
                }
            }
        )

        self.assertEqual(email["email"], "buyer@example.com")

    def test_hunter_verification_note_maps_status(self) -> None:
        note = hunter_verification_note({"data": {"status": "valid", "score": 98}})

        self.assertEqual(note, "Hunter verification: valid score=98")

    def test_clients_report_missing_keys(self) -> None:
        with self.assertRaises(RuntimeError):
            ApolloClient("").people_search("Example", "USA")
        with self.assertRaises(RuntimeError):
            HunterClient("").domain_search("example.com")


if __name__ == "__main__":
    unittest.main()
