import uuid
from contextlib import contextmanager
from io import BytesIO, StringIO
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import CommandError, call_command
from django.test import override_settings

import pytest

from proj.util import MissingPreconditionError

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    FigureExtractionResultFactory,
    L1HumanAnswerFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterHumanAnswerFactory,
    PdfFromDOIRequestFactory,
    TextExtractionResultFactory,
    UserFactory,
)
from my_app.models import (
    Citation,
    Document,
    DocumentFigure,
    DocumentTable,
    L1CriticalScreeningResult,
    PdfFromDOIRequest,
)
from my_app.services.doi_pdf_service import (
    PDF_FROM_DOI_MAX_RETRIES,
    DoiPdfConfigurationError,
    DoiPdfError,
    DoiPdfService,
    PdfFromDOIAlreadyPendingError,
    PendingDocumentProcessingError,
    QueueDoiPdfService,
    UnpaywallClient,
    download_pdf,
    get_public_response,
    normalize_doi,
)

pytestmark = pytest.mark.backend

DOI = "10.1016/j.jcv.2006.04.001"
PDF_URL = "https://repository.example/article.pdf"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture(autouse=True)
def doi_settings(settings):
    settings.UNPAYWALL_EMAIL = "researcher@example.org"
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }


def pending_request(**citation_kwargs):
    citation = CitationFactory(doi=DOI, **citation_kwargs)
    result = PdfFromDOIRequestFactory(citation=citation)
    return citation, result


@contextmanager
def fake_download(url):
    yield BytesIO(PDF)


@pytest.fixture
def resolved_pdf():
    # Replace only external resolution/downloads; request updates, document
    # storage, transactions, and downstream cleanup still run normally.
    with (
        patch.object(
            UnpaywallClient, "iter_pdf_urls", return_value=iter([PDF_URL])
        ) as resolve,
        patch("my_app.services.doi_pdf_service.download_pdf", fake_download),
    ):
        yield resolve


@pytest.mark.parametrize(
    "value",
    [
        DOI,
        f"https://dx.doi.org/{DOI}",
        f"https://doi.org/{DOI}",
        f" DOI:{DOI.upper()} ",
    ],
)
def test_normalize_doi(value):
    assert normalize_doi(value) == DOI


@pytest.mark.parametrize(
    "value", ["", "not-a-doi", "10.1234/", f"https://example.org/{DOI}"]
)
def test_normalize_doi_rejects_invalid_input(value):
    with pytest.raises(DoiPdfError):
        normalize_doi(value)


def mock_response(content, **kwargs):
    response = MagicMock(
        status_code=200, is_redirect=False, headers={}, **kwargs
    )
    response.iter_content.return_value = iter([content])
    response.__enter__.return_value = response
    return response


def test_unpaywall_ranks_deduplicates_and_resolves_landing_pages():
    # The two HTTP responses represent the API lookup and an HTML landing page.
    # Exercise ranking and deduplication before falling back to HTML metadata.
    import json

    best = {"url_for_pdf": PDF_URL, "host_type": "repository"}
    publisher = {
        "url_for_pdf": "https://publisher.example/published.pdf",
        "host_type": "publisher",
        "version": "publishedVersion",
    }
    repository = {
        "url_for_pdf": "https://repository.example/accepted.pdf",
        "host_type": "repository",
        "version": "acceptedVersion",
    }
    page = "https://repository.example/article"
    metadata = mock_response(
        b'<meta name="citation_pdf_url" content="/download.pdf">', url=page
    )
    response = mock_response(
        json.dumps(
            {
                "best_oa_location": best,
                "oa_locations": [
                    repository,
                    publisher,
                    best,
                    {"url_for_landing_page": page},
                ],
                "oa_locations_embargoed": [
                    {"url_for_pdf": "https://embargoed.example/pdf"}
                ],
            }
        ).encode()
    )
    with patch(
        "my_app.services.doi_pdf_service.get_public_response",
        side_effect=[response, metadata],
    ) as get:
        urls = list(UnpaywallClient().iter_pdf_urls(DOI))
    assert urls == [
        PDF_URL,
        publisher["url_for_pdf"],
        repository["url_for_pdf"],
        "https://repository.example/download.pdf",
    ]
    assert get.call_args_list[0].kwargs["params"] == {
        "email": "researcher@example.org"
    }


