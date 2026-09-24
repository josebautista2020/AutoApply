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


def test_sponsorship_conflict_is_excluded_with_reason():
    cfg = _config(["United States"])
    cfg.search_criteria.work_authorization = {"United States": "needs_sponsorship"}
    job = _job("New York, United States")
    job.description = "This position offers no visa sponsorship."
    result = score_job(job, cfg)
    assert not result.pass_filter
    assert "explicitly excludes" in result.skip_reason


def test_sponsorship_unknown_stays_in_review_queue():
    cfg = _config(["United States"])
    cfg.search_criteria.work_authorization = {"United States": "needs_sponsorship"}
    result = score_job(_job("New York, United States"), cfg)
    assert result.pass_filter
    assert "confirm employer support" in result.eligibility_note


def test_no_sponsorship_required_is_not_a_rejection():
    cfg = _config(["United States"])
    cfg.search_criteria.work_authorization = {"United States": "needs_sponsorship"}
    job = _job("New York, United States")
    job.description = "No sponsorship required for this opportunity."
    result = score_job(job, cfg)
    assert result.pass_filter
    assert "confirm employer support" in result.eligibility_note


def test_unverified_authorization_is_visible_for_review():
    result = score_job(_job("Bogota, Colombia"), _config(["Colombia"]))
    assert result.pass_filter
    assert "unverified" in result.eligibility_note


def test_authorization_keys_must_match_target_countries():
    with pytest.raises(ValueError, match="work_authorization"):
        SearchCriteria(
            job_titles=["Director"], locations=["Remote"],
            target_countries=["Spain"],
            work_authorization={"United States": "needs_sponsorship"},
        )


def test_executive_ranking_explains_role_signals_without_salary_bonus():
    cfg = _config(["Spain"])
    cfg.search_criteria.executive_mode = True
    job = _job("Madrid, Spain")
    job.description = (
        "Lead teams and strategy, own the roadmap, budget and governance. "
        "Architecture across cloud, platform and infrastructure."
    )
    result = score_job(job, cfg)
    assert result.pass_filter
    assert result.score == 100
    assert any("Leadership scope" in reason for reason in result.priority_reasons)
    assert any("Technical scope" in reason for reason in result.priority_reasons)


def test_executive_ranking_rejects_thin_posting_at_same_threshold():
    cfg = _config(["Spain"])
    cfg.search_criteria.executive_mode = True
    job = _job("Madrid, Spain")
    job.description = "Apply now."
    result = score_job(job, cfg)
    assert result.score == 55
    assert not result.pass_filter
    assert result.skip_reason == "Score 55 below threshold 70"


def test_executive_ranking_does_not_count_substrings_as_signals():
    cfg = _config(["Spain"])
    cfg.search_criteria.executive_mode = True
    job = _job("Madrid, Spain")
    job.description = "Cloudberry products and teamster culture."
    result = score_job(job, cfg)
    assert result.score == 55
    assert not result.pass_filter


def test_executive_ranking_recognizes_spanish_role_scope():
    cfg = _config(["Colombia"])
    cfg.search_criteria.executive_mode = True
    cfg.search_criteria.job_titles = ["Director de Infraestructura Tecnológica"]
    job = _job("Bogotá, Colombia")
    job.title = "Director de Infraestructura Tecnológica"
    job.description = (
        "Liderar equipos y definir la estrategia y el presupuesto. "
        "Arquitectura de nube, plataformas e infraestructura tecnológica."
    )
    result = score_job(job, cfg)
    assert result.pass_filter
    assert result.score == 95
    assert any("liderar" in reason for reason in result.priority_reasons)
    assert any("arquitectura" in reason for reason in result.priority_reasons)


def test_executive_ranking_does_not_double_count_bilingual_synonyms():
    cfg = _config(["Spain"])
    cfg.search_criteria.executive_mode = True
    job = _job("Madrid, Spain")
    job.description = "Lead and liderar team equipos; cloud nube architecture arquitectura."
    result = score_job(job, cfg)
    assert result.score == 75
    assert result.pass_filter


def test_executive_ranking_matches_accents_but_not_partial_words():
    cfg = _config(["Panama"])
    cfg.search_criteria.executive_mode = True
    job = _job("Panama City, Panama")
    job.description = "Gestión y migración; cloudberry y arquitecturaista."
    result = score_job(job, cfg)
    assert result.score == 65
    assert not result.pass_filter


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
