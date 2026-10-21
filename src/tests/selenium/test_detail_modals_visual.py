from datetime import datetime, timezone
from unittest.mock import patch

from django.urls import reverse

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from my_app.model_factories import (
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
)
from my_app.tables.table_framework import TableDef
from tests.detail_modal_cases import ANSWER_CASES, create_answer_case


@pytest.fixture(autouse=True)
def fixed_time(settings):
    settings.ENABLE_HTMX_POLLING = False
    with patch(
        "django.utils.timezone.now",
        return_value=datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc),
    ):
        yield


def open_citation_modal(driver, live_server, data, stage="l1"):
    prefix = TableDef.COL_SELECTION_FORM_PREFIX
    driver.get(
        live_server.url
        + reverse("citation_table", args=[data.review.pk])
        + f"?{prefix}-submitted=True&{prefix}-columns=title"
    )
    button = WebDriverWait(driver, 10).until(
        lambda browser: browser.find_element(
            By.CSS_SELECTOR,
            f'button[hx-get="{reverse("citation_detail_modal", args=[data.citation.pk])}?stage=l1"]',
        )
    )
    if stage != "l1":
        driver.execute_script(
            "arguments[0].setAttribute('hx-get', arguments[1]); htmx.process(arguments[0]);",
            button,
            reverse("citation_detail_modal", args=[data.citation.pk])
            + f"?stage={stage}",
        )
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});",
        button,
    )
    button.click()
    modal_id = f"citation-details-{data.citation.pk}"
    return WebDriverWait(driver, 10).until(
        lambda browser: visible_modal(browser, modal_id)
    )


def visible_modal(driver, modal_id):
    modal = driver.find_element(By.ID, modal_id)
    if "modal-visible" in modal.get_attribute("class"):
        return modal
    return False


def capture_modal(driver, save_screenshot, name, modal):
    path = save_screenshot(driver, snapshot_name=name)
    assert path.is_file()
    body = modal.find_element(By.CSS_SELECTOR, ".modal-body")
    driver.execute_script(
        "arguments[0].scrollTop = arguments[0].scrollHeight;", body
    )
    assert save_screenshot(driver, snapshot_name=f"{name}-bottom").is_file()


@pytest.mark.parametrize("stage", ["l1", "l2"])
@pytest.mark.parametrize("case", ANSWER_CASES)
def test_answer_detail_modal_visual(
    live_server, driver, admin_user, force_login, save_screenshot, stage, case
):
    data = create_answer_case(stage, case)
    force_login(admin_user)
    driver.set_window_size(1280, 800)
    parent = open_citation_modal(driver, live_server, data, stage)
    button = parent.find_element(
        By.CSS_SELECTOR,
        f'button[hx-get="{reverse(f"{stage}_answer_detail_modal", args=[data.citation.pk, data.question.pk])}?size=lg"]',
    )
    button.click()
    modal = WebDriverWait(driver, 10).until(
        lambda browser: visible_modal(
            browser,
            f"{stage}-answer-details-{data.citation.pk}-{data.question.pk}",
        )
    )
    assert parent.is_displayed()
    assert "modal-lg" in modal.get_attribute("class")
    assert not modal.find_elements(By.CSS_SELECTOR, "button[hx-get]")
    assert (
        modal.find_element(By.CSS_SELECTOR, ".modal-dialog").rect["width"]
        < parent.find_element(By.CSS_SELECTOR, ".modal-dialog").rect["width"]
    )
    assert data.question.question_text in modal.text
    if case == "multiple-humans":
        assert "Alex Smith" in modal.text and "Blair Chen" in modal.text
    capture_modal(
        driver, save_screenshot, f"{stage}-answer-modal-{case}", modal
    )
    if case.startswith("critical-"):
        section = modal.find_element(
            By.XPATH,
            ".//section[h2[normalize-space()='Critical agent review']]",
        )
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", section
        )
        assert save_screenshot(
            driver, snapshot_name=f"{stage}-answer-modal-{case}-critical"
        ).is_file()
    modal.find_element(By.CSS_SELECTOR, ".modal-footer button").click()
    WebDriverWait(driver, 10).until(EC.invisibility_of_element(modal))
    assert parent.is_displayed()
    WebDriverWait(driver, 10).until(
        lambda browser: browser.switch_to.active_element == button
    )
    driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    WebDriverWait(driver, 10).until(EC.invisibility_of_element(parent))


