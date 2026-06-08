from __future__ import annotations

import json
import urllib.request


APOLLO_PEOPLE_URL = "https://api.apollo.io/v1/mixed_people/search"


class ApolloClient:
    def __init__(self, api_key: str, endpoint: str = APOLLO_PEOPLE_URL, timeout: float = 12.0):
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout

    def people_search(self, company: str, country: str = "", per_page: int = 3) -> dict:
        if not self.api_key:
            raise RuntimeError("APOLLO_API_KEY is required for Apollo enrichment.")
        payload = json.dumps(
            {
                "q_organization_name": company,
                "person_titles": ["purchasing", "procurement", "sourcing", "buyer", "import", "manager"],
                "page": 1,
                "per_page": max(1, min(int(per_page), 10)),
                "organization_locations": [country] if country else [],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "api_key": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "LeadFinder/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def apollo_people_to_contact(payload: dict) -> dict:
    people = payload.get("people") or payload.get("contacts") or []
    if not people:
        return {"contact_name": "", "notes": "Apollo: no matching contact returned"}
    person = people[0]
    name = person.get("name") or " ".join(part for part in [person.get("first_name"), person.get("last_name")] if part)
    title = person.get("title") or ""
    organization = person.get("organization") or {}
    org_name = organization.get("name") or ""
    notes = "Apollo contact"
    if title:
        notes += f": {title}"
    if org_name:
        notes += f" at {org_name}"
    return {"contact_name": name or "", "notes": notes}
