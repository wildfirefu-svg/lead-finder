from __future__ import annotations

import html
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,5}\d{2,4}")
HREF_RE = re.compile(r"href\s*=\s*['\"]([^'\"]+)['\"]", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
META_DESC_RE = re.compile(
    r"<meta[^>]+name\s*=\s*['\"]description['\"][^>]+content\s*=\s*['\"]([^'\"]+)['\"]",
    re.I | re.S,
)
SITE_NAME_RE = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*['\"](?:og:site_name|application-name)['\"][^>]+content\s*=\s*['\"]([^'\"]+)['\"]",
    re.I | re.S,
)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[\s\S]*?</\1>", re.I)
PRIORITY_LINK_RE = re.compile(
    r"contact|about|product|company|supplier|fabric|fiberglass|fibreglass|glass-fiber|glass-fibre|roving|yarn",
    re.I,
)
SOCIAL_RE = re.compile(r"linkedin\.com|facebook\.com|twitter\.com|x\.com", re.I)
PLACEHOLDER_EMAIL_DOMAINS = {"example.com", "example.net", "example.org"}
PLACEHOLDER_EMAIL_USERS = {"contoso", "example", "test", "noreply", "no-reply"}


def normalize_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^https?://", text, re.I):
        return text
    return f"https://{text}"


def normalize_domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(normalize_url(url)).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def strip_html(markup: str) -> str:
    text = SCRIPT_STYLE_RE.sub(" ", markup or "")
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def extract_emails(text: str) -> list[str]:
    emails = EMAIL_RE.findall(text or "")
    return sorted(
        {
            email.lower()
            for email in emails
            if not re.search(r"\.(png|jpg|jpeg|gif|webp|svg)$", email, re.I)
            and email.split("@", 1)[1].lower() not in PLACEHOLDER_EMAIL_DOMAINS
            and email.split("@", 1)[0].lower() not in PLACEHOLDER_EMAIL_USERS
        }
    )


def extract_phones(text: str) -> list[str]:
    phones = []
    for match in PHONE_RE.findall(text or ""):
        cleaned = re.sub(r"\s+", " ", match).strip(" .-")
        digits = re.sub(r"\D", "", cleaned)
        if 7 <= len(digits) <= 16:
            phones.append(cleaned)
    return sorted(set(phones))


def title_from_html(markup: str) -> str:
    match = TITLE_RE.search(markup or "")
    return strip_html(match.group(1))[:160] if match else ""


def description_from_html(markup: str) -> str:
    match = META_DESC_RE.search(markup or "")
    return strip_html(match.group(1))[:500] if match else ""


def site_name_from_html(markup: str) -> str:
    match = SITE_NAME_RE.search(markup or "")
    return strip_html(match.group(1))[:120] if match else ""


def page_links(markup: str, base_url: str) -> list[str]:
    links = []
    for href in HREF_RE.findall(markup or ""):
        try:
            next_url = urllib.parse.urljoin(base_url, href)
            parsed = urllib.parse.urlparse(next_url)
        except ValueError:
            continue
        if parsed.scheme in {"http", "https"}:
            cleaned = parsed._replace(fragment="").geturl()
            links.append(cleaned)
    return list(dict.fromkeys(links))


def same_domain(url: str, seed_url: str) -> bool:
    return normalize_domain(url) == normalize_domain(seed_url)


def company_from_domain(url: str) -> str:
    domain = normalize_domain(url)
    if not domain:
        return ""
    name = domain.split(".")[0]
    return re.sub(r"[-_]+", " ", name).title()


def _protocol_candidates(url: str) -> list[str]:
    normalized = normalize_url(url)
    parsed = urllib.parse.urlparse(normalized)
    alternate = parsed._replace(
        scheme="http" if parsed.scheme == "https" else "https"
    ).geturl()
    return [normalized, alternate]


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return 500 <= int(error.code) < 600
    return isinstance(
        error,
        (urllib.error.URLError, TimeoutError, socket.timeout),
    )


def fetch_text(url: str, timeout: float = 12.0, retries: int = 1) -> tuple[str, str]:
    errors: list[Exception] = []
    for candidate in _protocol_candidates(url):
        for _ in range(max(0, int(retries)) + 1):
            request = urllib.request.Request(
                candidate,
                headers={"User-Agent": "LeadFinder/0.1 (+https://local.invalid)"},
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" not in content_type and "text/plain" not in content_type and content_type:
                        return "", response.geturl()
                    charset = response.headers.get_content_charset() or "utf-8"
                    body = response.read(1_000_000).decode(charset, errors="replace")
                    return body, response.geturl()
            except (urllib.error.URLError, TimeoutError, ValueError, socket.timeout) as error:
                errors.append(error)
                if not _is_retryable(error):
                    break
    if errors:
        raise errors[-1]
    return "", normalize_url(url)


def clean_company_name(existing: str, site_names: list[str], titles: list[str], url: str) -> str:
    for site_name in site_names:
        candidate = str(site_name or "").strip()
        if candidate and candidate.lower() not in {"home", "homepage", "official website"}:
            return candidate[:160]

    current = str(existing or "").strip()
    title_like = bool(re.search(r"\s[-|–—]\s|^home\b|^welcome\b", current, re.I))
    if current and not title_like:
        return current[:160]

    domain_name = company_from_domain(url)
    if domain_name:
        return domain_name[:160]

    for title in titles:
        candidate = re.sub(r"^(home|welcome)\s*[-|–—:]\s*", "", title, flags=re.I).strip()
        if candidate:
            return candidate[:160]
    return current[:160]


def enrich_site(url: str, defaults: dict | None = None, max_pages: int = 5, timeout: float = 12.0) -> dict:
    defaults = defaults or {}
    seed_url = normalize_url(url)
    visited: set[str] = set()
    queue: deque[str] = deque([seed_url])
    texts: list[str] = []
    titles: list[str] = []
    descriptions: list[str] = []
    site_names: list[str] = []
    emails: set[str] = set()
    phones: set[str] = set()
    socials: set[str] = set()
    errors: list[str] = []

    while queue and len(visited) < max_pages:
        current = queue.popleft()
        if current in visited or not same_domain(current, seed_url):
            continue
        visited.add(current)
        try:
            markup, final_url = fetch_text(current, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            errors.append(f"{current}: {error}")
            continue
        if not markup:
            continue

        title = title_from_html(markup)
        description = description_from_html(markup)
        site_name = site_name_from_html(markup)
        text = strip_html(markup)
        if title:
            titles.append(title)
        if description:
            descriptions.append(description)
        if site_name:
            site_names.append(site_name)
        if text:
            texts.append(text[:2500])
        extract_emails(markup + " " + text).copy()
        emails.update(extract_emails(markup + " " + text))
        phones.update(extract_phones(text))
        for link in page_links(markup, final_url):
            if SOCIAL_RE.search(link):
                socials.add(link)
            if same_domain(link, seed_url) and link not in visited:
                queue.append(link)
        queue = deque(
            sorted(
                list(dict.fromkeys(queue)),
                key=lambda item: 0 if PRIORITY_LINK_RE.search(item) else 1,
            )
        )

    raw_text = " ".join([*descriptions, *texts])[:8000]
    notes = []
    if phones:
        notes.append("Phones: " + "; ".join(sorted(phones)[:3]))
    if socials:
        notes.append("Social: " + "; ".join(sorted(socials)[:3]))
    successful_pages = len(texts)
    crawl_status = "success" if successful_pages else "error"
    if successful_pages and errors:
        crawl_status = "partial"
    notes.append(f"Crawler status: {crawl_status}")
    notes.append(f"Crawler pages: {successful_pages}/{len(visited)}")
    if errors:
        notes.append("Errors: " + " | ".join(errors[:3]))

    return {
        "source_type": defaults.get("source_type", "Website"),
        "source_name": defaults.get("source_name", ""),
        "company_name": clean_company_name(
            defaults.get("company_name", ""),
            site_names,
            titles,
            seed_url,
        ),
        "country_region": defaults.get("country_region", ""),
        "market_region": defaults.get("market_region", ""),
        "website": seed_url,
        "source_url": defaults.get("source_url", seed_url),
        "contact_name": defaults.get("contact_name", ""),
        "email": defaults.get("email") or (sorted(emails)[0] if emails else ""),
        "industry": defaults.get("industry", ""),
        "crawl_status": crawl_status,
        "notes": "\n".join(notes),
        "raw_text": raw_text,
    }