@override_settings(UNPAYWALL_EMAIL=None)
def test_unpaywall_requires_contact_email():
    with pytest.raises(DoiPdfConfigurationError, match="UNPAYWALL_EMAIL"):
        list(UnpaywallClient().iter_pdf_urls(DOI))


def test_download_rejects_html_and_oversized_responses():
    with patch(
        "my_app.services.doi_pdf_service.get_public_response",
        return_value=mock_response(b"<html>Access denied</html>"),
    ):
        with pytest.raises(DoiPdfError, match="did not return a PDF"):
            with download_pdf(PDF_URL):
                pytest.fail("HTML must not be accepted")
    with (
        patch(
            "my_app.services.doi_pdf_service.get_public_response",
            return_value=mock_response(PDF),
        ),
        patch("my_app.services.doi_pdf_service.PDF_FROM_DOI_MAX_BYTES", 5),
    ):
        with pytest.raises(DoiPdfError, match="size limit"):
            with download_pdf(PDF_URL):
                pytest.fail("Oversized files must not be accepted")


def test_redirects_cannot_reach_private_addresses():
    # A public PDF host redirects to localhost. Mock DNS for both destinations
    # to verify the redirect is rejected before a second HTTP request is sent.
    redirect = MagicMock(
        is_redirect=True, headers={"Location": "http://127.0.0.1/private.pdf"}
    )
    public = [(2, 1, 6, "", ("93.184.216.34", 443))]
    private = [(2, 1, 6, "", ("127.0.0.1", 80))]
    with (
        patch(
            "my_app.services.doi_pdf_service.socket.getaddrinfo",
            side_effect=[public, private],
        ),
        patch(
            "my_app.services.doi_pdf_service.requests.get",
            return_value=redirect,
        ) as get,
    ):
        with pytest.raises(DoiPdfError, match="private networks"):
            get_public_response(PDF_URL)
    get.assert_called_once()
    redirect.close.assert_called_once()


def test_queue_creates_resets_and_rejects_pending_requests(
    django_capture_on_commit_callbacks,
):
    # Follow one citation through initial queueing, duplicate rejection, and
    # retry after failure. Execute commit callbacks to observe task dispatch.
    citation = CitationFactory(doi=f"https://dx.doi.org/{DOI}")
    user = UserFactory()
    with patch.object(QueueDoiPdfService, "enqueue") as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            result = QueueDoiPdfService(
                citation, requesting_user=user
            ).perform()
        enqueue.assert_called_once_with(result.pk, str(result.run_id))
        assert result.requesting_user == user
        assert result.citation_id == citation.pk
        assert result.selected_url is None
        with pytest.raises(PdfFromDOIAlreadyPendingError):
            QueueDoiPdfService(citation).perform()
        first_run_id = result.run_id
        result.status = result.Status.FAILED
        result.error = "Old failure"
        result.selected_url = PDF_URL
        result.save()
        previous_update = result.updated_dt
        with django_capture_on_commit_callbacks(execute=True):
            reset = QueueDoiPdfService(citation).perform()
        assert reset.pk == result.pk
        assert reset.run_id != first_run_id
        assert reset.requesting_user is None
        assert reset.status == reset.Status.PENDING
        assert reset.selected_url is None
        assert reset.error == ""
        assert reset.updated_dt >= previous_update
        assert enqueue.call_count == 2


def test_queue_rolls_back_without_dispatching(
    django_capture_on_commit_callbacks,
):
    # The caller's outer transaction fails after the queue service returns.
    # Both the tracking record and its deferred task dispatch must disappear.
    from django.db import transaction

    citation = CitationFactory(doi=DOI)
    with patch.object(QueueDoiPdfService, "enqueue") as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    QueueDoiPdfService(citation).perform()
                    raise RuntimeError("rollback")
        assert not PdfFromDOIRequest.objects.filter(citation=citation).exists()
        enqueue.assert_not_called()


def test_dispatch_failure_marks_request_failed():
    _, result = pending_request()
    with patch("my_app.tasks.doi_pdf_task.process_doi_pdf_request") as task:
        task.enqueue.side_effect = RuntimeError("queue unavailable")
        with pytest.raises(RuntimeError):
            QueueDoiPdfService.enqueue(result.pk, str(result.run_id))
    result.refresh_from_db()
    assert result.status == result.Status.FAILED
    assert "queue unavailable" in result.error


