from __future__ import annotations

import json
from dataclasses import dataclass

from .apollo import apollo_people_to_contact
from .classifier import classification_note, classify_company_site
from .db import (
    create_campaign_run,
    create_or_skip_lead,
    find_duplicate,
    finish_campaign_run,
    list_leads,
    record_provider_event,
    update_lead,
)
from .enrich import enrich_site, normalize_domain
from .evidence import PASSING_CRAWL_STATUSES, enrichment_eligible, review_status_for_lead
from .hunter import hunter_domain_to_email, hunter_verification_note
from .market_fit import market_fit_note, validate_target_market
from .markets import fallback_markets, fetch_comtrade_markets
from .quality import quality_report
from .query_catalog import build_query_specs
from .scoring import score_lead
from .serper import results_to_leads


@dataclass(frozen=True)
class CampaignOptions:
    hs_code: str = "7019"
    year: int = 2024
    product: str = "both"
    market_limit: int = 5
    per_market_limit: int = 20
    target_countries: tuple[str, ...] = ()
    min_score: int = 50
    use_serper: bool = True
    use_apollo: bool = False
    use_hunter: bool = False
    timeout_seconds: float = 12.0


def _effective_product(hs_code: str, product: str) -> str:
    product_key = product.lower().replace("_", "-")
    if product_key != "both":
        return product_key
    normalized_hs = "".join(char for char in hs_code if char.isdigit())
    if normalized_hs.startswith("70191"):
        return "yarn"
    if normalized_hs.startswith("70196") or normalized_hs.startswith("70197"):
        return "fabric"
    return product_key


def _append_note(existing: str, note: str) -> str:
    parts = [part for part in [existing.strip(), note.strip()] if part]
    return "\n".join(parts)


