from contextlib import contextmanager
from io import BytesIO
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    PdfFromDOIRequestFactory,
    ReviewFactory,
)
from my_app.models import PdfFromDOIRequest
from my_app.services.doi_pdf_service import QueueDoiPdfService, UnpaywallClient
from tests.utils_for_testing import soup_from_str

pytestmark = pytest.mark.view

DETAIL_ROUTES = ["l2_citation_detail", "parameter_extraction_citation_detail"]


def download_url(citation):
    return reverse(
        "citation_download_pdf_from_doi",
        args=[citation.dataset.review_id, citation.pk],
    )


@pytest.mark.parametrize("route", DETAIL_ROUTES)
@pytest.mark.parametrize(
    "status", [None, "pending", "failed", "canceled", "fulfilled"]
)
def test_download_control_states_share_page_polling(
    vanilla_client, route, status
):
    citation = CitationFactory(doi="10.1234/example")
    reason = "The server returned HTTP 403. <script>not HTML</script>"
    if status is not None:
        PdfFromDOIRequestFactory(
            citation=citation, status=status, error=reason
        )
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(route, args=[citation.dataset.review_id, citation.pk])
        )
    assert response.status_code == 200
    soup = soup_from_str(response.content)
    owner = soup.find(id="workflow-detail-component")
    control = owner.find(id=f"doi-pdf-download-control-{citation.pk}")
    assert len(soup.select(".workflow-refresh")) == 1
    assert "every 5s" in owner["hx-trigger"]
    assert not control.has_attr("hx-get")
    if status in ("failed", "canceled"):
        assert reason in control.text
        assert "Reason" in control.text
        assert control.find("script") is None
    else:
        assert reason not in control.text
    if status == "pending":
        assert "PDF download in progress" in control.text
        assert control.find("button") is None
    else:
        button = control.find("button")
        assert button.text == "Auto-download PDF"
        assert button["hx-post"] == download_url(citation)
        assert not button.has_attr("disabled")
        if status == "failed":
            assert "PDF download failed" in control.text
        elif status == "canceled":
            assert "PDF download was canceled" in control.text


@pytest.mark.parametrize("route", DETAIL_ROUTES)
def test_download_control_disabled_without_doi(vanilla_client, route):
    citation = CitationFactory(doi="")
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(route, args=[citation.dataset.review_id, citation.pk])
        )
    control = soup_from_str(response.content).find(
        id=f"doi-pdf-download-control-{citation.pk}"
    )
    assert control.find("button").has_attr("disabled")
    assert "A DOI is required" in control.text


@pytest.mark.parametrize("route", DETAIL_ROUTES)
def test_download_control_hidden_when_pdf_exists(vanilla_client, route):
    citation = CitationFactory(
        doi="10.1234/example", document=DocumentFactory()
    )
    PdfFromDOIRequestFactory(citation=citation, status="failed")
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(route, args=[citation.dataset.review_id, citation.pk])
        )
    control = soup_from_str(response.content).find(
        id=f"doi-pdf-download-control-{citation.pk}"
    )
    assert not control.text
    assert control.find("button") is None


