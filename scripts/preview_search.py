"""Preview real search results and filter decisions without generating or applying.

Run from the repository: python scripts/preview_search.py --config private/config.json
The command prints JSON and opens a browser; it does not write application data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.bot import SEARCHERS  # noqa: E402
from bot.browser import BrowserManager  # noqa: E402
from bot.search.base import RawJob  # noqa: E402
from bot.search.linkedin_public import public_linkedin_jobs  # noqa: E402
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


def preview_jobs(
    config: AppConfig, page, platforms: list[str], limit: int,
    source_info: list[str] | None = None,
) -> list[dict]:
    """Use the production searchers and scorer, stopping after ``limit`` jobs."""
    # SearchCriteria is a Pydantic model; runtime limits belong on a copy.
    criteria = SimpleNamespace(
        **config.search_criteria.model_dump(),
        max_results_per_search=limit,
        max_pages_per_search=1,
        max_cards_per_page=min(limit * 2, 10),
    )
    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for platform in platforms:
        searcher = SEARCHERS[platform]()
        for job in searcher.search(criteria, page=page):
            if source_info is not None and getattr(searcher, "used_public_fallback", False):
                source_info.append("public_html_fallback")
            key = (job.platform, job.external_id)
            if key in seen:
                continue
            seen.add(key)
            results.append(_preview_entry(job, config))
            if len(results) >= limit:
                return results
    return results


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
    source = "public_html" if args.public_html else "browser"
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
        source_info: list[str] = []
        try:
            jobs = preview_jobs(config, browser.get_page(), platforms, args.limit,
                                source_info=source_info)
        finally:
            browser.close()
        if source_info:
            source = source_info[0]
            warnings.append("Browser cards could not be opened; using public LinkedIn HTML")
        if not jobs and platforms == ["linkedin"] and args.country and args.title:
            warnings.append("Browser extraction returned no jobs; trying public LinkedIn HTML")
            source = "public_html_fallback"
            try:
                jobs = [_preview_entry(job, config) for job in public_linkedin_jobs(
                    args.title, args.country, min(args.limit, 5), warnings
                )]
            except Exception as exc:
                warnings.append(f"Public LinkedIn fallback failed: {exc}")
    print(json.dumps({
        "jobs": jobs,
        "count": len(jobs),
        "source": source,
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
