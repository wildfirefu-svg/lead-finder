# Lead Finder Four-Stage Improvement Design

## Purpose

Improve the private fiberglass export lead system in four ordered stages:

1. Improve lead accuracy.
2. Improve lead recall.
3. Close the CRM feedback loop.
4. Harden the product for repeated daily use.

The stages must be delivered in order. Accuracy comes first so wider search does not feed low-quality leads into Hunter, Apollo, or the CRM.

## Current State

The project already supports:

- Comtrade market selection.
- Serper public web discovery.
- Website crawl and buyer/supplier classification.
- Apollo and Hunter enrichment through official APIs.
- Hunter verification for existing Qualified emails.
- Qualified-only CRM sync into `F:\project\sale`.
- Provider usage tracking.
- Local workbench at `http://127.0.0.1:8765`.
- SQLite storage.
- Python unittest coverage.
- GitHub repository at `https://github.com/wildfirefu-svg/lead-finder`.

The current system can produce and sync usable leads. The next work should make those leads easier to trust, scale search across more markets, and make outcomes measurable.

## Non-Goals

- Do not scrape logged-in SaaS dashboards, paid member pages, or sites where account terms disallow automation.
- Do not disable SSL certificate verification.
- Do not send sales emails automatically.
- Do not write API keys, SMTP secrets, or CRM secrets to browser responses, logs, docs, or Git.
- Do not change the CRM CSV import field contract unless the CRM project is changed in the same planned stage.
- Do not optimize for maximum lead count before accuracy gates are in place.

## Stage A: Lead Accuracy

### Goal

Make every Qualified or Rejected decision explainable, and prevent low-confidence leads from consuming Apollo, Hunter, or CRM sync capacity.

### Components

#### Structured Evidence

Add structured evidence alongside the existing free-text fields. Evidence should capture:

- Buyer evidence.
- Supplier evidence.
- Distributor or downstream manufacturer evidence.
- Market evidence.
- Contact evidence.
- Directory, marketplace, PDF, or social-media noise.
- Crawl status and failure summary.
- Score additions and penalties.

This can be stored as JSON text in SQLite or as focused columns if the implementation plan finds that simpler. The public CRM export schema should remain unchanged.

#### Classification Explanation

Each lead should have a visible classification:

- `buyer`
- `supplier`
- `distributor`
- `manufacturer`
- `directory`
- `unknown`

The workbench should show why the classification was assigned. Examples:

- Buyer-like: "FRP pipe manufacturer", "pultrusion profiles", "uses fiberglass roving".
- Supplier-like: "manufacturer of fiberglass roving", "fiberglass yarn supplier", "exporter of glass fiber".
- Directory-like: search result pages, marketplaces, PDFs, social pages, ranking articles.

#### Score Explanation

Scores should be decomposed into visible additions and penalties, such as:

- `+25 downstream application`
- `+15 target market evidence`
- `+10 verified business email`
- `-30 supplier language`
- `-20 directory or marketplace`
- `-15 target-country mismatch`

The score explanation should support both tests and workbench display.

#### Review Queues

The workbench should add filters for:

- High-confidence Qualified.
- Needs manual review.
- Suspected supplier false positive.
- Crawl failed.

The first version should avoid a complex approval workflow. Filtering and batch reclassification are enough.

#### API Credit Gate

Apollo and Hunter should run only for leads that pass all of these conditions:

- Classification is `buyer`, `manufacturer`, or `distributor`.
- Market fit is positive.
- Score is at or above the configured threshold.
- Crawl status is successful or there is enough existing evidence to classify safely.

`unknown`, supplier, directory, and crawl-failed leads should not consume Apollo or Hunter credits until requalified.

### Acceptance Criteria

- Qualified leads show why they are Qualified.
- Rejected supplier leads show why they are Rejected.
- Apollo and Hunter do not run for suppliers, directories, crawl failures, or unknown classifications.
- Tests cover classification explanation, score explanation, and enrichment gating.
- CRM export fields remain stable.

## Stage B: Lead Recall

### Goal

Find more relevant customers across more countries and fiberglass product families without bypassing Stage A accuracy gates.

### Components

#### Localized Search Terms

Maintain country and language-specific search terms. Examples:

- Germany: `Glasfaser Rovings`, `GFK Profile Hersteller`.
- Spanish-language markets: `fibra de vidrio`, `compuestos FRP`.
- French-language markets: `fibre de verre`, `composites PRV`.

Terms should be grouped by country or language, not embedded in one large query string.

#### HS Code Product Families

Represent fiberglass-related HS codes and product families in a selectable structure. The workbench should continue supporting HS `7019` and `701919`, then expand to product families such as:

- Roving.
- Yarn.
- Woven fabrics.
- Mats.
- Mesh.
- Chopped strand.
- Tissue.
- Insulation fabric.

Search queries should be generated from HS code, product family, country, and localized terms.

#### Region-to-Country Batch Runs

The workbench should keep the current region selection followed by country selection. It should add a controlled batch run mode where each country has its own limit so one large market cannot consume the whole Serper budget.

#### Recall Quality Report

Campaign reporting should show:

- Country.
- Language or locale.
- Search terms.
- Serper queries consumed.
- Leads created.
- Qualified count.
- Rejected count.
- Valid email count after enrichment.

The main recall metric should be Qualified leads per Serper query, not raw lead count.

### Acceptance Criteria

- The same HS code can generate different localized queries by country.
- Region batch runs enforce per-country limits.
- New search results still pass Stage A classification, score, and enrichment gates.
- The workbench shows which countries and search terms are productive.
- Tests cover localized terms, HS product families, per-country limits, and recall reporting.

## Stage C: CRM Feedback Loop

### Goal

Use CRM follow-up outcomes to improve future lead scoring and search strategy.

### Components

#### Manual CRM Outcome Pull

Add a workbench action to pull CRM outcomes back into lead-finder. The first version should be manual, not a background scheduler.

Local leads should capture:

- `crm_followup_status`
- `crm_last_contact_at`
- `crm_outcome`

#### Stable Outcome Labels

Use a small set of CRM outcome labels:

- `valid_customer`
- `not_buyer`
- `wrong_market`
- `duplicate`
- `no_response`
- `do_not_contact`

These labels should be stored as feedback signals. They should not rewrite historical score values automatically.

#### Rule Feedback

The workbench should summarize which countries, terms, and classification rules produce good or bad CRM outcomes:

- Rules that produce many `valid_customer` outcomes should be marked productive.
- Rules that produce many `not_buyer` or `wrong_market` outcomes should be marked low-efficiency.

#### Follow-Up Suggestions

The system may suggest actions such as:

- Prioritize follow-up.
- Needs manual confirmation.
- Do not contact.

It should not send emails automatically.

### Acceptance Criteria

- lead-finder can manually pull CRM outcomes.
- Synced leads show CRM outcome labels.
- CRM responses and workbench APIs do not expose secrets.
- The workbench can summarize which countries, terms, and rules lead to valid or invalid customers.
- No automatic email sending is introduced.

## Stage D: Product Stability

### Goal

Make the system safe and repeatable for daily use.

### Components

#### Quota Budgets and Circuit Breakers

Add per-run and daily soft limits for:

- Serper.
- Hunter.
- Apollo.

When a budget is reached, the run should stop provider calls and display why it stopped.

#### Run Logs and Error States

Campaigns, verification runs, enrichment runs, and CRM syncs should record:

- Run id.
- Start and end timestamps.
- Success count.
- Failure count.
- Skipped count.
- Sanitized error summary.
- Provider usage counts.

Errors must continue to pass through redaction before reaching UI or persisted notes.

#### Retry and Recovery

Add limited retry for likely transient failures:

- Timeout.
- HTTP 5xx.
- DNS or temporary network errors.

SSL certificate failures should be recorded and handled through safe fallback behavior. Certificate validation must not be disabled.

Already processed leads should not be charged again by repeated runs unless their state explicitly requires retry.

#### Documentation

Update README to match the real product:

- CRM sync is supported.
- First-time setup.
- Daily operating flow.
- API quota saving strategy.
- Troubleshooting.
- API key rotation reminder.

#### GitHub Hygiene

Add a simple CI workflow that runs the Python unittest suite. Optional issue templates or a short roadmap can be added after CI is working.

### Acceptance Criteria

- Provider usage and budget stops are visible.
- Budget limits prevent accidental paid API overuse.
- Common network failures produce readable status.
- README matches current behavior.
- GitHub CI runs the test suite.
- `.env`, SQLite databases, exports, logs, and caches remain ignored.

## Delivery Order

1. Stage A must be implemented first.
2. Stage B depends on Stage A gates.
3. Stage C depends on stable CRM sync and Stage A evidence.
4. Stage D can be implemented last, with README and CI reflecting the final behavior.

Each stage should have its own implementation plan, tests, commit, and verification summary.

## Testing Strategy

Use focused unit tests first, then run the full suite before each stage commit.

Stage A tests should cover:

- Evidence extraction.
- Classification explanation.
- Score explanation.
- Enrichment gating.
- Workbench filters.

Stage B tests should cover:

- Localized query generation.
- HS product family selection.
- Region-to-country limits.
- Recall reporting.

Stage C tests should cover:

- CRM outcome parsing.
- Local feedback storage.
- Secret redaction.
- Outcome summaries.

Stage D tests should cover:

- Budget stops.
- Retryable and non-retryable errors.
- Run logs.
- README command accuracy where practical.
- CI test command.

## Open Decisions

The implementation plan should decide whether structured evidence is stored as one JSON field or several narrow columns. The choice should follow the smallest database change that keeps tests and workbench display simple.

