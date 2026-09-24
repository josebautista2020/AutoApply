"""Preview real search results and filter decisions without generating or applying.

Run from the repository: python scripts/preview_search.py --config private/config.json
The command prints JSON and opens a browser; it does not write application data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.bot import SEARCHERS  # noqa: E402
from bot.browser import BrowserManager  # noqa: E402
from bot.search.base import RawJob  # noqa: E402
from config.settings import AppConfig, get_data_dir  # noqa: E402
from core.filter import score_job  # noqa: E402


def _preview_entry(job: RawJob, config: AppConfig) -> dict:
    scored = score_job(job, config)
    return {
        "platform": job.platform,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.apply_url,
        "score": scored.score,
        "review_candidate": scored.pass_filter,
        "reason": scored.skip_reason,
        "eligibility_note": scored.eligibility_note,
        "priority_reasons": scored.priority_reasons,
        "description_present": bool(job.description.strip()),
    }


def preview_jobs(config: AppConfig, page, platforms: list[str], limit: int) -> list[dict]:
    """Use the production searchers and scorer, stopping after ``limit`` jobs."""
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for platform in platforms:
        for job in SEARCHERS[platform]().search(config.search_criteria, page=page):
            key = (job.platform, job.external_id)
            if key in seen:
                continue
            seen.add(key)
            results.append(_preview_entry(job, config))
            if len(results) >= limit:
                return results
    return results


def _has_class(name: str) -> str:
    return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'


def _text(tree, name: str) -> str:
    nodes = tree.xpath(f'//*[{_has_class(name)}]')
    return " ".join(" ".join(nodes[0].itertext()).split()) if nodes else ""


def public_linkedin_jobs(title: str, country: str, limit: int, warnings: list[str]):
    """Read public HTML only; no browser session, login, or application flow."""
    import requests
    from lxml import html

    response = requests.get(
        "https://www.linkedin.com/jobs/search/",
        params={"keywords": title, "location": country}, timeout=25,
    )
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
        host = urlparse(job_url).hostname or ""
        if (urlparse(job_url).scheme != "https" or
            not urlparse(job_url).path.startswith("/jobs/view/") or not (
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=get_data_dir() / "config.json")
    parser.add_argument("--platform", choices=sorted(SEARCHERS), action="append")
    parser.add_argument("--country", help="One country from target_countries")
    parser.add_argument("--title", help="One title from job_titles")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--public-html", action="store_true",
                        help="Read public LinkedIn HTML without Chromium (single country/title)")
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if not args.config.is_file():
        parser.error(f"Configuration not found: {args.config}")
    try:
        config = AppConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    except ValueError as exc:
        parser.error(f"Invalid configuration: {exc}")
    if args.country:
        if args.country not in config.search_criteria.target_countries:
            parser.error("--country must be present in target_countries")
        config.search_criteria.target_countries = [args.country]
        config.search_criteria.work_authorization = {
            key: value for key, value in config.search_criteria.work_authorization.items()
            if key == args.country
        }
    if args.title:
        if args.title not in config.search_criteria.job_titles:
            parser.error("--title must be present in job_titles")
        config.search_criteria.job_titles = [args.title]

    # Only search and score. This entry point never calls the document generator,
    # the review approval gate, an applier, or the application database.
    platforms = args.platform or ["linkedin"]
    warnings: list[str] = []
    if args.public_html:
        if platforms != ["linkedin"] or not args.country or not args.title:
            parser.error("--public-html requires --platform linkedin, --country and --title")
        if args.limit > 5:
            parser.error("--public-html supports at most 5 jobs per run")
        try:
            jobs = [_preview_entry(job, config) for job in public_linkedin_jobs(
                args.title, args.country, args.limit, warnings
            )]
        except Exception as exc:
            parser.exit(2, f"Public LinkedIn preview failed: {exc}\n")
    else:
        browser = BrowserManager(config)
        try:
            jobs = preview_jobs(config, browser.get_page(), platforms, args.limit)
        finally:
            browser.close()
    print(json.dumps({
        "jobs": jobs,
        "count": len(jobs),
        "scope": {"countries": config.search_criteria.target_countries,
                  "titles": config.search_criteria.job_titles,
                  "platforms": platforms},
        "warnings": warnings + ([
            "Empty results do not confirm that the portal was accessible or had no jobs"
        ] if not jobs else []),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
