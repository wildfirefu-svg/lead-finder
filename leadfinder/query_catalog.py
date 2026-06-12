from __future__ import annotations

QUERY_EXCLUSIONS = (
    "-site:zauba.com -site:thomasnet.com -site:exporthub.com "
    "-site:seair.co.in -site:volza.com -site:tradeindia.com "
    "-site:alibaba.com -site:made-in-china.com -site:globalsources.com "
    "-site:facebook.com -site:linkedin.com -site:openpr.com "
    "-site:instagram.com -site:pinterest.com -site:youtube.com "
    "-site:prnewswire.com -site:globenewswire.com -site:indexbox.io "
    "-site:justdial.com -site:jec-world.events -site:researchandmarkets.com "
    "-site:tradekey.com -site:kenresearch.com -site:marketreportanalytics.com "
    "-site:marketresearchfuture.com -site:marketresearch.com -site:datainsightsreports.com "
    "-filetype:pdf -site:compositesworld.com -site:scribd.com -site:marketresearch.biz "
    "-site:nasa.gov -site:okorder.com"
)

HS_PRODUCT_FAMILIES = {
    "7019": [
        "roving",
        "yarn",
        "woven_fabric",
        "mat",
        "mesh",
        "chopped_strand",
        "tissue",
        "insulation_fabric",
    ],
    "701911": ["chopped_strand"],
    "701912": ["roving"],
    "701913": ["yarn"],
    "701914": ["mat"],
    "701915": ["mat"],
    "701919": ["roving", "yarn", "mat", "chopped_strand"],
    "701961": ["woven_fabric"],
    "701962": ["woven_fabric"],
    "701963": ["woven_fabric"],
    "701964": ["woven_fabric"],
    "701965": ["mesh"],
    "701966": ["mesh"],
    "701969": ["woven_fabric"],
    "701971": ["tissue"],
    "701972": ["tissue"],
    "701973": ["mesh"],
    "701980": ["insulation_fabric"],
    "701990": ["roving", "yarn", "woven_fabric", "mat", "mesh", "tissue"],
}

PRODUCT_FAMILY_LABELS = {
    "all": "全部",
    "roving": "粗纱 / Roving",
    "yarn": "纱线 / Yarn",
    "woven_fabric": "织物 / Woven Fabric",
    "mat": "毡 / Mat",
    "mesh": "网格布 / Mesh",
    "chopped_strand": "短切原丝 / Chopped Strand",
    "tissue": "薄毡 / Tissue",
    "insulation_fabric": "绝缘布 / Insulation Fabric",
}

COUNTRY_LOCALES = {
    "canada": "en-CA",
    "usa": "en-US",
    "united states": "en-US",
    "mexico": "es-MX",
    "germany": "de-DE",
    "france": "fr-FR",
    "united kingdom": "en-GB",
    "italy": "it-IT",
    "spain": "es-ES",
    "netherlands": "nl-NL",
    "poland": "pl-PL",
    "vietnam": "vi-VN",
    "thailand": "th-TH",
    "indonesia": "id-ID",
    "malaysia": "en-MY",
    "philippines": "en-PH",
    "singapore": "en-SG",
    "india": "en-IN",
    "united arab emirates": "ar-AE",
    "saudi arabia": "ar-SA",
    "turkey": "tr-TR",
    "japan": "ja-JP",
    "south korea": "ko-KR",
    "brazil": "pt-BR",
    "morocco": "fr-MA",
    "south africa": "en-ZA",
}

QUERY_TEMPLATES = {
    "roving": [
        '"fiberglass roving" "pultrusion" "capabilities" {country}',
        '"fiberglass roving" "filament winding" "capabilities" {country}',
        '"fiberglass roving" "FRP" "contact us" {country}',
        '"fiberglass roving" "custom pultrusions" {country}',
    ],
    "yarn": [
        '"glass fiber yarn" "composites" {country}',
        '"fiberglass yarn" buyer {country}',
        '"glass fibre yarn" "FRP" {country}',
    ],
    "woven_fabric": [
        '"fiberglass fabric" importer {country}',
        '"woven roving" buyer {country}',
        '"fiberglass cloth" distributor {country}',
        '"insulation fabric" composites {country}',
    ],
    "mat": [
        '"chopped strand mat" buyer {country}',
        '"glass fiber mat" composites {country}',
        '"FRP" "mat" "contact us" {country}',
    ],
    "mesh": [
        '"fiberglass mesh" importer {country}',
        '"glass fiber mesh" distributor {country}',
        '"reinforcement mesh" composites {country}',
    ],
    "chopped_strand": [
        '"chopped strand" composites {country}',
        '"glass fiber chopped strand" buyer {country}',
        '"thermoplastic" "glass fiber" {country}',
    ],
    "tissue": [
        '"glass fiber tissue" buyer {country}',
        '"fiberglass veil" composites {country}',
        '"surface tissue" FRP {country}',
    ],
    "insulation_fabric": [
        '"insulation fabric" "glass fiber" {country}',
        '"heat resistant fiberglass cloth" {country}',
        '"thermal insulation fabric" composites {country}',
    ],
}

