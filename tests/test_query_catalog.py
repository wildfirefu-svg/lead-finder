from __future__ import annotations

import unittest

from leadfinder.query_catalog import build_query_specs, product_families_for_hs


class QueryCatalogTests(unittest.TestCase):
    def test_product_families_for_hs_7019_returns_multiple_fiberglass_families(self) -> None:
        families = product_families_for_hs("7019", "all")

        self.assertEqual(
            families,
            [
                "roving",
                "yarn",
                "woven_fabric",
                "mat",
                "mesh",
                "chopped_strand",
                "tissue",
                "insulation_fabric",
            ],
        )

    def test_product_families_for_specific_hs_prefers_matching_family(self) -> None:
        self.assertEqual(product_families_for_hs("701912", "all"), ["roving"])
        self.assertEqual(product_families_for_hs("701971", "all"), ["tissue"])
        self.assertEqual(product_families_for_hs("701913", "yarn"), ["yarn"])
        self.assertEqual(product_families_for_hs("701912", "yarn"), ["roving"])

    def test_build_query_specs_for_germany_include_locale_family_and_terms(self) -> None:
        specs = build_query_specs("Germany", "701912", "all")

        self.assertTrue(specs)
        self.assertTrue(all(spec["country"] == "Germany" for spec in specs))
        self.assertTrue(all(spec["locale"] == "de-DE" for spec in specs))
        self.assertTrue(all(spec["product_family"] == "roving" for spec in specs))
        self.assertTrue(any("glasfaser" in spec["query"].lower() for spec in specs))
        self.assertTrue(any("GFK" in spec["query"] for spec in specs))

    def test_build_query_specs_for_7019_all_returns_multiple_families(self) -> None:
        specs = build_query_specs("Canada", "7019", "all")
        families = {spec["product_family"] for spec in specs}

        self.assertIn("roving", families)
        self.assertIn("woven_fabric", families)
        self.assertIn("mat", families)
        self.assertTrue(any("Ontario" in spec["query"] for spec in specs))

    def test_build_query_specs_for_explicit_yarn_stays_on_yarn_family(self) -> None:
        specs = build_query_specs("Canada", "701913", "yarn")

        self.assertTrue(specs)
        self.assertTrue(all(spec["product_family"] == "yarn" for spec in specs))
        self.assertTrue(any("glass fiber yarn" in spec["query"].lower() for spec in specs))
        self.assertFalse(any("Ontario" in spec["query"] for spec in specs))

    def test_build_query_specs_for_legacy_yarn_on_roving_hs_stays_roving_style(self) -> None:
        specs = build_query_specs("Germany", "701912", "yarn")

        self.assertTrue(specs)
        self.assertTrue(all(spec["product_family"] == "roving" for spec in specs))
        self.assertTrue(any("pultrusion" in spec["query"].lower() for spec in specs))
        self.assertTrue(any("glasfaser" in spec["query"].lower() for spec in specs))


if __name__ == "__main__":
    unittest.main()
