"""After-only snapshots of critical review states on both screening details."""

from datetime import datetime, timezone
from unittest.mock import patch

from django.urls import reverse

import pytest

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import (
    L1CriticalScreeningResult,
    L2CriticalScreeningResult,
    ScreeningResultStatus,
)


@pytest.fixture(autouse=True)
def fixed_snapshot_time():
    with patch(
        "django.utils.timezone.now",
        return_value=datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc),
    ):
        yield


def _create_screening_results(critical_status, *, disagrees=False):
    review = ReviewFactory(
        title="Critical screening review",
        description="Deterministic visual test",
    )
    citation = CitationFactory(
        dataset=CitationDatasetFactory(review=review),
        order=1,
        title="Community health study",
        abstract="A study of community health outcomes.",
    )
    l1_question = L1ScreeningQuestionFactory(
        review=review, question_text="Is the citation relevant?"
    )
    l1_include = L1ScreeningQuestionOptionFactory(
        question=l1_question,
        option_text="Include",
        option_value="Relevant study",
    )
    l1_exclude = L1ScreeningQuestionOptionFactory(
        question=l1_question,
        option_text="Exclude",
        option_value="Not relevant",
    )
    l2_question = L2ScreeningQuestionFactory(
        review=review, question_text="Does the full text meet the criteria?"
    )
    l2_include = L2ScreeningQuestionOptionFactory(
        question=l2_question,
        option_text="Include",
        option_value="Meets criteria",
    )
    l2_exclude = L2ScreeningQuestionOptionFactory(
        question=l2_question,
        option_text="Exclude",
        option_value="Does not meet criteria",
    )
    l1_result = L1ScreeningResultFactory(
        citation=citation,
        question=l1_question,
        selected_option=l1_include,
        status=ScreeningResultStatus.COMPLETED,
        confidence=0.84,
        explanation="The abstract matches the review question.",
    )
    l2_result = L2ScreeningResultFactory(
        citation=citation,
        question=l2_question,
        selected_option=l2_include,
        status=ScreeningResultStatus.COMPLETED,
        confidence=0.84,
        explanation="The full text matches the review question.",
        evidence_sentences=[0],
    )
    confidence = (
        0.79 if critical_status == ScreeningResultStatus.COMPLETED else None
    )
    L1CriticalScreeningResult.objects.create(
        initial_result=l1_result,
        status=critical_status,
        selected_option=l1_exclude if disagrees else None,
        confidence=confidence,
    )
    L2CriticalScreeningResult.objects.create(
        initial_result=l2_result,
        status=critical_status,
        selected_option=l2_exclude if disagrees else None,
        confidence=confidence,
    )
    return review, citation


def _capture_detail_panels(
    live_server,
    driver,
    assert_screenshot_matches,
    review,
    citation,
    state,
    expected_text,
    expected_class=None,
):

    from selenium.webdriver.common.by import By

    for level in (1, 2):
        driver.get(
            live_server.url
            + reverse(
                f"l{level}_citation_detail", args=[review.id, citation.id]
            )
        )
        panel = driver.find_element(
            By.XPATH,
            f"//section[.//h2[normalize-space()='L{level} screening results']]",
        )
        assert expected_text in panel.text
        if expected_class is not None:
            assert panel.find_element(
                By.CSS_SELECTOR, expected_class
            ).is_displayed()
        snapshot = panel.find_element(
            By.XPATH,
            ".//dt[normalize-space()='Critical agent review']/following-sibling::dd[1]",
        )
        assert_screenshot_matches(
            driver,
            baseline_name=f"l{level}-critical-{state}",
            element=snapshot,
        )


def test_critical_agent_agrees_visual(
    live_server, driver, admin_user, force_login, assert_screenshot_matches
):
    review, citation = _create_screening_results(
        ScreeningResultStatus.COMPLETED
    )
    force_login(admin_user)
    _capture_detail_panels(
        live_server,
        driver,
        assert_screenshot_matches,
        review,
        citation,
        "agrees",
        "Critical agent agrees (confidence 79%)",
        ".alert-success",
    )


def test_critical_agent_disagrees_visual(
    live_server, driver, admin_user, force_login, assert_screenshot_matches
):
    review, citation = _create_screening_results(
        ScreeningResultStatus.COMPLETED, disagrees=True
    )
    force_login(admin_user)
    _capture_detail_panels(
        live_server,
        driver,
        assert_screenshot_matches,
        review,
        citation,
        "disagrees",
        "Critical agent disagrees — Exclude (confidence 79%)",
        ".alert-danger",
    )


def test_critical_agent_loading_visual(
    live_server, driver, admin_user, force_login, assert_screenshot_matches
):
    review, citation = _create_screening_results(ScreeningResultStatus.PENDING)
    force_login(admin_user)
    _capture_detail_panels(
        live_server,
        driver,
        assert_screenshot_matches,
        review,
        citation,
        "loading",
        "Critical agent review is loading.",
        '[role="status"]',
    )


def test_critical_agent_error_visual(
    live_server, driver, admin_user, force_login, assert_screenshot_matches
):
    review, citation = _create_screening_results(
        ScreeningResultStatus.ABANDONED
    )
    force_login(admin_user)
    _capture_detail_panels(
        live_server,
        driver,
        assert_screenshot_matches,
        review,
        citation,
        "error",
        "Critical agent review could not be completed.",
        '[role="alert"]',
    )
