from unittest.mock import patch

from django.urls import reverse

import pytest

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    PdfFromDOIRequestFactory,
)
from my_app.services.doi_pdf_service import QueueDoiPdfService

MODAL = ("id", "delete-confirmation-modal")
CONFIRM = ("css selector", "#delete-confirmation-modal button[type='submit']")
CANCEL = (
    "css selector",
    "#delete-confirmation-modal .modal-footer [data-modal-close]",
)


@pytest.mark.parametrize("stage", ["l1", "l2"])
def test_delete_question_ui(
    live_server, driver, admin_user, force_login, save_screenshot, stage
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    if stage == "l1":
        question = L1ScreeningQuestionFactory(
            question_text="Is the study relevant?"
        )
        L1ScreeningQuestionOptionFactory(question=question, option_text="Yes")
        mirror = question.sync_to_l2()
    else:
        question = L2ScreeningQuestionFactory(
            question_text="Is the study eligible?"
        )
        L2ScreeningQuestionOptionFactory(question=question, option_text="Yes")

    force_login(admin_user)
    driver.get(
        live_server.url
        + reverse("screening_criteria", args=[question.review_id])
    )
    wait = WebDriverWait(driver, 10)
    delete_url = reverse(
        f"delete_{stage}_question", args=[question.review_id, question.pk]
    )
    button = (By.CSS_SELECTOR, f"button[hx-get='{delete_url}']")
    trigger = wait.until(ec.element_to_be_clickable(button))
    assert trigger.text == "Delete question"
    assert save_screenshot(
        driver,
        f"{stage}-delete-question-button",
        element=trigger.find_element(By.XPATH, "./ancestor::li[1]"),
    ).is_file()
    trigger.click()
    wait.until(ec.visibility_of_element_located(MODAL))
    assert save_screenshot(
        driver, f"{stage}-delete-question-confirmation"
    ).is_file()

    driver.find_element(*CANCEL).click()
    wait.until(ec.invisibility_of_element_located(MODAL))
    question.refresh_from_db()
    assert question.is_active

    driver.find_element(*button).click()
    wait.until(ec.element_to_be_clickable(CONFIRM)).click()
    wait.until(ec.invisibility_of_element_located(MODAL))
    assert not driver.find_elements(*button)
    question.refresh_from_db()
    assert question.is_deleted
    if stage == "l1":
        mirror.refresh_from_db()
        assert mirror.is_deleted


@pytest.mark.parametrize(
    "stage,route",
    [
        ("l2", "l2_citation_detail"),
        ("parameters", "parameter_extraction_citation_detail"),
    ],
)
def test_delete_pdf_ui_and_download_again(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    settings,
    tmp_path,
    stage,
    route,
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    settings.MEDIA_ROOT = tmp_path
    settings.UNPAYWALL_EMAIL = "contact@example.org"
    settings.ENABLE_HTMX_POLLING = False
    citation = CitationFactory(
        title="A study with a PDF",
        document=DocumentFactory(),
        doi="10.1234/example",
    )
    request = PdfFromDOIRequestFactory(citation=citation, status="fulfilled")
    args = [citation.dataset.review_id, citation.pk]
    delete_url = reverse(
        "citation_delete_pdf", args=[*args, citation.document_id]
    )
    delete_button = (By.CSS_SELECTOR, f"button[hx-get='{delete_url}']")
    download_button = (
        By.CSS_SELECTOR,
        f"#doi-pdf-download-control-{citation.pk} button",
    )

    force_login(admin_user)
    driver.get(live_server.url + reverse(route, args=args))
    wait = WebDriverWait(driver, 10)
    driver.find_element(
        By.XPATH, "//summary[normalize-space()='More']"
    ).click()
    trigger = wait.until(ec.element_to_be_clickable(delete_button))
    assert trigger.text == "Delete PDF"
    assert save_screenshot(
        driver,
        f"{stage}-delete-pdf-button",
        element=trigger.find_element(By.XPATH, "./ancestor::section[1]"),
    ).is_file()
    trigger.click()
    wait.until(ec.visibility_of_element_located(MODAL))
    assert save_screenshot(
        driver, f"{stage}-delete-pdf-confirmation"
    ).is_file()
    wait.until(ec.element_to_be_clickable(CONFIRM)).click()

    download = wait.until(ec.element_to_be_clickable(download_button))
    assert download.text == "Auto-download PDF"
    assert not driver.find_elements(*delete_button)
    assert (
        "Upload a PDF"
        in driver.find_element(By.ID, "citation-pdf-status").text
    )
    assert save_screenshot(
        driver,
        f"{stage}-pdf-deleted",
        element=download.find_element(By.XPATH, "./ancestor::section[1]"),
    ).is_file()
    citation.refresh_from_db()
    assert citation.document_id is None

    with patch.object(QueueDoiPdfService, "enqueue"):
        download.click()
        wait.until(
            lambda browser: "PDF download in progress"
            in browser.find_element(
                By.ID, f"doi-pdf-download-control-{citation.pk}"
            ).text
        )
    request.refresh_from_db()
    assert request.status == request.Status.PENDING
