from pathlib import Path
from unittest.mock import patch

from django.urls import reverse

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    L1ScreeningQuestionFactory,
    ParameterFactory,
    ParameterOptionFactory,
    TextExtractionResultFactory,
)


def open_form(driver, url):
    wait = WebDriverWait(driver, 10)
    trigger = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, f'[hx-get="{url}"]'))
    )
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
        trigger,
    )
    trigger.click()
    return wait.until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, ".modal-visible"))
    )


def submit_form(modal):
    modal.find_element(By.CSS_SELECTOR, "button[type=submit]").click()


def capture_error(driver, modal, save_screenshot, name, error_text):
    wait = WebDriverWait(driver, 10)
    summary = wait.until(
        EC.visibility_of_element_located((By.ID, "form-error-summary"))
    )
    assert error_text in summary.text
    assert modal.is_displayed()
    wait.until(lambda browser: browser.switch_to.active_element == summary)
    assert save_screenshot(
        driver, f"{name}-error", preserve_focus=True
    ).is_file()


def capture_success(driver, save_screenshot, name, message):
    wait = WebDriverWait(driver, 10)
    alert = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "#message-bar .alert-success")
        )
    )
    assert message in alert.text
    wait.until(
        EC.invisibility_of_element_located((By.CSS_SELECTOR, ".modal-visible"))
    )
    assert save_screenshot(driver, f"{name}-success").is_file()


@pytest.mark.parametrize(
    ("factory", "route", "field", "message"),
    [
        (
            L1ScreeningQuestionFactory,
            "edit_l1_question",
            "question_text",
            "Screening question saved.",
        ),
        (
            ParameterFactory,
            "edit_parameter_question",
            "name",
            "Parameter saved.",
        ),
    ],
    ids=["screening-question", "parameter"],
)
def test_configuration_modal_feedback(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    factory,
    route,
    field,
    message,
):
    item = factory()
    force_login(admin_user)
    driver.get(
        live_server.url + reverse("screening_criteria", args=[item.review_id])
    )
    modal = open_form(driver, reverse(route, args=[item.review_id, item.pk]))
    modal.find_element(By.NAME, field).clear()
    submit_form(modal)
    capture_error(
        driver, modal, save_screenshot, route, "This field is required."
    )

    modal.find_element(By.NAME, field).send_keys("Revised configuration")
    submit_form(modal)
    capture_success(driver, save_screenshot, route, message)
    item.refresh_from_db()
    assert getattr(item, field) == "Revised configuration"


def test_citation_answer_modal_feedback(
    live_server, driver, admin_user, force_login, save_screenshot
):
    citation = CitationFactory()
    review_id = citation.dataset.review_id
    question = ParameterFactory(review_id=review_id, option_type="select")
    option = ParameterOptionFactory(parameter=question)
    force_login(admin_user)
    driver.get(
        live_server.url
        + reverse(
            "parameter_extraction_citation_detail",
            args=[review_id, citation.pk],
        )
    )
    modal = open_form(
        driver,
        reverse(
            "parameter_question_human_answer",
            args=[review_id, citation.pk, question.pk],
        ),
    )
    modal.find_element(By.CSS_SELECTOR, '[name="found"][value="True"]').click()
    submit_form(modal)
    capture_error(
        driver,
        modal,
        save_screenshot,
        "citation-answer",
        "Select an option when the parameter was found.",
    )

    Select(modal.find_element(By.NAME, "selected_option")).select_by_value(
        str(option.pk)
    )
    submit_form(modal)
    capture_success(
        driver, save_screenshot, "citation-answer", "Answer saved."
    )
    panel = driver.find_element(
        By.ID, f"parameters-question-panel-{citation.pk}-{question.pk}"
    )
    assert option.name in panel.get_property("textContent")


def test_pdf_upload_modal_feedback(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    settings,
    tmp_path,
):
    settings.MEDIA_ROOT = tmp_path
    settings.ENABLE_HTMX_POLLING = False
    citation = CitationFactory()
    review_id = citation.dataset.review_id
    force_login(admin_user)
    driver.get(
        live_server.url
        + reverse("l2_citation_detail", args=[review_id, citation.pk])
    )
    modal = open_form(
        driver,
        reverse(
            "citation_upload_pdf_document_modal", args=[review_id, citation.pk]
        ),
    )
    submit_form(modal)
    capture_error(
        driver, modal, save_screenshot, "pdf-upload", "This field is required."
    )

    pdf = Path(__file__).parents[1] / "my_app/test_doc.pdf"
    modal.find_element(By.NAME, "document_file").send_keys(str(pdf))
    with patch(
        "my_app.views.screening.pdf.QueueProcessDocumentService.perform"
    ):
        submit_form(modal)
        capture_success(driver, save_screenshot, "pdf-upload", "PDF uploaded.")
    citation.refresh_from_db()
    assert citation.document_id is not None


def test_pdf_delete_modal_feedback(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    settings,
    tmp_path,
):
    settings.MEDIA_ROOT = tmp_path
    settings.ENABLE_HTMX_POLLING = False
    document = DocumentFactory()
    extraction = TextExtractionResultFactory(
        document=document, status="pending"
    )
    citation = CitationFactory(document=document)
    review_id = citation.dataset.review_id
    force_login(admin_user)
    driver.get(
        live_server.url
        + reverse("l2_citation_detail", args=[review_id, citation.pk])
    )
    url = reverse(
        "citation_delete_pdf", args=[review_id, citation.pk, document.pk]
    )
    driver.find_element(
        By.XPATH, f'//button[@hx-get="{url}"]/ancestor::details[1]/summary'
    ).click()
    modal = open_form(driver, url)
    submit_form(modal)
    capture_error(
        driver,
        modal,
        save_screenshot,
        "pdf-delete",
        "Wait for processing to finish before deleting the PDF.",
    )

    extraction.delete()
    submit_form(modal)
    capture_success(driver, save_screenshot, "pdf-delete", "PDF deleted.")
    citation.refresh_from_db()
    assert citation.document_id is None
