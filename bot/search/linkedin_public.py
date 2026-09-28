"""Read public LinkedIn job cards and details without a login session."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from bot.search.base import RawJob


def _has_class(name: str) -> str:
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def _text(tree, name: str) -> str:
    nodes = tree.xpath(f'//*[{_has_class(name)}]')
    return " ".join(" ".join(nodes[0].itertext()).split()) if nodes else ""


def public_linkedin_jobs(
    title: str, country: str, limit: int, warnings: list[str], *, remote_only: bool = False
):
    """Yield public listings, stopping promptly on a portal rate limit."""
    import requests
    from lxml import html

    params = {"keywords": title, "location": country}
    if remote_only:
        params["f_WT"] = "2"
    response = requests.get("https://www.linkedin.com/jobs/search/", params=params, timeout=25)
    if response.status_code == 429:
        warnings.append("LinkedIn rate limited the search; stop and retry later")
        return
    response.raise_for_status()
    response.encoding = "utf-8"
    cards = html.fromstring(response.text).xpath(f'//*[{_has_class("job-search-card")}]')
    seen: set[str] = set()
    for card in cards:
        urn = card.get("data-entity-urn", "")
        match = re.fullmatch(r"urn:li:jobPosting:(\d+)", urn)
        links = card.xpath(f'.//a[{_has_class("base-card__full-link")}]/@href')
        if not match or not links or match.group(1) in seen:
            continue
        job_url = links[0]
        parsed = urlparse(job_url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or not parsed.path.startswith("/jobs/view/") or not (
            host == "linkedin.com" or host.endswith(".linkedin.com")
        )):
            continue
        seen.add(match.group(1))
        detail_url = job_url.split("?", 1)[0]
        detail = requests.get(detail_url, timeout=25)
        if detail.status_code == 429:
            warnings.append("LinkedIn rate limited job details; preview stopped early")
            return
        detail.raise_for_status()
        detail.encoding = "utf-8"
        tree = html.fromstring(detail.text)
        title_text = _text(tree, "top-card-layout__title")
        company = _text(tree, "topcard__org-name-link")
        if not title_text or not company:
            continue
        yield RawJob(
            title=title_text, company=company,
            location=_text(tree, "topcard__flavor--bullet"),
            salary=None, description=_text(tree, "show-more-less-html__markup"),
            apply_url=detail_url, platform="linkedin",
            external_id=f"linkedin-{match.group(1)}", posted_at=None,
        )
        if len(seen) >= limit:
            return
