from __future__ import annotations

import argparse
import json
import sys

from leadfinder.apollo import ApolloClient
from leadfinder.campaigns import CampaignOptions, run_campaign
from leadfinder.config import settings
from leadfinder.db import connect, create_or_skip_lead, list_leads, list_markets, stats, update_lead, upsert_market
from leadfinder.enrich import enrich_site
from leadfinder.exporter import export_csv
from leadfinder.hunter import HunterClient
from leadfinder.importers import import_csv
from leadfinder.markets import fallback_markets, fetch_comtrade_markets
from leadfinder.providers import provider_report
from leadfinder.quality import quality_report
from leadfinder.scoring import score_lead
from leadfinder.serper import SerperClient, build_queries, results_to_leads
from leadfinder.webapp import serve


def cmd_markets(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        try:
            markets = fetch_comtrade_markets(args.hs, args.year, cfg.timeout_seconds)
            source = "UN Comtrade"
        except Exception as error:
            markets = fallback_markets(args.hs, args.year)
            source = f"fallback ({error})"
        for market in markets[: args.limit]:
            upsert_market(db, market)
        print(f"Saved {min(len(markets), args.limit)} markets from {source}.")
        for market in list_markets(db, args.limit):
            print(f"{market['country_region']}\t{market['import_value_usd']:.0f}\t{market['source_name']}")
    finally:
        db.close()
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    client = SerperClient(cfg.serper_api_key, timeout=cfg.timeout_seconds)
    created = 0
    skipped = 0
    try:
        queries = build_queries(args.country, args.product)
        per_query = max(1, min(100, (args.limit + len(queries) - 1) // len(queries)))
        for query in queries:
            payload = client.search(query, num=per_query)
            for lead in results_to_leads(payload, args.country, query):
                scored = {**lead, **score_lead(lead)}
                _, was_created = create_or_skip_lead(db, scored)
                created += int(was_created)
                skipped += int(not was_created)
                if created >= args.limit:
                    break
            if created >= args.limit:
                break
    finally:
        db.close()
    print(f"Discovery complete. created={created}, skipped={skipped}")
    return 0


def cmd_import_serper_json(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    created = 0
    skipped = 0
    try:
        for lead in results_to_leads(payload, args.country, args.query):
            scored = {**lead, **score_lead(lead)}
            _, was_created = create_or_skip_lead(db, scored)
            created += int(was_created)
            skipped += int(not was_created)
    finally:
        db.close()
    print(f"Imported mocked/search JSON. created={created}, skipped={skipped}")
    return 0


def cmd_import_csv(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        result = import_csv(db, args.input, source=args.source)
    finally:
        db.close()
    print(f"Imported CSV source={args.source}. created={result.created}, skipped={result.skipped}")
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    leads = list_leads(db, status=args.status, limit=args.limit)
    enriched = 0
    errors = 0
    try:
        for lead in leads:
            if not lead.get("website"):
                continue
            try:
                enriched_lead = enrich_site(
                    lead["website"],
                    defaults=lead,
                    max_pages=args.max_pages or cfg.max_pages,
                    timeout=cfg.timeout_seconds,
                )
                scored = score_lead(enriched_lead)
                update_lead(db, lead["id"], {**enriched_lead, **scored, "status": "Enriched"})
                enriched += 1
            except Exception as error:
                update_lead(db, lead["id"], {"status": "Error", "notes": f"{lead.get('notes', '')}\nEnrich error: {error}".strip()})
                errors += 1
    finally:
        db.close()
    print(f"Enrichment complete. enriched={enriched}, errors={errors}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        leads = [lead for lead in list_leads(db, limit=args.limit) if int(lead.get("match_score") or 0) >= args.min_score]
        path = export_csv(leads, args.output)
    finally:
        db.close()
    print(f"Exported {len(leads)} leads to {path}")
    return 0


def cmd_quality_report(args: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        leads = list_leads(db, limit=args.limit)
        report = quality_report(leads, min_score=args.min_score)
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_provider_report(_: argparse.Namespace) -> int:
    print(json.dumps(provider_report(), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = settings()
    serve(cfg.db_path, host=args.host, port=args.port)
    return 0


def cmd_campaign(args: argparse.Namespace) -> int:
    cfg = settings()
    use_serper = not args.no_serper and bool(cfg.serper_api_key)
    use_apollo = args.apollo and bool(cfg.apollo_api_key)
    use_hunter = args.hunter and bool(cfg.hunter_api_key)
    db = connect(cfg.db_path)
    try:
        result = run_campaign(
            db,
            CampaignOptions(
                hs_code=args.hs,
                year=args.year,
                product=args.product,
                market_limit=len(args.country) if args.country else args.market_limit,
                per_market_limit=args.per_market_limit,
                target_countries=tuple(args.country or ()),
                min_score=args.min_score,
                use_serper=use_serper,
                use_apollo=use_apollo,
                use_hunter=use_hunter,
                timeout_seconds=cfg.timeout_seconds,
            ),
            serper_client=SerperClient(cfg.serper_api_key, timeout=cfg.timeout_seconds) if use_serper else None,
            apollo_client=ApolloClient(cfg.apollo_api_key, timeout=cfg.timeout_seconds) if use_apollo else None,
            hunter_client=HunterClient(cfg.hunter_api_key, timeout=cfg.timeout_seconds) if use_hunter else None,
        )
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    cfg = settings()
    db = connect(cfg.db_path)
    try:
        print(json.dumps(stats(db), ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find fiberglass overseas customer leads.")
    sub = parser.add_subparsers(required=True)

    markets = sub.add_parser("markets", help="Fetch or seed priority markets for an HS code.")
    markets.add_argument("--hs", default="7019")
    markets.add_argument("--year", type=int, default=2024)
    markets.add_argument("--limit", type=int, default=5)
    markets.set_defaults(func=cmd_markets)

    discover = sub.add_parser("discover", help="Discover leads with Serper.")
    discover.add_argument("--country", required=True)
    discover.add_argument("--product", choices=["yarn", "fabric", "both"], default="both")
    discover.add_argument("--limit", type=int, default=100)
    discover.set_defaults(func=cmd_discover)

    import_json = sub.add_parser("import-serper-json", help="Import saved Serper JSON for offline testing.")
    import_json.add_argument("--input", required=True, type=lambda value: __import__("pathlib").Path(value))
    import_json.add_argument("--country", required=True)
    import_json.add_argument("--query", default="mocked query")
    import_json.set_defaults(func=cmd_import_serper_json)

    import_csv_parser = sub.add_parser("import-csv", help="Import leads from external CSV sources such as bill-of-lading platforms, Apollo, or Snov.")
    import_csv_parser.add_argument("--input", required=True, type=lambda value: __import__("pathlib").Path(value))
    import_csv_parser.add_argument("--source", required=True)
    import_csv_parser.set_defaults(func=cmd_import_csv)

    enrich = sub.add_parser("enrich", help="Crawl discovered websites and enrich lead data.")
    enrich.add_argument("--limit", type=int, default=100)
    enrich.add_argument("--status", default="Discovered")
    enrich.add_argument("--max-pages", type=int, default=0)
    enrich.set_defaults(func=cmd_enrich)

    export = sub.add_parser("export", help="Export CRM-compatible CSV.")
    export.add_argument("--output", default="exports/sourced_leads.csv")
    export.add_argument("--min-score", type=int, default=0)
    export.add_argument("--limit", type=int, default=None)
    export.set_defaults(func=cmd_export)

    quality_parser = sub.add_parser("quality-report", help="Show measurable lead-quality metrics.")
    quality_parser.add_argument("--min-score", type=int, default=50)
    quality_parser.add_argument("--limit", type=int, default=None)
    quality_parser.set_defaults(func=cmd_quality_report)

    provider_parser = sub.add_parser("provider-report", help="Show source provider cost and allowed-use classification.")
    provider_parser.set_defaults(func=cmd_provider_report)

    serve_parser = sub.add_parser("serve", help="Run the private local lead workbench.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.set_defaults(func=cmd_serve)

    campaign = sub.add_parser("campaign", help="Run one-click market selection and lead discovery.")
    campaign.add_argument("--hs", default="7019")
    campaign.add_argument("--year", type=int, default=2024)
    campaign.add_argument("--product", choices=["yarn", "fabric", "both"], default="both")
    campaign.add_argument("--market-limit", type=int, default=5)
    campaign.add_argument("--country", action="append", default=[])
    campaign.add_argument("--per-market-limit", type=int, default=20)
    campaign.add_argument("--min-score", type=int, default=50)
    campaign.add_argument("--no-serper", action="store_true")
    campaign.add_argument("--apollo", action="store_true")
    campaign.add_argument("--hunter", action="store_true")
    campaign.set_defaults(func=cmd_campaign)

    stats_parser = sub.add_parser("stats", help="Show local database counts.")
    stats_parser.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
