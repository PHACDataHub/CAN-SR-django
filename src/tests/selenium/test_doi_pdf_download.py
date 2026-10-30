from pathlib import Path
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from my_app.model_factories import CitationFactory, DocumentFactory
from my_app.models import Citation, PdfFromDOIRequest
from my_app.services.doi_pdf_service import QueueDoiPdfService


@pytest.mark.parametrize(
    "route", ["l2_citation_detail", "parameter_extraction_citation_detail"]
)
def test_download_states_and_pdf_viewer_refresh(
    live_server, driver, admin_user, force_login, route
):
    # Exercise real HTMX clicks and the page's existing refresh mechanism.
    # Simulate worker completion and PDF.js rendering to keep HTTP local.
    citation = CitationFactory(doi="10.1234/example")
    force_login(admin_user)
    url = reverse(route, args=[citation.dataset.review_id, citation.pk])
    control_id = f"doi-pdf-download-control-{citation.pk}"
    wait = WebDriverWait(driver, 10)
    with (
        override_settings(
            ENABLE_HTMX_POLLING=False,
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.InMemoryStorage"
                },
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            },
        ),
        patch.object(QueueDoiPdfService, "enqueue"),
        patch(
            "my_app.views.screening.l2.detail.PdfViewerAssets",
            return_value=None,
        ),
        patch(
            "my_app.views.screening.parameter_extraction.list.PdfViewerAssets",
            return_value=None,
        ),
    ):
        driver.get(live_server.url + url)
        driver.execute_script(
            """
            window.originalPdfPages = document.getElementById('citation-pdf-pages');
            window.testPdfjs = {
                GlobalWorkerOptions: {},
                getDocument: () => ({promise: Promise.resolve({
                    numPages: 1,
                    getPage: async () => ({
                        getViewport: ({scale}) => ({width: 100 * scale, height: 100 * scale}),
                        render: () => ({promise: Promise.resolve()})
                    })
                })})
            };
            """
        )
        source = (
            Path(__file__).parents[2] / "static/citation_pdf.js"
        ).read_text()
        driver.execute_script(
            source.replace(
                "import(PDFJS_URL)", "Promise.resolve(window.testPdfjs)"
            )
        )
        driver.find_element(By.CSS_SELECTOR, f"#{control_id} button").click()
        wait.until(
            lambda browser: "PDF download in progress"
            in browser.find_element(By.ID, control_id).text
        )
        result = PdfFromDOIRequest.objects.get(citation=citation)
        result.status = result.Status.FAILED
        result.save()
        driver.find_element(By.ID, "refresh-button").click()
        wait.until(
            lambda browser: "PDF download failed"
            in browser.find_element(By.ID, control_id).text
        )
        driver.find_element(By.CSS_SELECTOR, f"#{control_id} button").click()
        wait.until(
            lambda browser: "PDF download in progress"
            in browser.find_element(By.ID, control_id).text
        )
        document = DocumentFactory()
        Citation.objects.filter(pk=citation.pk).update(document=document)
        result.refresh_from_db()
        result.status = result.Status.FULFILLED
        result.save()
        driver.find_element(By.ID, "refresh-button").click()
        wait.until(
            lambda browser: browser.find_elements(
                By.CSS_SELECTOR, "#citation-pdf-pages canvas"
            )
        )
        assert driver.find_element(By.ID, control_id).text == ""
        assert (
            driver.find_element(By.ID, "citation-pdf-status").text == "1 page"
        )
        assert driver.execute_script(
            "return window.originalPdfPages === document.getElementById('citation-pdf-pages');"
        )
