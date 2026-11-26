"""Capture bulk workflow pages without visual baseline comparisons."""

from django.urls import reverse

import pytest

from my_app.model_factories import (
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterFactory,
)
from my_app.models import (
    BulkWorkflowRequest,
    L1CriticalScreeningResult,
    ScreeningActions,
)
from my_app.services.bulk_workflow import QueueBulkResultsService
from tests.bulk_workflow_cases import bulk_context
from tests.selenium.test_phase2_workflow_visual import (
    FIXED_TIME,
    capture_page,
    viewport,
)


def launch_url(phase, review):
    if phase == 1:
        return reverse("phase1_bulk_workflow", args=[review.pk])
    if phase == 2:
        return reverse("phase2_bulk_workflow", args=[review.pk])
    return reverse("phase3_bulk_workflow", args=[review.pk])


def status_url(phase, review, bulk):
    if phase == 1:
        return reverse(
            "phase1_bulk_workflow_status", args=[review.pk, bulk.pk]
        )
    return reverse("phase3_bulk_workflow_status", args=[review.pk, bulk.pk])


@pytest.mark.parametrize("phase", [1, 3])
@pytest.mark.parametrize("case", ["ready", "unconfigured"])
def test_bulk_launch_screenshots(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    viewport,
    phase,
    case,
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    review, _, definition, _ = bulk_context(phase)
    if case == "unconfigured":
        definition.soft_delete()
    force_login(admin_user)
    driver.get(live_server.url + launch_url(phase, review))
    if case == "unconfigured":
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(driver, 10).until(
            lambda browser: any(
                alert.is_displayed()
                for alert in browser.find_elements(
                    By.CSS_SELECTOR, ".alert-danger"
                )
            )
        )
    assert save_screenshot(
        driver, snapshot_name=f"phase{phase}-bulk-launch-{case}-{viewport}"
    ).is_file()


@pytest.mark.parametrize("phase", [1, 2, 3])
@pytest.mark.parametrize(
    "citation_count, question_count",
    [(51, 1), (50, 11)],
    ids=["citation-limit", "pair-limit"],
)
def test_bulk_limit_screenshots(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    viewport,
    phase,
    citation_count,
    question_count,
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    context_phase = 1 if phase == 2 else phase
    review, citations, l1_question, _ = bulk_context(
        context_phase, count=citation_count
    )
    if phase == 1:
        for _ in range(question_count - 1):
            question = L1ScreeningQuestionFactory(review=review)
            L1ScreeningQuestionOptionFactory(question=question)
    elif phase == 2:
        include = L1ScreeningQuestionOptionFactory(
            question=l1_question, screening_action=ScreeningActions.ScreenIn
        )
        for citation in citations:
            L1HumanAnswerFactory(
                citation=citation,
                question=l1_question,
                selected_option=include,
            )
        for _ in range(question_count):
            question = L2ScreeningQuestionFactory(review=review)
            L2ScreeningQuestionOptionFactory(question=question)
    else:
        ParameterFactory.create_batch(question_count - 1, review=review)

    force_login(admin_user)
    driver.get(live_server.url + launch_url(phase, review))
    wait = WebDriverWait(driver, 10)
    wait.until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
    ).click()
    alert = wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, "#message-bar .django-message.alert-danger")
        )
    )
    assert "at most 50 citations" in alert.text
    assert "at most 500" in alert.text
    assert not BulkWorkflowRequest.objects.filter(review=review).exists()
    limit = "citation-limit" if citation_count == 51 else "pair-limit"
    assert save_screenshot(
        driver, snapshot_name=f"phase{phase}-bulk-launch-{limit}-{viewport}"
    ).is_file()


@pytest.mark.parametrize("phase", [1, 3])
@pytest.mark.parametrize("status", ["pending", "completed", "failed"])
def test_bulk_status_screenshots(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    viewport,
    phase,
    status,
):
    review, citations, _, _ = bulk_context(phase)
    for index, citation in enumerate(citations, start=1):
        citation.title = f"Study {index}: Community-based respiratory health interventions across urban and rural populations"
        citation.save()
    bulk = QueueBulkResultsService(
        review, phase, requested_by=admin_user
    ).perform()
    bulk.status = status
    if status != "pending":
        bulk.finished_at = FIXED_TIME
    bulk.save()
    result_status = "pending"
    if status == "completed":
        result_status = "completed"
    elif status == "failed":
        result_status = "abandoned"
    if phase == 1:
        bulk.l1_results.update(status=result_status)
        if status == "completed":
            for result in bulk.l1_results.all():
                L1CriticalScreeningResult.objects.create(
                    initial_result=result, status="completed"
                )
    else:
        bulk.parameter_results.update(status=result_status)
    force_login(admin_user)
    capture_page(
        driver,
        live_server,
        save_screenshot,
        status_url(phase, review, bulk),
        f"phase{phase}-bulk-status-{status}-{viewport}",
    )
