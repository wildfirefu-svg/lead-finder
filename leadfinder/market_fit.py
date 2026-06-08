from __future__ import annotations

from .enrich import normalize_domain


COUNTRY_EVIDENCE = {
    "usa": [
        "usa",
        "u.s.a",
        "united states",
        "america",
        "american",
        "california",
        "texas",
        "florida",
        "new york",
        "illinois",
        "ohio",
        "pennsylvania",
        "wisconsin",
        "nevada",
        "pittsburgh",
        "la crosse",
        "+1",
        "800-",
        "888-",
        "877-",
        "866-",
    ],
    "united states": [
        "usa",
        "u.s.a",
        "united states",
        "america",
        "american",
        "california",
        "texas",
        "florida",
        "new york",
        "illinois",
        "ohio",
        "pennsylvania",
        "wisconsin",
        "nevada",
        "pittsburgh",
        "la crosse",
        "+1",
        "800-",
        "888-",
        "877-",
        "866-",
    ],
    "canada": [
        "canada",
        "canadian",
        "ontario",
        "quebec",
        "british columbia",
        "alberta",
        "manitoba",
        "saskatchewan",
        "nova scotia",
        "+1",
        ".ca",
    ],
    "mexico": ["mexico", "méxico", "mexican", ".mx"],
    "germany": ["germany", "deutschland", "german", "bavaria", "nrw", ".de"],
    "france": ["france", "french", "paris", "lyon", ".fr"],
    "united kingdom": ["united kingdom", "uk", "britain", "england", ".uk", ".co.uk"],
    "italy": ["italy", "italia", "italian", ".it"],
    "spain": ["spain", "españa", "spanish", ".es"],
    "netherlands": ["netherlands", "dutch", "holland", ".nl"],
    "poland": ["poland", "polska", "polish", ".pl"],
    "vietnam": ["vietnam", "viet nam", "vietnamese", ".vn"],
    "thailand": ["thailand", "thai", ".th"],
    "indonesia": ["indonesia", "indonesian", ".id"],
    "malaysia": ["malaysia", "malaysian", ".my"],
    "philippines": ["philippines", "philippine", ".ph"],
    "singapore": ["singapore", ".sg"],
    "india": ["india", "indian", "pune", "mumbai", "gujarat", ".in"],
    "united arab emirates": ["united arab emirates", "uae", "dubai", "abu dhabi", ".ae"],
    "saudi arabia": ["saudi arabia", "saudi", "riyadh", "jeddah", ".sa"],
    "turkey": ["turkey", "turkiye", "türkiye", "istanbul", ".tr"],
    "japan": ["japan", "japanese", "tokyo", ".jp"],
    "south korea": ["south korea", "korea", "korean", ".kr"],
    "brazil": ["brazil", "brasil", "brazilian", ".br"],
    "south africa": ["south africa", "south african", ".za"],
}

COUNTRY_NEGATIVE_EVIDENCE = {
    "canada": [
        "usa",
        "united states",
        "american",
        "california",
        "texas",
        "florida",
        "wisconsin",
        "nevada",
    ],
    "usa": [
        "canada",
        "canadian",
        "ontario",
        "quebec",
        "british columbia",
        "alberta",
    ],
    "united states": [
        "canada",
        "canadian",
        "ontario",
        "quebec",
        "british columbia",
        "alberta",
    ],
}


def market_fit_note(fit: dict) -> str:
    evidence = ", ".join(fit.get("evidence", []))
    suffix = f"; evidence={evidence}" if evidence else ""
    return (
        f"Market fit: target={fit['target_country']} "
        f"passed={fit['passed']} confidence={fit['confidence']} "
        f"reason={fit['reason']}{suffix}"
    )


def validate_target_market(lead: dict, target_country: str) -> dict:
    target = str(target_country or "").strip().lower()
    if not target:
        return _result("", True, 0, [], "no target country")

    expected = COUNTRY_EVIDENCE.get(target)
    if not expected:
        return _result(target_country, True, 0, [], "no country-specific rule")

    text = " ".join(
        str(lead.get(field, "") or "")
        for field in (
            "company_name",
            "website",
            "source_url",
            "notes",
            "raw_text",
        )
    ).lower()
    domain = normalize_domain(lead.get("website", ""))
    haystack = f"{text} {domain}"

    positive = _hits(haystack, expected)
    negative = _hits(haystack, COUNTRY_NEGATIVE_EVIDENCE.get(target, []))

    if target == "canada" and domain.endswith(".ca"):
        positive.append(".ca")

    positive = list(dict.fromkeys(positive))
    negative = list(dict.fromkeys(negative))

    if target == "canada" and domain.endswith(".ca") and positive:
        confidence = min(95, 60 + len(positive) * 10)
        return _result(target_country, True, confidence, positive, "target market domain evidence")

    if positive and not _strong_negative(target, negative):
        confidence = min(95, 50 + len(positive) * 10)
        return _result(target_country, True, confidence, positive, "target market evidence")

    if positive and negative:
        return _result(target_country, False, 45, positive + negative, "conflicting target market evidence")

    return _result(target_country, False, 30, negative, "missing target market evidence")


def _hits(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


def _strong_negative(target: str, negative: list[str]) -> bool:
    if target == "canada":
        return any(term not in {"+1"} for term in negative)
    return False


def _result(target_country: str, passed: bool, confidence: int, evidence: list[str], reason: str) -> dict:
    return {
        "target_country": target_country,
        "passed": passed,
        "confidence": confidence,
        "evidence": list(dict.fromkeys(evidence))[:8],
        "reason": reason,
    }