LOCALIZED_TEMPLATES = {
    ("germany", "roving"): [
        'site:.de "glasfaser roving" "pultrusion"',
        'site:.de "GFK" "profile"',
        '"GFK" "Roving" Deutschland',
    ],
    ("france", "roving"): [
        'site:.fr "fibre de verre" "pultrusion"',
        'site:.fr "roving fibre de verre"',
    ],
    ("morocco", "roving"): [
        'site:.ma "fibre de verre" "composite"',
        '"fibre de verre" "Maroc" "composite"',
    ],
    ("canada", "roving"): [
        'site:.ca "FRP grating" "contact"',
        'site:.ca "fiberglass rebar"',
        'site:.ca "pultrusion" "FRP"',
        '"fiberglass reinforced plastic" Canada "contact us"',
        '"fiberglass rebar" Canada "contact us"',
        '"fiberglass roving" "Ontario" "composites"',
    ],
    ("mexico", "roving"): [
        'site:.mx "fibra de vidrio" "pultrusion"',
        '"fibra de vidrio" "FRP" Mexico',
    ],
    ("germany", "woven_fabric"): [
        'site:.de "glasfasergewebe" "GFK"',
    ],
    ("france", "woven_fabric"): [
        'site:.fr "tissu fibre de verre"',
    ],
    ("brazil", "woven_fabric"): [
        'site:.br "fibra de vidro" "tecido"',
    ],
}

LEGACY_PRODUCT_ALIASES = {
    "all": "all",
    "both": "all",
    "fiberglass_yarn": "roving",
    "fiberglass-yarn": "roving",
    "roving": "roving",
    "yarn": "yarn",
    "fiberglass_fabric": "woven_fabric",
    "fiberglass-fabric": "woven_fabric",
    "fabric": "woven_fabric",
    "woven_fabric": "woven_fabric",
    "woven-fabric": "woven_fabric",
    "mat": "mat",
    "mesh": "mesh",
    "chopped_strand": "chopped_strand",
    "chopped-strand": "chopped_strand",
    "tissue": "tissue",
    "insulation_fabric": "insulation_fabric",
    "insulation-fabric": "insulation_fabric",
}


def product_families_for_hs(hs_code: str, selected_product: str = "all") -> list[str]:
    product_key = str(selected_product or "all").strip().lower().replace("-", "_")
    normalized_product = LEGACY_PRODUCT_ALIASES.get(product_key, product_key)
    normalized_hs = "".join(char for char in str(hs_code or "") if char.isdigit())
    if normalized_product and normalized_product != "all":
        return [normalized_product]
    return list(HS_PRODUCT_FAMILIES.get(normalized_hs, HS_PRODUCT_FAMILIES["7019"]))


def build_query_specs(country: str, hs_code: str, selected_product: str = "all") -> list[dict]:
    country_name = str(country or "").strip()
    country_key = country_name.lower()
    locale = COUNTRY_LOCALES.get(country_key, "en-US")
    specs: list[dict] = []
    for family in product_families_for_hs(hs_code, selected_product):
        templates: list[str] = []
        templates.extend(LOCALIZED_TEMPLATES.get((country_key, family), []))
        templates.extend(QUERY_TEMPLATES.get(family, []))
        for template in templates:
            query = f"{template.format(country=country_name)} {QUERY_EXCLUSIONS}".strip()
            specs.append(
                {
                    "country": country_name,
                    "locale": locale,
                    "product_family": family,
                    "query": query,
                }
            )
    deduped: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for spec in specs:
        key = (spec["country"], spec["locale"], spec["product_family"], spec["query"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped
