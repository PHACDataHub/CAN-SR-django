"""Capture phase 2 previews for inspection, without comparing image baselines."""

from datetime import datetime, timezone
from unittest.mock import patch

from django.urls import reverse

import pytest

from my_app.model_factories import (
    BulkWorkflowRequestFactory,
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    Phase2CitationWorkflowRequestFactory,
    ReviewFactory,
)
from my_app.models import ScreeningActions
from tests.selenium.visual_comparison_utils import set_viewport

FIXED_TIME = datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc)


@pytest.fixture(params=["desktop", "mobile"])
def viewport(request, driver, live_server, settings):
    settings.ENABLE_HTMX_POLLING = False
    width, height = (1280, 1100)
    if request.param == "mobile":
        width, height = (390, 1500)
    driver.set_window_size(width, height)
    driver.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": False,
        },
    )
    with patch("django.utils.timezone.now", return_value=FIXED_TIME):
        yield request.param
        driver.get(live_server.url + "/health/live")
    set_viewport(driver)


def workflow_context():
    review = ReviewFactory(
        title="Community interventions and respiratory health"
    )
    citation = CitationFactory(
        dataset__review=review,
        title="Community-based interventions to reduce respiratory illness among older adults: a systematic review of randomized studies",
    )
    question = L1ScreeningQuestionFactory(review=review)
    option = L1ScreeningQuestionOptionFactory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    L1HumanAnswerFactory(
        citation=citation, question=question, selected_option=option
    )
    return review, citation


def capture_page(driver, live_server, save_screenshot, url, name):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(live_server.url + url)
    WebDriverWait(driver, 10).until(
        ec.visibility_of_element_located((By.TAG_NAME, "h1"))
    )
    assert save_screenshot(driver, snapshot_name=name).is_file()


@pytest.mark.parametrize("scope", ["citation", "bulk"])
@pytest.mark.parametrize(
    "case", ["ready", "no-selection", "unconfigured-l2", "already-pending"]
)
def test_phase2_launch_screenshots(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    viewport,
    scope,
    case,
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    review, citation = workflow_context()
    if case == "already-pending":
        Phase2CitationWorkflowRequestFactory(citation=citation)
    elif case == "ready":
        question = L2ScreeningQuestionFactory(review=review)
        L2ScreeningQuestionOptionFactory(question=question)

    url = reverse("phase2_citation_workflow", args=[review.pk, citation.pk])
    if scope == "bulk":
        url = reverse("phase2_bulk_workflow", args=[review.pk])
    force_login(admin_user)
    driver.get(live_server.url + url)
    wait = WebDriverWait(driver, 10)
    submit = wait.until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
    )
    if case != "ready":
        selected = None
        if case == "unconfigured-l2":
            selected = "should_run_l2"
        elif case == "already-pending":
            selected = "should_download_pdf"
        for name in (
            "should_download_pdf",
            "should_process_pdf",
            "should_run_l2",
        ):
            checkbox = driver.find_element(By.NAME, name)
            if checkbox.is_selected() != (name == selected):
                checkbox.click()
        submit.click()
        try:
            wait.until(
                lambda browser: any(
                    alert.is_displayed()
                    for alert in browser.find_elements(
                        By.CSS_SELECTOR, ".alert-danger"
                    )
                )
            )
        except Exception:
            save_screenshot(
                driver,
                snapshot_name=f"phase2-{scope}-launch-{case}-{viewport}",
            )
            raise
    assert save_screenshot(
        driver, snapshot_name=f"phase2-{scope}-launch-{case}-{viewport}"
    ).is_file()


@pytest.mark.parametrize(
    "scope,case",
    [
        ("citation", "pending"),
        ("citation", "completed"),
        ("citation", "failed"),
        ("bulk", "empty"),
        ("bulk", "pending"),
        ("bulk", "mixed"),
        ("bulk", "completed"),
        ("bulk", "failed"),
    ],
)
def test_phase2_status_screenshots(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    viewport,
    scope,
    case,
):
    review, citation = workflow_context()
    status = case
    if case == "mixed":
        status = "pending"
    elif case == "empty":
        status = "completed"
    finished_at = None
    if status != "pending":
        finished_at = FIXED_TIME
    if scope == "citation":
        error = ""
        if case == "failed":
            error = "L2 screening finished with abandoned results. Review the screening results before starting a new workflow."
        workflow = Phase2CitationWorkflowRequestFactory(
            citation=citation,
            requested_by=admin_user,
            status=status,
            current_process="l2",
            finished_at=finished_at,
            error=error,
        )
        url = reverse(
            "phase2_citation_workflow_status", args=[review.pk, workflow.pk]
        )
    else:
        workflow = BulkWorkflowRequestFactory(
            review=review,
            requested_by=admin_user,
            status=status,
            finished_at=finished_at,
        )
        child_statuses = [status] * 3
        if case == "empty":
            child_statuses = []
        elif case == "mixed":
            child_statuses = ["completed", "pending", "failed"]
        elif case == "failed":
            child_statuses = ["completed", "failed", "completed"]
        for index, child_status in enumerate(child_statuses, start=1):
            child = CitationFactory(
                dataset=citation.dataset,
                title=f"Study {index}: Community-based respiratory health interventions across urban and rural populations",
            )
            child_finished_at = None
            if child_status != "pending":
                child_finished_at = FIXED_TIME
            Phase2CitationWorkflowRequestFactory(
                citation=child,
                bulk_request=workflow,
                requested_by=admin_user,
                status=child_status,
                finished_at=child_finished_at,
            )
        url = reverse(
            "phase2_bulk_workflow_status", args=[review.pk, workflow.pk]
        )
    force_login(admin_user)
    capture_page(
        driver,
        live_server,
        save_screenshot,
        url,
        f"phase2-{scope}-status-{case}-{viewport}",
    )