@pytest.mark.parametrize("status", [None, "failed", "canceled"])
@pytest.mark.parametrize(
    "doi", ["10.1234/example", "dx.doi.org/10.1234/example"]
)
def test_post_queues_and_renders_pending(
    vanilla_client,
    vanilla_user,
    django_capture_on_commit_callbacks,
    status,
    doi,
):
    citation = CitationFactory(doi=doi)
    if status:
        PdfFromDOIRequestFactory(
            citation=citation, status=status, error="Old download failure"
        )
    with (
        patch_rules(can_access_review=True),
        patch.object(QueueDoiPdfService, "enqueue") as enqueue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = vanilla_client.post(
            download_url(citation), headers={"HX-Request": "true"}
        )
    assert response.status_code == 200
    assert "PDF download in progress" in response.content.decode()
    assert "Old download failure" not in response.content.decode()
    result = PdfFromDOIRequest.objects.get(citation=citation)
    assert result.status == result.Status.PENDING
    assert result.requesting_user == vanilla_user
    assert result.error == ""
    enqueue.assert_called_once_with(result.pk, str(result.run_id))


def test_duplicate_post_keeps_current_request(vanilla_client):
    result = PdfFromDOIRequestFactory()
    run_id = result.run_id
    with (
        patch_rules(can_access_review=True),
        patch.object(QueueDoiPdfService, "enqueue") as enqueue,
    ):
        response = vanilla_client.post(download_url(result.citation))
    assert response.status_code == 200
    assert "PDF download in progress" in response.content.decode()
    result.refresh_from_db()
    assert result.run_id == run_id
    enqueue.assert_not_called()


def test_post_cannot_replace_existing_pdf(vanilla_client):
    citation = CitationFactory(
        doi="10.1234/example", document=DocumentFactory()
    )
    with (
        patch_rules(can_access_review=True),
        patch.object(QueueDoiPdfService, "perform") as perform,
    ):
        response = vanilla_client.post(download_url(citation))
    assert response.status_code == 200
    assert not PdfFromDOIRequest.objects.filter(citation=citation).exists()
    perform.assert_not_called()


@pytest.mark.parametrize("doi", ["", "not-a-doi", "https://[invalid"])
def test_post_reports_invalid_doi(vanilla_client, doi):
    citation = CitationFactory(doi=doi)
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(download_url(citation))
    assert response.status_code == 200
    assert "A valid DOI is required" in response.content.decode()
    assert not PdfFromDOIRequest.objects.filter(citation=citation).exists()


def test_post_requires_review_access_and_scopes_citation(vanilla_client):
    citation = CitationFactory(doi="10.1234/example")
    with patch_rules(can_access_review=False):
        assert vanilla_client.post(download_url(citation)).status_code == 403
    other_review = ReviewFactory()
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse(
                "citation_download_pdf_from_doi",
                args=[other_review.pk, citation.pk],
            )
        )
        get_response = vanilla_client.get(download_url(citation))
    assert response.status_code == 404
    assert get_response.status_code == 405
    assert not PdfFromDOIRequest.objects.exists()


@pytest.mark.parametrize("route", DETAIL_ROUTES)
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
def test_download_completion_updates_page_and_viewer_data(
    vanilla_client,
    route,
    django_capture_on_commit_callbacks,
    run_database_tasks,
):
    # Exercise the POST, real task worker, storage, and existing page refresh.
    # Only the external DOI lookup and PDF transport are replaced.
    citation = CitationFactory(doi="10.1234/example")

    @contextmanager
    def download(url):
        yield BytesIO(b"%PDF-1.4\nexample PDF\n%%EOF")

    detail_url = reverse(route, args=[citation.dataset.review_id, citation.pk])
    with (
        patch_rules(can_access_review=True),
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter(["https://repository.example/article.pdf"]),
        ),
        patch("my_app.services.doi_pdf_service.download_pdf", download),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = vanilla_client.post(download_url(citation))
        assert "PDF download in progress" in response.content.decode()
        run_database_tasks()
        response = vanilla_client.get(
            detail_url,
            headers={
                "HX-Request": "true",
                "HX-Target": "workflow-detail-component",
            },
        )
    assert response.status_code == 200
    owner = soup_from_str(response.content).find(
        id="workflow-detail-component"
    )
    control = owner.find(id=f"doi-pdf-download-control-{citation.pk}")
    assert not control.text
    template = owner.find(
        "template", attrs={"data-citation-id": str(citation.pk)}
    )
    assert template["data-pdf-url"] == reverse(
        "citation_download_pdf_document",
        args=[citation.dataset.review_id, citation.pk],
    )
    citation.refresh_from_db()
    assert not hasattr(citation.document, "text_extraction_result")
    assert not hasattr(citation.document, "figure_extraction_result")
