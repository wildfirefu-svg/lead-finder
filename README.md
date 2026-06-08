# Lead Finder

Python CLI for finding overseas fiberglass yarn and fiberglass fabric customer leads, then exporting CSV rows that can be imported into `F:\project\sale`.

## Setup

```powershell
Copy-Item .env.example .env
python cli.py stats
```

Edit `.env` and set `SERPER_API_KEY` before running live discovery.

## Commands

```powershell
python cli.py markets --hs 7019 --year 2024
python cli.py discover --country USA --limit 100
python cli.py campaign --hs 7019 --year 2024 --product both --market-limit 3 --per-market-limit 10
python cli.py campaign --hs 7019 --year 2024 --product both --market-limit 3 --per-market-limit 10 --apollo --hunter
python cli.py provider-report
python cli.py quality-report --min-score 50
python cli.py import-csv --input exports/waitubang.csv --source 外贸邦
python cli.py import-csv --input exports/yizhijia.csv --source 易之家
python cli.py import-csv --input exports/apollo.csv --source Apollo.io
python cli.py import-csv --input exports/snov.csv --source Snov.io
python cli.py enrich --limit 100
python cli.py export --output exports/sourced_leads.csv
python cli.py serve
python cli.py stats
python -m unittest discover -s tests -p test_*.py
```

The exported CSV fields match the sourced lead import in the CRM:

```text
source_type, source_name, company_name, country_region, market_region, website, source_url, contact_name, email, industry, product_fit, fit_reason, match_score, notes, raw_text
```

## Cost-aware source workflow

- Use UN Comtrade to choose target countries for HS 7019 fiberglass products.
- Use Serper discovery for public company websites when free trial or paid credits are available.
- Use 外贸邦 / 易之家 manually for public bill-of-lading clues, then import exported or copied CSV rows with `import-csv`.
- Use Apollo.io / Snov.io free credits manually for email discovery, then import their CSV output with `import-csv`.
- Keep Serper, Apollo.io, Snov.io, and Bright Data as optional paid or free-credit sources. Their quotas and credit systems can change, so the core workflow must still work without them.
- Use Bright Data only for public web pages. Do not use it for logged-in SaaS pages, paywalled data, or bypassing account restrictions.
- Do not scrape bill-of-lading or SaaS platforms unless their terms allow it for the account being used.

## Recommended operating flow

### Stage 1: source aggregation

1. Pick target countries with `python cli.py markets --hs 7019 --year 2024`.
2. Check cost assumptions with `python cli.py provider-report`.
3. Run public discovery with `python cli.py discover --country USA --limit 100` when Serper free trial or paid credits are available.
4. Record the baseline with `python cli.py quality-report --min-score 50`.
5. Import bill-of-lading CSV rows with `python cli.py import-csv --input exports/waitubang.csv --source 外贸邦`.
6. Import free-credit or paid SaaS contact CSV rows with `python cli.py import-csv --input exports/snov.csv --source Snov.io`.
7. Enrich websites with `python cli.py enrich --limit 100`.
8. Recheck quality with `python cli.py quality-report --min-score 50`.
9. Export CRM CSV with `python cli.py export --output exports/sourced_leads.csv --min-score 50`.

### Stage 2: private workbench

Run `python cli.py serve` and open `http://127.0.0.1:8765`.

Use the workbench to review leads, inspect source and fit, and decide which leads should be exported for CRM follow-up.

## Campaign workflow

The `campaign` command runs Comtrade market selection, Serper discovery, optional Apollo contact lookup, optional Hunter email lookup and verification, then records quality before and after the run.

Serper, Apollo, and Hunter are optional credit-based providers. Missing API keys disable those providers rather than failing the whole campaign.

Use small limits first:

```powershell
python cli.py campaign --market-limit 1 --per-market-limit 3
```

## Notes

- v1 only collects public company leads and exports CSV.
- v1 does not send emails or write into the CRM database.
- Apollo.io, Snov.io, and Bright Data are optional sources, not zero-cost core dependencies.
- If UN Comtrade is unavailable, use `discover --country <COUNTRY>` with manual target markets.
