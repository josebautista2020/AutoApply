"""Conservative country targeting for executive searches."""

from unittest.mock import MagicMock, patch

import pytest

from bot.search.indeed import IndeedSearcher
from bot.search.linkedin import LinkedInSearcher
from config.settings import SearchCriteria
from core.filter import score_job


def _job(location):
    return MagicMock(
        title="Director of Engineering",
        company="Acme",
        location=location,
        description="Lead infrastructure and cloud architecture.",
        salary=None,
    )


def _config(countries):
    config = MagicMock()
    config.search_criteria = SearchCriteria(
        job_titles=["Director of Engineering"],
        locations=["Remote"],
        target_countries=countries,
    )
    config.company_blacklist = []
    config.bot.min_match_score = 70
    return config


def test_country_target_accepts_explicit_listing():
    result = score_job(_job("Madrid, Spain"), _config(["Spain"]))
    assert result.pass_filter
    assert result.score == 75


def test_country_target_rejects_unconfirmed_remote_listing():
    result = score_job(_job("Remote"), _config(["Spain"]))
    assert not result.pass_filter
    assert result.skip_reason == "Country not confirmed in job location"


def test_country_target_does_not_confuse_panama_city_with_country():
    result = score_job(_job("Panama City, Florida"), _config(["Panama"]))
    assert not result.pass_filter


def test_country_target_rejects_currency_agnostic_salary_minimum():
    with pytest.raises(ValueError, match="cross-currency"):
        SearchCriteria(
            job_titles=["Director of Engineering"],
            locations=["Remote"],
            target_countries=["Spain", "Colombia"],
            salary_min=100000,
        )


def test_searchers_query_selected_countries_instead_of_generic_remote():
    criteria = SearchCriteria(
        job_titles=["Director of Engineering"],
        locations=["Remote"],
        target_countries=["Spain", "Colombia"],
    )
    for searcher_class in (LinkedInSearcher, IndeedSearcher):
        searcher = searcher_class()
        with patch.object(searcher, "_search_page", return_value=iter(())) as search_page:
            list(searcher.search(criteria, page=MagicMock()))
        assert [call.args[2] for call in search_page.call_args_list] == ["Spain", "Colombia"]
