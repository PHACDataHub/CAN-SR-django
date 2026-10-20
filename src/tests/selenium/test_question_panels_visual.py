from datetime import datetime, timezone
from unittest.mock import patch

from django.urls import reverse

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from my_app.models import (
    L1ScreeningResult,
    L2ScreeningResult,
    ParameterExtractionResult,
)
from tests.detail_modal_cases import panel_case

PAGE_ROUTES = {
    "l1": "l1_citation_detail",
    "l2": "l2_citation_detail",
    "parameters": "parameter_extraction_citation_detail",
}


@pytest.fixture(autouse=True)
def fixed_time(settings, driver, live_server):
    settings.ENABLE_HTMX_POLLING = False
    with patch(
        "django.utils.timezone.now",
        return_value=datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc),
    ):
        yield
        driver.get(live_server.url + "/health/live")


def open_page(driver, live_server, data, stage):
    driver.set_window_size(1280, 800)
    driver.get(
        live_server.url
        + reverse(PAGE_ROUTES[stage], args=[data.review.pk, data.citation.pk])
    )
    return driver.find_element(
        By.ID, f"{stage}-question-panel-{data.citation.pk}-{data.question.pk}"
    )


@pytest.mark.parametrize("stage", ["l1", "l2", "parameters"])
@pytest.mark.parametrize(
    "case",
    ["neither", "human-only", "agreement", "disagreement", "pending", "error"],
)
def test_question_panel_visual(
    live_server, driver, admin_user, force_login, save_screenshot, stage, case
):
    data = panel_case(stage, case)
    force_login(admin_user)
    panel = open_page(driver, live_server, data, stage)
    details = panel.find_element(By.CSS_SELECTOR, ":scope > details")
    assert bool(details.get_attribute("open")) == (
        case in {"disagreement", "error"}
    )
    assert (
        len(
            panel.find_elements(By.CSS_SELECTOR, 'button[hx-get*="/details/"]')
        )
        == 1
    )
    if case == "human-only":
        assert panel.find_element(By.CSS_SELECTOR, ".badge").text == "Human"
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'start', behavior: 'instant'});",
        panel,
    )
    snapshot_element = panel
    if panel.rect["height"] > 720:
        snapshot_element = panel.find_element(By.CSS_SELECTOR, ":scope > dl")
    assert save_screenshot(
        driver,
        snapshot_name=f"{stage}-question-panel-{case}",
        element=snapshot_element,
    ).is_file()
    if case in {"disagreement", "error"}:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'end', behavior: 'instant'});",
            details,
        )
        snapshot_element = None
        if details.rect["height"] <= 720:
            snapshot_element = details
        assert save_screenshot(
            driver,
            snapshot_name=f"{stage}-question-panel-{case}-more",
            element=snapshot_element,
        ).is_file()
    else:
        details.find_element(By.CSS_SELECTOR, "summary").click()
    button = panel.find_element(By.CSS_SELECTOR, 'button[hx-get*="/details/"]')
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
        button,
    )
    button.click()
    modal = WebDriverWait(driver, 10).until(
        lambda browser: browser.find_element(
            By.CSS_SELECTOR, ".citation-detail-modal.modal-visible"
        )
    )
    assert data.question.title in modal.text
    modal.find_element(By.CSS_SELECTOR, ".modal-footer button").click()
    WebDriverWait(driver, 10).until(
        lambda browser: browser.switch_to.active_element == button
    )


@pytest.mark.parametrize("stage", ["l1", "l2", "parameters"])
@pytest.mark.parametrize("with_ai", [False, True])
def test_enter_human_answer_before_ai(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    stage,
    with_ai,
):
    case = "neither"
    if with_ai:
        case = "ai-only"
    data = panel_case(stage, case)
    suffix = "before-ai"
    if with_ai:
        suffix = "ai-disagreement"
    force_login(admin_user)
    panel = open_page(driver, live_server, data, stage)
    button = panel.find_element(
        By.CSS_SELECTOR, 'button[hx-get*="/human-answer/"]'
    )
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
        button,
    )
    button.click()
    modal = WebDriverWait(driver, 10).until(
        lambda browser: browser.find_element(
            By.CSS_SELECTOR, "[data-modal].modal-visible"
        )
    )
    if stage == "parameters":
        modal.find_element(
            By.CSS_SELECTOR, 'input[name="found"][value="True"]'
        ).click()
        value = "Community clinics"
        if with_ai:
            value = "Schools"
        modal.find_element(By.NAME, "value").send_keys(value)
    else:
        option = data.question.options.first()
        if with_ai:
            option = data.question.options.last()
        Select(modal.find_element(By.NAME, "selected_option")).select_by_value(
            str(option.pk)
        )
    modal.find_element(By.NAME, "notes").send_keys("Reviewed without AI")
    assert save_screenshot(
        driver, snapshot_name=f"{stage}-manual-answer-form-{suffix}"
    ).is_file()
    modal.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    panel_id = f"{stage}-question-panel-{data.citation.pk}-{data.question.pk}"
    WebDriverWait(driver, 10).until(
        lambda browser: browser.find_element(By.ID, panel_id)
        .find_element(By.CSS_SELECTOR, ".badge")
        .text
        == "Human"
    )
    WebDriverWait(driver, 10).until(
        lambda browser: not browser.find_elements(
            By.CSS_SELECTOR, "[data-modal].modal-visible"
        )
    )
    panel = driver.find_element(By.ID, panel_id)
    assert "Edit your answer" in panel.text
    result_model = {
        "l1": L1ScreeningResult,
        "l2": L2ScreeningResult,
        "parameters": ParameterExtractionResult,
    }[stage]
    assert (
        result_model.objects.filter(citation=data.citation).exists() == with_ai
    )
    assert (
        bool(
            panel.find_element(
                By.CSS_SELECTOR, ":scope > details"
            ).get_attribute("open")
        )
        == with_ai
    )
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
        panel,
    )
    assert save_screenshot(
        driver, snapshot_name=f"{stage}-manual-answer-saved-{suffix}"
    ).is_file()
