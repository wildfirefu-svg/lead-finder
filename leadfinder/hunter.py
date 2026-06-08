from __future__ import annotations

import json
import urllib.parse
import urllib.request


HUNTER_DOMAIN_URL = "https://api.hunter.io/v2/domain-search"
HUNTER_VERIFY_URL = "https://api.hunter.io/v2/email-verifier"

PURCHASING_TERMS = [
    "procurement",
    "purchasing",
    "buyer",
    "sourcing",
    "supply chain",
    "achats",
    "acheteur",
    "einkauf",
    "compras",
]

DECISION_MAKER_TERMS = [
    "owner",
    "founder",
    "chief executive",
    "ceo",
    "general manager",
    "managing director",
    "operations",
]


class HunterClient:
    def __init__(
        self,
        api_key: str,
        domain_endpoint: str = HUNTER_DOMAIN_URL,
        verify_endpoint: str = HUNTER_VERIFY_URL,
        timeout: float = 12.0,
    ):
        self.api_key = api_key
        self.domain_endpoint = domain_endpoint
        self.verify_endpoint = verify_endpoint
        self.timeout = timeout

    def domain_search(self, domain: str) -> dict:
        if not self.api_key:
            raise RuntimeError("HUNTER_API_KEY is required for Hunter enrichment.")
        query = urllib.parse.urlencode({"domain": domain, "api_key": self.api_key})
        with urllib.request.urlopen(f"{self.domain_endpoint}?{query}", timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def verify_email(self, email: str) -> dict:
        if not self.api_key:
            raise RuntimeError("HUNTER_API_KEY is required for Hunter enrichment.")
        query = urllib.parse.urlencode({"email": email, "api_key": self.api_key})
        with urllib.request.urlopen(f"{self.verify_endpoint}?{query}", timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def hunter_domain_to_email(payload: dict) -> dict:
    emails = [
        item
        for item in (payload.get("data") or {}).get("emails") or []
        if str(item.get("value") or "").strip()
    ]
    if not emails:
        return {"email": "", "notes": "Hunter domain search: no email returned"}
    best = max(emails, key=_contact_rank)
    value = str(best.get("value") or "").lower()
    confidence = int(best.get("confidence") or 0)
    position = str(best.get("position") or "").strip()
    position_note = f" position={position}" if position else ""
    return {
        "email": value,
        "notes": f"Hunter domain search: confidence={confidence}{position_note}",
    }


def _contact_rank(item: dict) -> tuple[int, int, int]:
    role_text = " ".join(
        str(item.get(field) or "")
        for field in ("position", "department", "seniority")
    ).lower()
    role_score = 0
    if any(term in role_text for term in PURCHASING_TERMS):
        role_score = 2
    elif any(term in role_text for term in DECISION_MAKER_TERMS):
        role_score = 1
    is_personal = (
        str(item.get("type") or "").lower() == "personal"
        or bool(item.get("first_name"))
        or bool(item.get("last_name"))
    )
    return role_score, int(is_personal), int(item.get("confidence") or 0)


def hunter_verification_note(payload: dict) -> str:
    data = payload.get("data") or {}
    status = data.get("status") or "unknown"
    score = data.get("score")
    if score is None:
        return f"Hunter verification: {status}"
    return f"Hunter verification: {status} score={score}"