def run_campaign(
    db,
    options: CampaignOptions,
    *,
    fetch_markets=fetch_comtrade_markets,
    serper_client=None,
    apollo_client=None,
    hunter_client=None,
    site_enricher=enrich_site,
) -> dict:
    quality_before = quality_report(list_leads(db), min_score=options.min_score)
    effective_product = _effective_product(options.hs_code, options.product)
    providers = ["Region Selection"] if options.target_countries else ["Comtrade"]
    if options.use_serper:
        providers.append("Serper")
        providers.append("Site Classifier")
    if options.use_apollo:
        providers.append("Apollo.io")
    if options.use_hunter:
        providers.append("Hunter.io")

    run = create_campaign_run(
        db,
        {
            "name": f"HS{options.hs_code} {options.product}",
            "hs_code": options.hs_code,
            "year": options.year,
            "product": effective_product,
            "market_limit": options.market_limit,
            "per_market_limit": options.per_market_limit,
            "providers": providers,
            "quality_before": quality_before,
        },
    )
    run_id = run["id"]
    created = 0
    skipped = 0
    errors = 0

    try:
        if options.target_countries:
            markets = [
                {
                    "country_region": country,
                    "import_value_usd": 0,
                    "hs_code": options.hs_code,
                    "year": options.year,
                    "source_name": "Selected Region",
                }
                for country in options.target_countries
            ]
            record_provider_event(
                db,
                run_id,
                provider="Region Selection",
                event_type="markets",
                status="ok",
                cost_units=0,
                message=f"countries={len(markets)}",
            )
        else:
            try:
                markets = fetch_markets(options.hs_code, options.year, options.timeout_seconds)
                if not markets:
                    raise RuntimeError("UN Comtrade returned no markets")
                record_provider_event(
                    db,
                    run_id,
                    provider="Comtrade",
                    event_type="markets",
                    status="ok",
                    cost_units=0,
                    message=f"markets={len(markets)}",
                )
            except Exception as error:
                markets = fallback_markets(options.hs_code, options.year)
                record_provider_event(
                    db,
                    run_id,
                    provider="Comtrade",
                    event_type="markets",
                    status="fallback",
                    cost_units=0,
                    message=str(error),
                )

        market_limit = len(options.target_countries) if options.target_countries else int(options.market_limit)
        selected_markets = markets[: max(0, market_limit)]
        target_created = max(0, market_limit * int(options.per_market_limit))

        if options.use_serper and serper_client is None:
            record_provider_event(
                db,
                run_id,
                provider="Serper",
                event_type="search",
                status="skipped",
                cost_units=0,
                message="SERPER_API_KEY missing or client unavailable",
            )
        elif options.use_serper:
            for market in selected_markets:
                country = market.get("country_region", "")
                created_for_market = 0
                query_specs = build_query_specs(country, options.hs_code, effective_product)
                query_limit = max(1, int(options.per_market_limit))
                for spec in query_specs[:query_limit]:
                    if created_for_market >= int(options.per_market_limit):
                        break
                    query = spec["query"]
                    serper_message = json.dumps(
                        {
                            "country": country,
                            "locale": spec["locale"],
                            "product_family": spec["product_family"],
                            "query": query,
                        },
                        ensure_ascii=False,
                    )
                    try:
                        payload = serper_client.search(query, num=max(1, min(options.per_market_limit, 100)))
                        record_provider_event(
                            db,
                            run_id,
                            provider="Serper",
                            event_type="search",
                            status="ok",
                            cost_units=1,
                            message=serper_message,
                        )
                    except Exception as error:
                        errors += 1
                        record_provider_event(
                            db,
                            run_id,
                            provider="Serper",
                            event_type="search",
                            status="error",
                            cost_units=0,
                            message=json.dumps(
                                {
                                    "country": country,
                                    "locale": spec["locale"],
                                    "product_family": spec["product_family"],
                                    "query": query,
                                    "error": str(error),
                                },
                                ensure_ascii=False,
                            ),
                        )
                        continue
                    for lead in results_to_leads(payload, country, query):
                        scored = {
                            **lead,
                            "campaign_run_id": run_id,
                            "discovery_query": query,
                            "query_locale": spec["locale"],
                            "product_family": spec["product_family"],
                        }
                        scored = {**scored, **score_lead(scored)}
                        if int(scored.get("match_score") or 0) < min(int(options.min_score), 35):
                            skipped += 1
                            record_provider_event(
                                db,
                                run_id,
                                provider="Site Classifier",
                                event_type="classify",
                                status="skipped",
                                cost_units=0,
                                message=f"pre-score<{min(int(options.min_score), 35)}: {scored.get('website', '')}",
                            )
                            continue
                        if find_duplicate(db, scored):
                            skipped += 1
                            continue
                        classified = _crawl_score_and_classify(
                            scored,
                            options,
                            site_enricher,
                            db,
                            run_id,
                        )
                        if not classified:
                            skipped += 1
                            continue
                        row, was_created = create_or_skip_lead(db, classified)
                        created += int(was_created)
                        created_for_market += int(was_created)
                        skipped += int(not was_created)
                        if was_created:
                            _enrich_optional(db, row, options, apollo_client, hunter_client, run_id)
                        if created >= target_created or created_for_market >= int(options.per_market_limit):
                            break
                    if created >= target_created or created_for_market >= int(options.per_market_limit):
                        break

        if options.use_apollo and apollo_client is None:
            record_provider_event(
                db,
                run_id,
                provider="Apollo.io",
                event_type="contact",
                status="skipped",
                cost_units=0,
                message="APOLLO_API_KEY missing or client unavailable",
            )
        if options.use_hunter and hunter_client is None:
            record_provider_event(
                db,
                run_id,
                provider="Hunter.io",
                event_type="email",
                status="skipped",
                cost_units=0,
                message="HUNTER_API_KEY missing or client unavailable",
            )

        quality_after = quality_report(list_leads(db), min_score=options.min_score)
        final = finish_campaign_run(
            db,
            run_id,
            status="Completed",
            created=created,
            skipped=skipped,
            errors=errors,
            quality_after=quality_after,
        )
        return {
            "run_id": run_id,
            "status": final["status"],
            "created": created,
            "skipped": skipped,
            "errors": errors,
            "quality_before": quality_before,
            "quality_after": quality_after,
        }
    except Exception:
        quality_after = quality_report(list_leads(db), min_score=options.min_score)
        finish_campaign_run(
            db,
            run_id,
            status="Error",
            created=created,
            skipped=skipped,
            errors=errors + 1,
            quality_after=quality_after,
        )
        raise


