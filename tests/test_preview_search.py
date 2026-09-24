"""Safe preview of search and scoring without a submission flow."""

import json
import sys
from unittest.mock import MagicMock, patch

from bot.search.base import RawJob
from config.settings import SearchCriteria
from scripts.preview_search import main, preview_jobs, public_linkedin_jobs


def _job(job_id, location, description="Lead cloud architecture and teams."):
    return RawJob(
        title="Director of Engineering", company="Acme", location=location,
        salary=None, description=description, apply_url=f"https://example.com/{job_id}",
        platform="linkedin", external_id=job_id, posted_at=None,
    )


def test_preview_uses_real_scorer_deduplicates_and_limits_results():
    config = MagicMock()
    config.search_criteria = SearchCriteria(
        job_titles=["Director of Engineering"], locations=["Remote"],
        target_countries=["Colombia"], executive_mode=True,
    )
    config.bot.min_match_score = 70
    config.company_blacklist = []

    class Searcher:
        def search(self, criteria, page):
            yield _job("one", "Bogota, Colombia")
            yield _job("one", "Bogota, Colombia")
            yield _job("two", "Remote")
            yield _job("three", "Bogota, Colombia")

    with patch("scripts.preview_search.SEARCHERS", {"linkedin": Searcher}):
        results = preview_jobs(config, page=MagicMock(), platforms=["linkedin"], limit=2)

    assert [item["url"] for item in results] == [
        "https://example.com/one", "https://example.com/two",
    ]
    assert results[0]["review_candidate"] is True
    assert results[0]["description_present"] is True
    assert results[1]["review_candidate"] is False
    assert results[1]["reason"] == "Country not confirmed in job location"


def test_preview_cli_scopes_country_and_title_without_application(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "profile": {
            "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com",
            "phone": "5550100", "city": "Bogota", "state": "", "country": "Colombia",
            "bio": "Architect",
        },
        "search_criteria": {
            "job_titles": ["Director of Engineering", "Director de Ingeniería"],
            "locations": ["Remote"], "target_countries": ["Colombia", "Spain"],
            "work_authorization": {"Colombia": "authorized", "Spain": "unknown"},
        },
    }), encoding="utf-8")
    args = ["preview_search.py", "--config", str(path), "--country", "Colombia",
            "--title", "Director de Ingeniería", "--limit", "2"]
    with patch.object(sys, "argv", args), patch("scripts.preview_search.BrowserManager") as browser:
        with patch("scripts.preview_search.preview_jobs", return_value=[]) as preview:
            assert main() == 0
    scoped = preview.call_args.args[0]
    assert scoped.search_criteria.target_countries == ["Colombia"]
    assert scoped.search_criteria.work_authorization == {"Colombia": "authorized"}
    assert scoped.search_criteria.job_titles == ["Director de Ingeniería"]
    assert preview.call_args.args[-1] == 2
    assert browser.return_value.close.called
    assert "Empty results do not confirm" in capsys.readouterr().out


def test_public_html_preview_reads_cards_and_stops_at_rate_limit():
    search = MagicMock(status_code=200, text=(
        '<div class="job-search-card" data-entity-urn="urn:li:jobPosting:123">'
        '<a class="base-card__full-link" href="https://co.linkedin.com/jobs/view/job-123?tracking=x">'
        'Job</a></div>'
        '<div class="job-search-card" data-entity-urn="urn:li:jobPosting:456">'
        '<a class="base-card__full-link" href="https://co.linkedin.com/jobs/view/job-456">'
        'Job</a></div>'
    ))
    detail = MagicMock(status_code=200, text=(
        '<h1 class="top-card-layout__title">Director of Engineering</h1>'
        '<a class="topcard__org-name-link">Acme</a>'
        '<span class="topcard__flavor--bullet">Bogotá, Colombia</span>'
        '<div class="show-more-less-html__markup">Lead cloud teams.</div>'
    ))
    limited = MagicMock(status_code=429)
    warnings = []
    with patch("requests.get", side_effect=[search, detail, limited]) as get:
        jobs = list(public_linkedin_jobs("Director", "Colombia", 5, warnings))

    assert len(jobs) == 1
    assert jobs[0].description == "Lead cloud teams."
    assert jobs[0].external_id == "linkedin-123"
    assert get.call_args_list[1].args[0] == "https://co.linkedin.com/jobs/view/job-123"
    assert warnings == ["LinkedIn rate limited job details; preview stopped early"]
