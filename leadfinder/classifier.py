from __future__ import annotations

from .evidence import lead_classification_label


DOWNSTREAM_TERMS = [
    "composites manufacturer",
    "composite manufacturer",
    "pultrusion manufacturer",
    "pultrusion",
    "custom pultrusions",
    "pultruded profiles",
    "pultrusion capabilities",
    "frp grating",
    "frp installation",
    "frp installations",
    "frp profiles",
    "frp pipe",
    "frp tanks",
    "fiberglass rebar",
    "fiberglass reinforced plastic products",
    "molded fiberglass",
    "filament winding services",
    "composite parts",
    "composite products",
    "corrosion resistant products",
]

BUYER_TERMS = [
    "importer",
    "distributor",
    "wholesale distributor",
    "stocking distributor",
    "request a quote",
    "purchasing",
]

SUPPLIER_TERMS = [
    "fiberglass roving manufacturer",
    "glass fiber roving manufacturer",
    "direct roving manufacturer",
    "e-glass roving manufacturer",
    "fiberglass manufacturer",
    "glass fiber manufacturer",
    "roving factory",
    "factory direct",
    "exporter",
    "supplier of fiberglass roving",
    "fiberglass roving production",
    "china wholesale",
    "china direct roving",
    "china deliver on time fiberglass",
    "from china",
    "made in china",
]

SUPPLIER_CATALOG_TERMS = [
    "fiberglass spray up roving",
    "fiberglass woven roving",
    "fiberglass chopped strand mat",
]

NOISE_TERMS = [
    "market report",
    "market research",
    "market size",
    "press release",
    "exhibitor list",
    "directory",
    "yellow pages",
    "lecture notes",
    "university",
    "school of",
    "technical document",
    "research center",
    "government",
    "nasa",
    "ntrs",
    "top 10",
    "top ten",
]

CONTACT_TERMS = [
    "contact us",
    "about us",
    "capabilities",
    "request a quote",
]


def _hits(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def classify_company_site(lead: dict) -> dict:
    text = " ".join(
        str(lead.get(field, "") or "")
        for field in (
            "company_name",
            "website",
            "source_url",
            "notes",
            "raw_text",
        )
    )
    downstream_hits = _hits(text, DOWNSTREAM_TERMS)
    buyer_hits = _hits(text, BUYER_TERMS)
    supplier_hits = _hits(text, SUPPLIER_TERMS)
    supplier_catalog_hits = _hits(text, SUPPLIER_CATALOG_TERMS)
    noise_hits = _hits(text, NOISE_TERMS)
    contact_hits = _hits(text, CONTACT_TERMS)

    if noise_hits:
        return _result("noise", False, 90, noise_hits, "noise source")

    if "+86" in text and len(supplier_catalog_hits) >= 2:
        return _result(
            "supplier",
            False,
            85,
            ["+86", *supplier_catalog_hits],
            "supplier product catalog",
        )

    if supplier_hits and (not buyer_hits or len(supplier_hits) >= 2):
        return _result("supplier", False, 85, supplier_hits, "supplier/manufacturer source")

    if downstream_hits:
        confidence = min(95, 60 + len(downstream_hits) * 10 + len(contact_hits) * 5)
        return _result("downstream_customer", True, confidence, downstream_hits + contact_hits, "downstream usage evidence")

    if buyer_hits:
        confidence = min(90, 55 + len(buyer_hits) * 10 + len(contact_hits) * 5)
        return _result("distributor_or_importer", True, confidence, buyer_hits + contact_hits, "buyer/distributor evidence")

    if supplier_hits:
        return _result("supplier", False, 70, supplier_hits, "supplier/manufacturer source")

    return _result("unknown", False, 30, [], "insufficient website evidence")


def classification_note(classification: dict) -> str:
    evidence = ", ".join(classification.get("evidence", []))
    suffix = f"; evidence={evidence}" if evidence else ""
    label = classification.get("label") or lead_classification_label(classification.get("category"))
    return (
        f"Site classification: {classification['category']} "
        f"label={label} "
        f"confidence={classification['confidence']} "
        f"passed={classification['passed']} "
        f"reason={classification['reason']}{suffix}"
    )


def _result(category: str, passed: bool, confidence: int, evidence: list[str], reason: str) -> dict:
    unique_evidence = list(dict.fromkeys(evidence))[:8]
    label = lead_classification_label(category)
    evidence_text = ", ".join(unique_evidence)
    explanation = f"{reason}; evidence={evidence_text}" if evidence_text else reason
    return {
        "category": category,
        "label": label,
        "passed": passed,
        "confidence": confidence,
        "evidence": unique_evidence,
        "reason": reason,
        "explanation": explanation,
    }
