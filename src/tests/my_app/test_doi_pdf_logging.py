import json
import logging
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.storage import default_storage

import pytest
import requests

from my_app.model_factories import PdfFromDOIRequestFactory
from my_app.services.doi_pdf_service import (
    DoiPdfConfigurationError,
    DoiPdfError,
    DoiPdfService,
    UnpaywallClient,
    delete_stored_file,
    get_public_response,
    read_response,
    redact_doi_pdf_error,
)
from my_app.tasks.doi_pdf_task import process_doi_pdf_request

pytestmark = pytest.mark.backend


@pytest.fixture(autouse=True)
def logging_settings(settings, caplog):
    settings.UNPAYWALL_EMAIL = "do-not-log-me@example.org"
    settings.OPENALEX_API_KEY = None
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    caplog.set_level(logging.INFO, logger="app")


def response(body=b"", *, status=200):
    result = MagicMock(
        status_code=status,
        is_redirect=False,
        url="https://repository.example/article.pdf?token=do-not-log-me",
        headers={"Content-Type": "text/html"},
    )
    result.iter_content.return_value = iter([body])
    result.__enter__.return_value = result
    return result


def event_record(caplog, event):
    return next(
        record
        for record in caplog.records
        if record.getMessage().startswith(f"doi_pdf.{event} ")
    )


def test_task_logs_missing_configuration_with_request_identifiers(
    settings, caplog
):
    # Run the real task and service so the low-level reason and task failure
    # can be correlated even when Django's own task log only says FAILED.
    settings.UNPAYWALL_EMAIL = None
    result = PdfFromDOIRequestFactory()
    with pytest.raises(DoiPdfConfigurationError):
        process_doi_pdf_request.func(result.pk, str(result.run_id))
    event_record(caplog, "unpaywall_email_missing")
    event_record(caplog, "request_resolve_url_failed")
    message = event_record(caplog, "task_process_request_failed").getMessage()
    assert f"request_id={result.pk}" in message
    assert f"citation_id={result.citation_id}" in message
    assert str(result.run_id) in message
    assert "UNPAYWALL_EMAIL" in message
    result.refresh_from_db()
    assert result.status == result.Status.FAILED


@pytest.mark.parametrize(
    "http_status,event",
    [(403, "http_status_failed"), (200, "download_not_pdf")],
)
def test_download_failure_reasons_are_distinct_and_urls_redacted(
    caplog, http_status, event
):
    result = PdfFromDOIRequestFactory()
    url = "https://repository.example/article.pdf?token=do-not-log-me"
    with (
        patch.object(
            UnpaywallClient, "iter_pdf_urls", return_value=iter([url])
        ),
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get",
            return_value=response(
                b"<html>Access denied</html>", status=http_status
            ),
        ),
    ):
        with pytest.raises(DoiPdfError):
            process_doi_pdf_request.func(result.pk, str(result.run_id))
    event_record(caplog, event)
    assert "attempt=1" in event_record(caplog, "candidate_failed").getMessage()
    event_record(caplog, "download_attempts_exhausted")
    assert "do-not-log-me" not in caplog.text
    assert "repository.example/article.pdf" in caplog.text


@pytest.mark.parametrize(
    "error,event",
    [
        (requests.Timeout(), "http_timeout"),
        (requests.ConnectionError(), "http_connection_failed"),
        (requests.exceptions.ProxyError(), "http_proxy_failed"),
    ],
)
def test_transport_errors_have_different_events(caplog, error, event):
    with (
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get", side_effect=error
        ),
    ):
        with pytest.raises(DoiPdfError):
            get_public_response("https://repository.example/pdf")
    event_record(caplog, event)


def test_tls_failure_keeps_certificate_reason_without_query_parameters(caplog):
    error = requests.exceptions.SSLError(
        "url: /article?email=do-not-log-me CERTIFICATE_VERIFY_FAILED: "
        "unable to get local issuer certificate"
    )
    with (
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get", side_effect=error
        ),
    ):
        with pytest.raises(DoiPdfError) as captured:
            get_public_response("https://repository.example/pdf")
    message = event_record(caplog, "http_tls_failed").getMessage()
    assert "CERTIFICATE_VERIFY_FAILED" in message
    assert "unable to get local issuer certificate" in message
    assert "do-not-log-me" not in caplog.text
    assert "unable to get local issuer certificate" in str(captured.value)
    assert "do-not-log-me" not in str(captured.value)


def test_tracker_keeps_detailed_reason_without_url_credentials():
    result = PdfFromDOIRequestFactory()
    error = (
        "Connection refused at https://user:password@repository.example/pdf"
        "?token=private-token"
    )
    service = DoiPdfService(result.citation)
    service.result_id = result.pk
    service.run_id = str(result.run_id)
    service.mark_failed(error)
    result.refresh_from_db()
    assert result.status == result.Status.FAILED
    assert "Connection refused" in result.error
    assert "user:password" not in result.error
    assert "private-token" not in result.error
    assert redact_doi_pdf_error(result.error) == result.error


