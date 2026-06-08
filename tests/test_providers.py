from __future__ import annotations

import unittest

from cli import main
from leadfinder.providers import provider_report, provider_summary


class ProviderReportTests(unittest.TestCase):
    def test_provider_summary_classifies_serper_as_free_credit_or_paid(self) -> None:
        summary = provider_summary("Serper")

        self.assertEqual(summary["provider"], "Serper")
        self.assertEqual(summary["cost_model"], "free_credit_or_paid")
        self.assertTrue(summary["api_backed"])
        self.assertFalse(summary["zero_cost_core"])
        self.assertIn("credits", summary["notes"].lower())

    def test_provider_summary_classifies_bright_data_as_paid_public_web_only(self) -> None:
        summary = provider_summary("Bright Data")

        self.assertEqual(summary["provider"], "Bright Data")
        self.assertEqual(summary["cost_model"], "paid")
        self.assertTrue(summary["api_backed"])
        self.assertFalse(summary["zero_cost_core"])
        self.assertIn("public web", summary["allowed_use"].lower())

    def test_provider_report_contains_free_and_paid_sources(self) -> None:
        report = provider_report()
        providers = {item["provider"]: item for item in report["providers"]}

        self.assertTrue(providers["UN Comtrade"]["zero_cost_core"])
        self.assertFalse(providers["Serper"]["zero_cost_core"])
        self.assertFalse(providers["Apollo.io"]["zero_cost_core"])
        self.assertFalse(providers["Snov.io"]["zero_cost_core"])
        self.assertFalse(providers["Bright Data"]["zero_cost_core"])

    def test_provider_report_includes_csv_only_data_platforms(self) -> None:
        report = provider_report()
        names = {item["provider"] for item in report["providers"]}

        for name in [
            "Panjiva",
            "ImportGenius",
            "ZoomInfo",
            "Lusha",
            "BuiltWith",
            "SimilarWeb",
            "跨境搜",
            "跨境魔方",
            "Tendata",
            "TradeInfo",
            "孚盟软件",
            "信风数据",
            "格兰德",
            "Hunter.io",
        ]:
            self.assertIn(name, names)

    def test_cli_provider_report_returns_zero(self) -> None:
        exit_code = main(["provider-report"])

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