def _crawl_score_and_classify(lead: dict, options: CampaignOptions, site_enricher, db, run_id: int) -> dict | None:
    enriched = lead
    try:
        if site_enricher is not None and lead.get("website"):
            enriched = site_enricher(
                lead["website"],
                defaults=lead,
                max_pages=2,
                timeout=min(float(options.timeout_seconds), 6.0),
            )
    except Exception as error:
        record_provider_event(
            db,
            run_id,
            provider="Site Classifier",
            event_type="crawl",
            status="error",
            cost_units=0,
            message=f"{lead.get('website', '')}: {error}",
        )
        return None

    crawl_status = str(enriched.get("crawl_status", "") or "").strip().lower()
    if crawl_status and crawl_status not in PASSING_CRAWL_STATUSES:
        record_provider_event(
            db,
            run_id,
            provider="Site Classifier",
            event_type="crawl",
            status="error",
            cost_units=0,
            message=f"{lead.get('website', '')}: crawl_status={crawl_status}",
        )
        return None

    scored = {**lead, **enriched}
    scored = {**scored, **score_lead(scored)}
    if int(scored.get("match_score") or 0) < int(options.min_score):
        record_provider_event(
            db,
            run_id,
            provider="Site Classifier",
            event_type="classify",
            status="skipped",
            cost_units=0,
            message=f"score<{options.min_score}: {scored.get('website', '')}",
        )
        return None

    classification = classify_company_site(scored)
    note = classification_note(classification)
    scored["classification_status"] = classification["label"]
    scored["classification_evidence"] = classification["explanation"]
    scored["notes"] = _append_note(scored.get("notes", ""), note)
    scored["fit_reason"] = _append_note(scored.get("fit_reason", ""), note)

    if not classification["passed"]:
        record_provider_event(
            db,
            run_id,
            provider="Site Classifier",
            event_type="classify",
            status="skipped",
            cost_units=0,
            message=f"{classification['category']}: {scored.get('website', '')}",
        )
        return None

    record_provider_event(
        db,
        run_id,
        provider="Site Classifier",
        event_type="classify",
        status="ok",
        cost_units=0,
        message=f"{classification['category']}: {scored.get('website', '')}",
    )

    market_fit = validate_target_market(scored, scored.get("country_region", ""))
    market_note = market_fit_note(market_fit)
    scored["market_fit_status"] = "passed" if market_fit["passed"] else "failed"
    scored["notes"] = _append_note(scored.get("notes", ""), market_note)
    scored["fit_reason"] = _append_note(scored.get("fit_reason", ""), market_note)

    if not market_fit["passed"]:
        record_provider_event(
            db,
            run_id,
            provider="Market Fit",
            event_type="country",
            status="skipped",
            cost_units=0,
            message=f"{market_fit['reason']}: {scored.get('website', '')}",
        )
        return None

    record_provider_event(
        db,
        run_id,
        provider="Market Fit",
        event_type="country",
        status="ok",
        cost_units=0,
        message=f"{scored.get('country_region', '')}: {scored.get('website', '')}",
    )
    scored["status"] = "Qualified"
    scored["review_status"] = review_status_for_lead(scored, min_score=options.min_score)
    return scored


def _enrich_optional(db, lead: dict, options: CampaignOptions, apollo_client, hunter_client, run_id: int) -> None:
    if not enrichment_eligible(lead, min_score=options.min_score):
        return

    updates: dict = {}
    notes = lead.get("notes", "")

    if options.use_apollo and apollo_client is not None and lead.get("company_name"):
        try:
            payload = apollo_client.people_search(lead["company_name"], lead.get("country_region", ""))
            contact = apollo_people_to_contact(payload)
            if contact.get("contact_name"):
                updates["contact_name"] = contact["contact_name"]
            notes = _append_note(notes, contact.get("notes", ""))
            record_provider_event(
                db,
                run_id,
                provider="Apollo.io",
                event_type="contact",
                status="ok",
                cost_units=1,
                message=lead["company_name"],
            )
        except Exception as error:
            record_provider_event(
                db,
                run_id,
                provider="Apollo.io",
                event_type="contact",
                status="error",
                cost_units=0,
                message=str(error),
            )

    domain = normalize_domain(lead.get("website", ""))
    if options.use_hunter and hunter_client is not None and domain:
        try:
            payload = hunter_client.domain_search(domain)
            email = hunter_domain_to_email(payload)
            cost_units = 1.0
            if email.get("email"):
                verify_payload = hunter_client.verify_email(email["email"])
                cost_units += 1.0
                notes = _append_note(notes, hunter_verification_note(verify_payload))
                verification_status = str(
                    (verify_payload.get("data") or {}).get("status") or ""
                ).lower()
                if verification_status == "valid":
                    updates["email"] = email["email"]
                updates["email_verification_status"] = verification_status or "unknown"
            else:
                updates["email_verification_status"] = "not_found"
            notes = _append_note(notes, email.get("notes", ""))
            record_provider_event(
                db,
                run_id,
                provider="Hunter.io",
                event_type="email",
                status="ok",
                cost_units=cost_units,
                message=domain,
            )
        except Exception as error:
            record_provider_event(
                db,
                run_id,
                provider="Hunter.io",
                event_type="email",
                status="error",
                cost_units=0,
                message=str(error),
            )

    if notes != lead.get("notes", ""):
        updates["notes"] = notes
    if updates:
        merged = {**lead, **updates}
        scored = score_lead(merged)
        update_lead(db, lead["id"], {**updates, **scored})