@pytest.mark.parametrize("stage", ["l1", "l2", "parameters"])
def test_citation_detail_modal_visual(
    live_server, driver, admin_user, force_login, save_screenshot, stage
):
    data = create_answer_case("l1", "multiple-humans")
    question = L2ScreeningQuestionFactory(
        review=data.review,
        question_text="Does the full text meet the eligibility criteria?",
    )
    option = L2ScreeningQuestionOptionFactory(
        question=question,
        option_text="Include",
        option_value="Full text meets all criteria",
    )
    L2ScreeningResultFactory(
        citation=data.citation,
        question=question,
        selected_option=option,
        status="completed",
        confidence=0.95,
    )
    L2HumanAnswerFactory(
        citation=data.citation, question=question, selected_option=option
    )
    parameter = ParameterFactory(
        review=data.review,
        name="Study setting",
        description="Where was the study conducted?",
    )
    ParameterExtractionResultFactory(
        citation=data.citation,
        question=parameter,
        status="completed",
        found=True,
        value="Community clinics",
        explanation="The methods describe the setting.",
    )
    force_login(admin_user)
    driver.set_window_size(1280, 800)
    modal = open_citation_modal(driver, live_server, data, stage)
    expanded = modal.find_elements(
        By.CSS_SELECTOR, "details[data-detail-stage][open]"
    )
    assert [item.get_attribute("data-detail-stage") for item in expanded] == [
        stage
    ]
    if stage == "parameters":
        expanded[0].find_element(
            By.CSS_SELECTOR, ":scope > details > summary"
        ).click()
        assert "Community clinics" in modal.text
    capture_modal(driver, save_screenshot, f"citation-modal-{stage}", modal)
    modal.find_element(
        By.CSS_SELECTOR, "details:not([data-detail-stage]) > summary"
    ).click()
    assert save_screenshot(
        driver, snapshot_name=f"citation-modal-{stage}-fields"
    ).is_file()


@pytest.mark.parametrize("stage", ["l1", "l2"])
def test_answer_to_citation_nested_modal_visual(
    live_server, driver, admin_user, force_login, save_screenshot, stage
):
    data = create_answer_case(stage, "agreement")
    force_login(admin_user)
    driver.set_window_size(1280, 800)
    prefix = TableDef.COL_SELECTION_FORM_PREFIX
    driver.get(
        live_server.url
        + reverse(f"{stage}_ai_answer_table", args=[data.review.pk])
        + f"?{prefix}-submitted=True&{prefix}-columns=question"
    )
    url = reverse(
        f"{stage}_answer_detail_modal",
        args=[data.citation.pk, data.question.pk],
    )
    trigger = WebDriverWait(driver, 10).until(
        lambda browser: browser.find_element(
            By.CSS_SELECTOR, f'button[hx-get="{url}"]'
        )
    )
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
        trigger,
    )
    trigger.click()
    parent = WebDriverWait(driver, 10).until(
        lambda browser: visible_modal(
            browser,
            f"{stage}-answer-details-{data.citation.pk}-{data.question.pk}",
        )
    )
    assert "modal-xl" in parent.get_attribute("class")
    button = parent.find_element(By.CSS_SELECTOR, "button[hx-get]")
    button.click()
    child = WebDriverWait(driver, 10).until(
        lambda browser: visible_modal(
            browser, f"citation-details-{data.citation.pk}"
        )
    )
    assert "modal-lg" in child.get_attribute("class")
    assert parent.is_displayed()
    assert (
        child.find_element(By.CSS_SELECTOR, ".modal-dialog").rect["width"]
        < parent.find_element(By.CSS_SELECTOR, ".modal-dialog").rect["width"]
    )
    assert not child.find_elements(By.CSS_SELECTOR, "button[hx-get]")
    assert child.find_element(
        By.CSS_SELECTOR, f'details[data-detail-stage="{stage}"]'
    ).get_attribute("open")
    capture_modal(
        driver, save_screenshot, f"{stage}-answer-to-citation-modal", child
    )
    child.find_element(By.CSS_SELECTOR, ".modal-footer button").click()
    WebDriverWait(driver, 10).until(
        lambda browser: browser.switch_to.active_element == button
    )
    assert parent.is_displayed()
    driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    WebDriverWait(driver, 10).until(EC.invisibility_of_element(parent))


@pytest.mark.parametrize("stage", ["l1", "l2"])
def test_citation_page_compact_answers_visual(
    live_server, driver, admin_user, force_login, save_screenshot, stage
):
    data = create_answer_case(stage, "multiple-humans")
    force_login(admin_user)
    driver.set_window_size(1280, 800)
    driver.get(
        live_server.url
        + reverse(
            f"{stage}_citation_detail", args=[data.review.pk, data.citation.pk]
        )
    )
    control = driver.find_element(
        By.ID, f"{stage}-question-panel-{data.citation.pk}-{data.question.pk}"
    )
    assert "Includes Canadian adults" not in control.text
    assert "Population outside the review scope" not in control.text
    url = reverse(
        f"{stage}_answer_detail_modal",
        args=[data.citation.pk, data.question.pk],
    )
    buttons = control.find_elements(By.CSS_SELECTOR, f'button[hx-get="{url}"]')
    assert len(buttons) == 1
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'start', behavior: 'instant'});",
        control,
    )
    assert save_screenshot(
        driver, snapshot_name=f"{stage}-citation-page-compact-answers"
    ).is_file()
    button = buttons[-1]
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
        button,
    )
    button.click()
    modal = WebDriverWait(driver, 10).until(
        lambda browser: visible_modal(
            browser,
            f"{stage}-answer-details-{data.citation.pk}-{data.question.pk}",
        )
    )
    assert "modal-xl" in modal.get_attribute("class")
    assert "Alex Smith" in modal.text and "Blair Chen" in modal.text
    capture_modal(
        driver, save_screenshot, f"{stage}-citation-page-answer-modal", modal
    )
    modal.find_element(By.CSS_SELECTOR, ".modal-footer button").click()
    WebDriverWait(driver, 10).until(
        lambda browser: browser.switch_to.active_element == button
    )
