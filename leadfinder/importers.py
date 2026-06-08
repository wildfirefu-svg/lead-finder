from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .db import create_or_skip_lead
from .enrich import normalize_url
from .scoring import score_lead


BILL_OF_LADING_SOURCES = {"外贸邦", "易之家", "waitubang", "yizhijia", "bill_of_lading"}
SAAS_CONTACT_SOURCES = {"apollo.io", "apollo", "snov.io", "snov"}

ALIASES = {
    "company_name": ["company_name", "company", "company name", "importer", "buyer", "consignee", "organization", "account"],
    "country_region": ["country_region", "country", "region", "market", "destination country"],
    "market_region": ["market_region", "market", "country", "region", "destination country"],
    "website": ["website", "domain", "company website", "url", "site"],
    "source_url": ["source_url", "source url", "url", "profile url", "apollo url", "snov url"],
    "contact_name": ["contact_name", "contact name", "name", "person", "decision maker"],
    "email": ["email", "email address", "work email", "business email"],
    "industry": ["industry", "category", "business type"],
    "raw_text": ["raw_text", "description", "product", "shipment summary", "bill summary", "notes", "hs code"],
}


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped: int


def _clean_key(value: str) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _lookup(row: dict[str, str], field: str) -> str:
    cleaned = {_clean_key(key): str(value or "").strip() for key, value in row.items()}
    for alias in ALIASES[field]:
        value = cleaned.get(_clean_key(alias), "")
        if value:
            return value
    return ""


def _source_type(source: str) -> str:
    key = source.strip().lower()
    if key in BILL_OF_LADING_SOURCES:
        return "Bill of Lading"
    if key in SAAS_CONTACT_SOURCES:
        return "SaaS Contact"
    return "Manual CSV"


def normalize_source_row(row: dict[str, str], source: str) -> dict:
    country = _lookup(row, "country_region")
    website = _lookup(row, "website")
    source_url = _lookup(row, "source_url") or website
    raw_parts = [
        _lookup(row, "raw_text"),
        _lookup(row, "industry"),
        _lookup(row, "company_name"),
    ]
    raw_text = " ".join(part for part in raw_parts if part).strip()
    notes = [f"Source: {source}"]
    if _source_type(source) == "SaaS Contact":
        notes.append(f"Contact source: {source}")
    if _source_type(source) == "Bill of Lading":
        notes.append("Evidence: public bill-of-lading/import record")

    return {
        "source_type": _source_type(source),
        "source_name": source,
        "company_name": _lookup(row, "company_name"),
        "country_region": country,
        "market_region": _lookup(row, "market_region") or country,
        "website": normalize_url(website) if website else "",
        "source_url": normalize_url(source_url) if source_url else "",
        "contact_name": _lookup(row, "contact_name"),
        "email": _lookup(row, "email").lower(),
        "industry": _lookup(row, "industry"),
        "product_fit": "Both",
        "fit_reason": "",
        "match_score": 0,
        "status": "Discovered",
        "notes": "\n".join(notes),
        "raw_text": raw_text,
    }


def import_csv(db, input_path: str | Path, source: str) -> ImportResult:
    created = 0
    skipped = 0
    with Path(input_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            lead = normalize_source_row(row, source=source)
            scored = {**lead, **score_lead(lead)}
            _, was_created = create_or_skip_lead(db, scored)
            created += int(was_created)
            skipped += int(not was_created)
    return ImportResult(created=created, skipped=skipped)