@pytest.mark.parametrize("failure", ["size", "time", "interrupted"])
def test_response_read_failures_have_distinct_events(caplog, failure):
    download = response(b"too large")
    if failure == "interrupted":
        download.iter_content.side_effect = (
            requests.exceptions.ChunkedEncodingError()
        )
    elapsed = [0, 121]
    max_bytes = 100
    if failure == "size":
        max_bytes = 1
    with patch(
        "my_app.services.doi_pdf_service.time.monotonic", side_effect=elapsed
    ):
        with pytest.raises(DoiPdfError):
            read_response(download, BytesIO(), max_bytes=max_bytes)
    expected = {
        "size": "response_too_large",
        "time": "response_time_limit_exceeded",
        "interrupted": "response_interrupted",
    }
    event_record(caplog, expected[failure])


@pytest.mark.parametrize(
    "body,event",
    [
        (b"not JSON", "unpaywall_json_invalid"),
        (b"[]", "unpaywall_response_invalid"),
        (b'{"oa_locations": [null]}', "unpaywall_locations_invalid"),
    ],
)
def test_api_response_failures_have_distinct_events(caplog, body, event):
    with patch(
        "my_app.services.doi_pdf_service.get_public_response",
        return_value=response(body),
    ):
        with pytest.raises(DoiPdfError):
            list(UnpaywallClient().iter_pdf_urls("10.1234/example"))
    event_record(caplog, event)


def test_missing_landing_metadata_is_distinct_from_closed_access(caplog):
    result = PdfFromDOIRequestFactory()
    api = response(
        json.dumps(
            {
                "oa_locations": [
                    {
                        "url_for_landing_page": "https://repository.example/article"
                    }
                ]
            }
        ).encode()
    )
    landing = response(b"<html>No PDF metadata</html>")
    with patch(
        "my_app.services.doi_pdf_service.get_public_response",
        side_effect=[api, landing],
    ):
        with pytest.raises(DoiPdfError):
            DoiPdfService(result.citation).perform()
    event_record(caplog, "landing_pdf_metadata_missing")
    event_record(caplog, "no_pdf_candidates")


def test_storage_failure_logs_attachment_step_and_traceback(caplog):
    result = PdfFromDOIRequestFactory()
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter(["https://repository.example/pdf"]),
        ),
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            return_value=BytesIO(b"%PDF-1.4"),
        ),
        patch.object(
            default_storage, "save", side_effect=OSError("storage offline")
        ),
    ):
        with pytest.raises(OSError, match="storage offline"):
            process_doi_pdf_request.func(result.pk, str(result.run_id))
    for event in (
        "attachment_store_file_failed",
        "request_attach_document_failed",
        "task_process_request_failed",
    ):
        record = event_record(caplog, event)
        assert record.exc_info[0] is OSError
        assert "storage offline" in record.getMessage()


def test_failure_status_save_error_does_not_hide_original_failure(caplog):
    result = PdfFromDOIRequestFactory()
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            side_effect=DoiPdfError("lookup refused"),
        ),
        patch.object(
            DoiPdfService,
            "mark_failed",
            side_effect=RuntimeError("database offline"),
        ),
    ):
        with pytest.raises(DoiPdfError, match="lookup refused"):
            DoiPdfService(result.citation).perform()
    event_record(caplog, "request_resolve_url_failed")
    assert (
        event_record(caplog, "failure_status_save_failed").exc_info[0]
        is RuntimeError
    )


@pytest.mark.parametrize(
    "reason", ["replaced_pdf", "replaced_figure", "rollback_new_pdf"]
)
def test_file_cleanup_failures_identify_which_file_is_left(caplog, reason):
    storage = MagicMock()
    storage.delete.side_effect = OSError("cleanup unavailable")
    delete_stored_file(storage, "documents/old.pdf", reason=reason)
    record = event_record(caplog, f"{reason}_cleanup_failed")
    assert "documents/old.pdf" in record.getMessage()
    assert record.exc_info[0] is OSError


@pytest.mark.parametrize("reason", ["missing", "superseded", "canceled"])
def test_skipped_task_reasons_are_logged(caplog, reason):
    result = PdfFromDOIRequestFactory()
    request_id = result.pk
    run_id = str(result.run_id)
    if reason == "missing":
        result.delete()
    elif reason == "superseded":
        run_id = str(uuid.uuid4())
    else:
        result.status = result.Status.CANCELED
        result.save()
    with patch.object(DoiPdfService, "perform") as perform:
        process_doi_pdf_request.func(request_id, run_id)
    perform.assert_not_called()
    expected = {
        "missing": "task_request_missing",
        "superseded": "task_run_superseded",
        "canceled": "task_not_pending",
    }
    event_record(caplog, expected[reason])