def test_fulfills_request_and_attaches_new_document(resolved_pdf):
    citation, result = pending_request()
    outcome = DoiPdfService(citation).perform()
    resolved_pdf.assert_called_once_with(citation.doi)
    citation.refresh_from_db()
    assert outcome.status == result.Status.FULFILLED
    assert outcome.selected_url == PDF_URL
    assert citation.document.file.read() == PDF


def test_replacement_clears_ai_and_extraction_but_preserves_humans(
    resolved_pdf, django_capture_on_commit_callbacks
):
    # Populate each downstream result type to check replacement across models.
    # Processing is completed so replacement is allowed; commit callbacks delete
    # the old PDF and figure files after their database records are updated.
    document = DocumentFactory()
    old_name = document.file.name
    citation, result = pending_request(document=document)
    text = TextExtractionResultFactory(document=document, status="completed")
    figures = FigureExtractionResultFactory(
        document=document, status="completed"
    )
    figure = DocumentFigure.objects.create(document=document, index=1)
    figure.file.save("old-figure.png", ContentFile(b"old image"))
    figure_name = figure.file.name
    table = DocumentTable.objects.create(
        document=document, index=1, table_markdown="old"
    )
    ai = [
        factory(citation=citation, status="completed")
        for factory in (
            L1ScreeningResultFactory,
            L2ScreeningResultFactory,
            ParameterExtractionResultFactory,
        )
    ]
    critical = L1CriticalScreeningResult.objects.create(
        initial_result=ai[0], status="completed"
    )
    human = [
        factory(citation=citation)
        for factory in (
            L1HumanAnswerFactory,
            L2HumanAnswerFactory,
            ParameterHumanAnswerFactory,
        )
    ]
    with django_capture_on_commit_callbacks(execute=True):
        DoiPdfService(citation).perform()
    citation.refresh_from_db()
    assert citation.document_id == document.pk
    assert citation.document.file.read() == PDF
    assert not default_storage.exists(old_name)
    assert not default_storage.exists(figure_name)
    for item in [text, figures, figure, table, critical, *ai]:
        assert not type(item).objects.filter(pk=item.pk).exists()
    for item in human:
        assert type(item).objects.filter(pk=item.pk).exists()
    result.refresh_from_db()
    assert result.status == result.Status.FULFILLED


def test_failed_download_keeps_existing_document_and_tries_next():
    document = DocumentFactory()
    citation, result = pending_request(document=document)
    urls = ["https://publisher.example/pdf", PDF_URL]

    @contextmanager
    def download(url):
        if url == urls[0]:
            raise DoiPdfError("Publisher refused download")
        yield BytesIO(PDF)

    with (
        patch.object(
            UnpaywallClient, "iter_pdf_urls", return_value=iter(urls)
        ),
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            side_effect=download,
        ) as get,
    ):
        outcome = DoiPdfService(citation).perform()
    assert get.call_count == 2
    assert outcome.status == result.Status.FULFILLED
    assert outcome.selected_url == PDF_URL


def test_download_failures_are_capped_and_leave_old_content():
    document = DocumentFactory()
    old_name = document.file.name
    citation, result = pending_request(document=document)
    text = TextExtractionResultFactory(document=document, status="completed")
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter(
                [f"https://repository.example/{i}.pdf" for i in range(10)]
            ),
        ),
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            side_effect=DoiPdfError("Blocked"),
        ) as get,
    ):
        with pytest.raises(DoiPdfError, match="Blocked"):
            DoiPdfService(citation).perform()
    assert get.call_count == PDF_FROM_DOI_MAX_RETRIES
    document.refresh_from_db()
    assert document.file.name == old_name
    assert default_storage.exists(old_name)
    text.refresh_from_db()
    result.refresh_from_db()
    assert result.status == result.Status.FAILED


def test_database_failure_rolls_back_file_and_downstream_changes(resolved_pdf):
    # Fail after real downstream deletion, once the new file is already stored.
    # Database rollback must restore old results, while separate storage cleanup
    # removes the new file and leaves the old PDF intact.
    document = DocumentFactory()
    old_name = document.file.name
    citation, result = pending_request(document=document)
    text = TextExtractionResultFactory(document=document, status="completed")
    clear = DoiPdfService.clear_downstream_results

    def clear_then_fail(citation, document):
        clear(citation, document)
        raise RuntimeError("database failure")

    with patch.object(
        DoiPdfService, "clear_downstream_results", side_effect=clear_then_fail
    ):
        with pytest.raises(RuntimeError, match="database failure"):
            DoiPdfService(citation).perform()
    document.refresh_from_db()
    assert document.file.name == old_name
    text.refresh_from_db()
    assert default_storage.listdir("documents")[1] == [old_name.split("/")[-1]]
    result.refresh_from_db()
    assert result.status == result.Status.FAILED


