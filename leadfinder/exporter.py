from __future__ import annotations

import csv
import io
from pathlib import Path

CRM_FIELDS = [
    "source_type",
    "source_name",
    "company_name",
    "country_region",
    "market_region",
    "website",
    "source_url",
    "contact_name",
    "email",
    "industry",
    "product_fit",
    "fit_reason",
    "match_score",
    "notes",
    "raw_text",
]


def export_csv(leads: list[dict], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CRM_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow({field: lead.get(field, "") for field in CRM_FIELDS})
    return path


def export_csv_bytes(leads: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CRM_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow({field: lead.get(field, "") for field in CRM_FIELDS})
    return ("\ufeff" + output.getvalue()).encode("utf-8")
