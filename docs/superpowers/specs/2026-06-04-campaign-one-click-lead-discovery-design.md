# Campaign One-Click Lead Discovery Design

## Goal

Build a one-click Campaign workflow for the private lead system. A campaign should choose priority markets with Comtrade, discover company websites with Serper, optionally search contacts with Apollo.io, optionally find and verify emails with Hunter.io, then write scored, deduped leads into the existing SQLite database for review in the local workbench.

## Non-Goals

- Do not scrape logged-in SaaS dashboards, paid member pages, or paywalled datasets.
- Do not automate 外贸邦, 易之家, Panjiva, ImportGenius, ZoomInfo, Lusha, BuiltWith, SimilarWeb, 跨境搜, 跨境魔方, Tendata, TradeInfo, 孚盟软件, 信风数据, or 格兰德 in the first campaign release.
- Do not send emails or create email sequences.
- Do not write into the external CRM database.
- Do not add Bright Data to the campaign runner yet. Bright Data remains a future paid public-web collection option.

## Campaign Inputs

The campaign UI and CLI should collect:

- `hs_code`: default `7019`.
- `year`: default `2024`.
- `product`: `yarn`, `fabric`, or `both`.
- `market_limit`: number of Comtrade markets to use.
- `per_market_limit`: number of Serper leads to create per market.
- `min_score`: default `50`, used for quality comparison.
- Optional provider toggles:
  - `use_serper`: enabled by default when `SERPER_API_KEY` exists.
  - `use_apollo`: enabled only when `APOLLO_API_KEY` exists.
  - `use_hunter`: enabled only when `HUNTER_API_KEY` exists.

## Provider Roles

### Comtrade

Comtrade selects target countries for HS 7019. If Comtrade fails, the runner should use the existing fallback market list and record that fallback in campaign output.

### Serper

Serper searches public Google results for company websites by market and product query. Serper is a free-credit or paid credits provider, not a zero-cost core source. The campaign should record the number of queries attempted and successful.

### Apollo.io

Apollo searches companies and contacts where official API access is available for the current account. People Search can identify contacts, but email enrichment may consume credits and may be restricted by plan. The first implementation should preserve company/contact metadata even when no email is returned.

### Hunter.io

Hunter performs domain search and email verification. The first implementation should:

- Use a lead website domain as input.
- Store the best email found, if any.
- Verify existing or Hunter-found emails when the API returns a verification result.
- Record verification status in `notes` without changing the CRM export schema.

## CSV-Only Provider Sources

These sources are valuable but first-class campaign automation should not call or scrape them:

- 外贸邦
- 易之家
- Panjiva
- ImportGenius
- ZoomInfo
- Lusha
- BuiltWith
- SimilarWeb
- 跨境搜
- 跨境魔方
- Tendata
- TradeInfo
- 孚盟软件
- 信风数据
- 格兰德

They should be added to the provider directory and accepted by the existing `import-csv` command. Imported rows should be tagged by `source_name`, scored, deduped, and included in `quality-report`.

## Data Flow

1. User starts a campaign from CLI or web workbench.
2. System records a pre-run `quality_report`.
3. System fetches or falls back to target markets.
4. For each selected market, Serper runs the existing product queries.
5. Search results are normalized into lead rows, scored, and inserted with existing dedupe rules.
6. If Apollo is enabled, the system searches company/contact data and updates matching leads with contact names, titles, and source notes.
7. If Hunter is enabled, the system searches or verifies emails by domain and updates matching leads.
8. System records a post-run `quality_report`.
9. Web workbench refreshes the lead table and shows campaign summary: markets used, leads created, skipped duplicates, provider errors, and quality delta.

## Data Model

Keep the existing `leads` schema stable for CRM compatibility.

Add a `campaign_runs` table:

- `id`
- `name`
- `hs_code`
- `year`
- `product`
- `market_limit`
- `per_market_limit`
- `providers`
- `status`
- `created`
- `skipped`
- `errors`
- `quality_before`
- `quality_after`
- `started_at`
- `finished_at`

Add a `provider_events` table:

- `id`
- `campaign_run_id`
- `provider`
- `event_type`
- `status`
- `cost_units`
- `message`
- `created_at`

These tables are for auditability and cost visibility. They should not change the CRM export fields.

## Web Workbench Changes

Add a campaign panel above the lead table:

- Inputs for HS code, year, product, market limit, per-market limit.
- Provider toggles for Serper, Apollo, Hunter.
- Disabled provider state when the required API key is missing.
- `Run Campaign` button.
- Campaign summary after run.

The first version can run synchronously in the local server request because limits should stay small. The UI should warn that large runs may take time and spend credits.

## CLI Changes

Add:

```powershell
python cli.py campaign --hs 7019 --year 2024 --product both --market-limit 5 --per-market-limit 20
```

Optional flags:

```powershell
--no-serper
--apollo
--hunter
--min-score 50
```

The command should print JSON with the campaign summary.

## Error Handling

- Missing Serper API key: skip Serper and report that no automated discovery was run.
- Missing Apollo API key: disable Apollo enrichment and continue.
- Missing Hunter API key: disable Hunter enrichment and continue.
- Provider request failure: record provider event, continue with other providers where possible.
- Comtrade failure: use fallback markets and record the fallback.
- Duplicate leads: count as `skipped`, not errors.

## Quality Gate

Every campaign must compare `quality_before` and `quality_after`.

The run is useful when:

- `high_quality` increases, and
- `high_quality_rate` does not drop sharply.

If `high_quality_rate` drops after adding a paid provider, the next step should be query tuning or provider disablement, not more volume.

## Testing

Use `unittest` and offline fixtures. Do not require live API keys for the test suite.

Tests should cover:

- Campaign runner works with Comtrade fallback and mocked Serper payloads.
- Missing API keys disable optional providers without failing the run.
- Provider events record cost/source status.
- Campaign inserts deduped leads and updates `campaign_runs`.
- `quality_before` and `quality_after` are present in campaign output.
- Web API can start a campaign with mocked providers.
- CLI `campaign` returns JSON summary.

## Open Implementation Notes

- Apollo and Hunter clients should be small modules with injectable endpoints so tests can use local mock responses.
- Provider-specific email/contact data should go into existing lead fields where possible, with detailed provenance in `notes`.
- The first release should cap default volume to avoid accidental credit spend.