def test_shared_documents_are_not_overwritten(resolved_pdf):
    document = DocumentFactory()
    old_name = document.file.name
    citation, result = pending_request(document=document)
    CitationFactory(document=document)
    with pytest.raises(MissingPreconditionError, match="shared"):
        DoiPdfService(citation).perform()
    document.refresh_from_db()
    assert document.file.name == old_name
    result.refresh_from_db()
    assert result.status == result.Status.FAILED


@pytest.mark.parametrize(
    "factory",
    [
        TextExtractionResultFactory,
        FigureExtractionResultFactory,
        L1ScreeningResultFactory,
        L2ScreeningResultFactory,
        ParameterExtractionResultFactory,
    ],
)
def test_pending_processing_prevents_replacement(factory, resolved_pdf):
    document = DocumentFactory()
    old_name = document.file.name
    citation, result = pending_request(document=document)
    if factory in (TextExtractionResultFactory, FigureExtractionResultFactory):
        processing = factory(document=document)
    else:
        processing = factory(citation=citation)
    with pytest.raises(PendingDocumentProcessingError, match="pending"):
        DoiPdfService(citation).perform()
    document.refresh_from_db()
    assert document.file.name == old_name
    processing.refresh_from_db()
    result.refresh_from_db()
    assert result.status == result.Status.FAILED


@pytest.mark.parametrize("change", ["cancel", "new_run", "document"])
def test_stale_downloads_cannot_overwrite_newer_work(change):
    # Change database state inside the fake download to simulate another action
    # while the worker is waiting on HTTP. Its final save must respect that change.
    citation, result = pending_request()
    initial_run_id = result.run_id

    @contextmanager
    def download(url):
        if change == "cancel":
            result.status = result.Status.CANCELED
            result.save()
        elif change == "new_run":
            result.run_id = uuid.uuid4()
            result.selected_url = None
            result.save()
        else:
            Citation.objects.filter(pk=citation.pk).update(
                document=DocumentFactory()
            )
        yield BytesIO(PDF)

    with (
        patch.object(
            UnpaywallClient, "iter_pdf_urls", return_value=iter([PDF_URL])
        ),
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            side_effect=download,
        ),
    ):
        outcome = DoiPdfService(citation).perform()
    if change == "new_run":
        assert outcome.run_id != initial_run_id
        assert outcome.status == result.Status.PENDING
        assert outcome.selected_url is None
    else:
        assert outcome.status == result.Status.CANCELED
    assert Document.objects.count() == int(change == "document")


def test_database_task_runs_full_flow(
    resolved_pdf, django_capture_on_commit_callbacks, run_database_tasks
):
    # Run the real queue service, commit callback, database task backend, worker,
    # and fulfillment service together. Only external HTTP work is replaced.
    citation = CitationFactory(doi=DOI)
    with django_capture_on_commit_callbacks(execute=True):
        result = QueueDoiPdfService(citation).perform()
    run_database_tasks()
    result.refresh_from_db()
    assert result.status == result.Status.FULFILLED


@pytest.mark.parametrize("argument", [None, f"https://dx.doi.org/{DOI}"])
def test_check_command_resolves_default_and_optional_doi(argument):
    output = StringIO()
    arguments = []
    if argument:
        arguments.append(argument)
    with patch.object(
        UnpaywallClient, "iter_pdf_urls", return_value=iter([PDF_URL])
    ) as resolve:
        call_command("check_doi_pdf_resolution", *arguments, stdout=output)
    resolve.assert_called_once_with(DOI)
    assert "check passed" in output.getvalue()
    assert PDF_URL in output.getvalue()


def test_check_command_reports_no_pdf():
    with patch.object(UnpaywallClient, "iter_pdf_urls", return_value=iter([])):
        with pytest.raises(CommandError, match="No open-access PDF URL"):
            call_command("check_doi_pdf_resolution")
