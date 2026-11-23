"""Capture phase 1/3 bulk pages without visual baseline comparisons."""

from django.urls import reverse

import pytest

from my_app.models import L1CriticalScreeningResult
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
