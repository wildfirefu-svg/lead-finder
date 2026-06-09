from __future__ import annotations

import json
import math

PASSING_CLASSIFICATIONS = {"buyer", "manufacturer", "distributor"}
PASSING_MARKET_STATUSES = {"passed", "pass", "matched", "ok", "positive"}
PASSING_CRAWL_STATUSES = {"", "ok", "success", "passed", "fetched"}


def evidence_json(evidence: dict) -> str:
    return json.dumps(
        {
            "additions": evidence.get("additions", []),
            "penalties": evidence.get("penalties", []),
            "matched_terms": evidence.get("matched_terms", []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def parse_score_evidence(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        parsed = value
    else:
        if not value:
            return {"additions": [], "penalties": [], "matched_terms": []}
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return {"additions": [], "penalties": [], "matched_terms": []}
    if not isinstance(parsed, dict):
        return {"additions": [], "penalties": [], "matched_terms": []}
    return {
        "additions": _list_value(parsed.get("additions")),
        "penalties": _list_value(parsed.get("penalties")),
        "matched_terms": _list_value(parsed.get("matched_terms")),
    }


def score_reason_text(evidence: dict) -> str:
    parts: list[str] = []
    for item in evidence.get("additions", []):
        parts.append(_format_item(item, positive=True))
    for item in evidence.get("penalties", []):
        parts.append(_format_item(item, positive=False))
    if not parts:
        return "No fiberglass keywords found yet; review manually."
    return "; ".join(parts)


def lead_classification_label(category: str | None) -> str:
    value = str(category or "").strip().lower()
    mapping = {
        "downstream_customer": "buyer",
        "buyer": "buyer",
        "manufacturer": "manufacturer",
        "distributor_or_importer": "distributor",
        "distributor": "distributor",
        "supplier": "supplier",
        "noise": "directory",
        "directory": "directory",
    }
    return mapping.get(value, "unknown")


def enrichment_eligible(lead: dict, *, min_score: int = 50) -> bool:
    if str(lead.get("status", "") or "") != "Qualified":
        return False
    try:
        score = float(lead.get("match_score", 0) or 0)
        threshold = float(min_score)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(score) or not math.isfinite(threshold) or score < threshold:
        return False
    if not str(lead.get("website", "") or "").strip():
        return False
    classification = lead_classification_label(lead.get("classification_status", ""))
    if classification not in PASSING_CLASSIFICATIONS:
        return False
    market_status = str(lead.get("market_fit_status", "") or "").strip().lower()
    if market_status not in PASSING_MARKET_STATUSES:
        return False
    crawl_status = str(lead.get("crawl_status", "") or "").strip().lower()
    if crawl_status and crawl_status not in PASSING_CRAWL_STATUSES:
        return False
    return True


def _list_value(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def _format_item(item: dict, *, positive: bool) -> str:
    points = int(item.get("points", 0) or 0)
    if positive and points > 0:
        prefix = f"+{points}"
    else:
        prefix = str(points)
    reason = str(item.get("reason", "") or "").strip()
    terms = [str(term) for term in item.get("terms", []) if str(term).strip()]
    suffix = f": {', '.join(terms[:5])}" if terms else ""
    return f"{prefix} {reason}{suffix}".strip()
