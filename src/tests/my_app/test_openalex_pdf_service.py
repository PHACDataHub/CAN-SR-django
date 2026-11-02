import json
import logging
from io import BytesIO, StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command

import pytest

from my_app.model_factories import PdfFromDOIRequestFactory
from my_app.services.doi_pdf_service import (
    PDF_FROM_DOI_MAX_RETRIES,
    DoiPdfConfigurationError,
    DoiPdfError,
    DoiPdfService,
    OpenAlexClient,
    QueueDoiPdfService,
    UnpaywallClient,
    get_public_response,
    iter_doi_pdf_urls,
)

pytestmark = pytest.mark.backend

DOI = "10.3346/jkms.2017.32.11.1876"
CACHED_URL = "https://content.openalex.org/works/W2760786931.pdf"
PUBLISHER_URL = "https://publisher.example/paper.pdf"
REPOSITORY_URL = "https://repository.example/paper.pdf"
API_KEY = "private-openalex-test-key"
PDF = b"%PDF-1.4\nexample\n%%EOF"


@pytest.fixture(autouse=True)
def provider_settings(settings, caplog):
    settings.OPENALEX_API_KEY = API_KEY
    caplog.set_level(logging.INFO, logger="app")
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }


def response(body, *, status=200, url=CACHED_URL):
    result = MagicMock(
        status_code=status, is_redirect=False, url=url, headers={}
    )
    result.iter_content.return_value = iter([body])
    result.__enter__.return_value = result
    return result


def work_data():
    best = {"is_oa": True, "pdf_url": PUBLISHER_URL}
    return {
        "id": "https://openalex.org/W2760786931",
        "has_content": {"pdf": True},
        "content_urls": {"pdf": CACHED_URL},
        "best_oa_location": best,
        "locations": [
            best,
            {"is_oa": False, "pdf_url": "https://closed.example/paper.pdf"},
            {"is_oa": True, "pdf_url": REPOSITORY_URL},
        ],
    }


def test_openalex_prefers_cached_pdf_and_only_includes_open_locations():
    with patch(
        "my_app.services.doi_pdf_service.get_public_response",
        return_value=response(json.dumps(work_data()).encode()),
    ):
        urls = list(OpenAlexClient().iter_pdf_urls(DOI))
    assert urls == [CACHED_URL, PUBLISHER_URL, REPOSITORY_URL]
    assert all(API_KEY not in url for url in urls)


def test_explicit_openalex_requires_key(settings):
    settings.OPENALEX_API_KEY = None
    with patch("my_app.services.doi_pdf_service.get_public_response") as get:
        with pytest.raises(DoiPdfConfigurationError, match="OPENALEX_API_KEY"):
            list(OpenAlexClient().iter_pdf_urls(DOI))
    get.assert_not_called()


@pytest.mark.parametrize(
    "body,event",
    [
        (b"not JSON", "openalex_json_invalid"),
        (b"[]", "openalex_response_invalid"),
        (b'{"has_content": true}', "openalex_response_invalid"),
        (
            b'{"has_content": {"pdf": true}, "id": "invalid"}',
            "openalex_work_id_invalid",
        ),
        (b'{"locations": [null]}', "openalex_locations_invalid"),
    ],
)
def test_openalex_reports_malformed_responses(body, event, caplog):
    with patch(
        "my_app.services.doi_pdf_service.get_public_response",
        return_value=response(body),
    ):
        with pytest.raises(DoiPdfError):
            list(OpenAlexClient().iter_pdf_urls(DOI))
    assert f"doi_pdf.{event}" in caplog.text


@pytest.mark.parametrize(
    "target,authorized",
    [
        ("https://storage.example/paper.pdf?signature=value", False),
        ("http://content.openalex.org/works/W2760786931.pdf", False),
        ("https://content.openalex.org/works/W2760786931.pdf", True),
    ],
)
def test_openalex_key_is_not_forwarded_to_untrusted_redirects(
    target, authorized, caplog
):
    redirect = MagicMock(is_redirect=True, headers={"Location": target})
    with (
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get",
            side_effect=[redirect, response(PDF)],
        ) as get,
    ):
        get_public_response(CACHED_URL).close()
    assert (
        get.call_args_list[0].kwargs["headers"]["Authorization"]
        == f"Bearer {API_KEY}"
    )
    forwarded = get.call_args_list[1].kwargs["headers"].get("Authorization")
    if authorized:
        assert forwarded == f"Bearer {API_KEY}"
    else:
        assert forwarded is None
    assert API_KEY not in caplog.text


def test_publisher_downloads_do_not_receive_openalex_key():
    with (
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get",
            return_value=response(PDF),
        ) as get,
    ):
        get_public_response(PUBLISHER_URL).close()
    assert "Authorization" not in get.call_args.kwargs["headers"]


def test_each_provider_gets_a_separate_retry_budget():
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter(
                [PUBLISHER_URL, REPOSITORY_URL, "https://third.example/pdf"]
            ),
        ),
        patch.object(
            OpenAlexClient, "iter_pdf_urls", return_value=iter([CACHED_URL])
        ),
    ):
        urls = list(iter_doi_pdf_urls(DOI))
    assert urls == [
        PUBLISHER_URL,
        REPOSITORY_URL,
        "https://third.example/pdf",
        CACHED_URL,
    ]


def test_duplicate_urls_across_providers_do_not_use_retry_slots():
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter([PUBLISHER_URL, REPOSITORY_URL]),
        ),
        patch.object(
            OpenAlexClient,
            "iter_pdf_urls",
            return_value=iter(
                [
                    PUBLISHER_URL,
                    REPOSITORY_URL,
                    CACHED_URL,
                    "https://openalex.example/second.pdf",
                    "https://openalex.example/third.pdf",
                    "https://openalex.example/fourth.pdf",
                ]
            ),
        ),
    ):
        assert list(iter_doi_pdf_urls(DOI)) == [
            PUBLISHER_URL,
            REPOSITORY_URL,
            CACHED_URL,
            "https://openalex.example/second.pdf",
            "https://openalex.example/third.pdf",
        ]


def test_unconfigured_openalex_is_skipped(settings):
    settings.OPENALEX_API_KEY = None
    with (
        patch.object(UnpaywallClient, "iter_pdf_urls", return_value=iter([])),
        patch.object(OpenAlexClient, "iter_pdf_urls") as openalex,
    ):
        assert list(iter_doi_pdf_urls(DOI)) == []
    openalex.assert_not_called()


def test_successful_unpaywall_download_does_not_query_openalex():
    result = PdfFromDOIRequestFactory(citation__doi=DOI)
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter([PUBLISHER_URL]),
        ),
        patch.object(OpenAlexClient, "iter_pdf_urls") as openalex,
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            return_value=BytesIO(PDF),
        ),
    ):
        outcome = DoiPdfService(result.citation).perform()
    assert outcome.status == result.Status.FULFILLED
    openalex.assert_not_called()


def test_cached_pdf_fulfills_request_after_publisher_failure(
    caplog, django_capture_on_commit_callbacks, run_database_tasks
):
    # Exercise queueing, the task worker, provider fallback, and file attachment.
    # Only HTTP transport and DNS are replaced; the cached URL stays credential-free.
    result = PdfFromDOIRequestFactory(
        citation__doi=DOI, status="failed", error="Previous failure"
    )
    metadata = response(json.dumps(work_data()).encode())
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter([PUBLISHER_URL, REPOSITORY_URL]),
        ),
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get",
            side_effect=[
                response(b"Forbidden", status=403),
                response(b"Forbidden", status=403),
                metadata,
                response(PDF),
            ],
        ) as get,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            QueueDoiPdfService(result.citation).perform()
        run_database_tasks()
    result.refresh_from_db()
    outcome = result
    assert get.call_count == 4
    assert "Authorization" not in get.call_args_list[0].kwargs["headers"]
    assert (
        get.call_args_list[2].kwargs["headers"]["Authorization"]
        == f"Bearer {API_KEY}"
    )
    assert (
        get.call_args_list[3].kwargs["headers"]["Authorization"]
        == f"Bearer {API_KEY}"
    )
    assert outcome.status == result.Status.FULFILLED
    assert outcome.selected_url == CACHED_URL
    assert outcome.error == ""
    result.citation.refresh_from_db()
    assert result.citation.document.file.read() == PDF
    assert API_KEY not in outcome.selected_url
    assert API_KEY not in caplog.text


def test_openalex_still_runs_when_unpaywall_lookup_fails():
    result = PdfFromDOIRequestFactory(citation__doi=DOI)
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            side_effect=DoiPdfError("Unpaywall is unavailable"),
        ),
        patch.object(
            OpenAlexClient, "iter_pdf_urls", return_value=iter([CACHED_URL])
        ),
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            return_value=BytesIO(PDF),
        ),
    ):
        outcome = DoiPdfService(result.citation).perform()
    assert outcome.status == result.Status.FULFILLED
    assert outcome.selected_url == CACHED_URL


def test_successful_second_unpaywall_download_skips_openalex():
    result = PdfFromDOIRequestFactory(citation__doi=DOI)
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter([PUBLISHER_URL, REPOSITORY_URL]),
        ),
        patch.object(
            OpenAlexClient,
            "iter_pdf_urls",
            side_effect=DoiPdfError("OpenAlex is unavailable"),
        ) as openalex,
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            side_effect=[
                DoiPdfError("Publisher refused download"),
                BytesIO(PDF),
            ],
        ),
    ):
        outcome = DoiPdfService(result.citation).perform()
    assert outcome.status == result.Status.FULFILLED
    assert outcome.selected_url == REPOSITORY_URL
    openalex.assert_not_called()


@pytest.mark.parametrize("last_download_succeeds", [False, True])
def test_download_attempts_are_capped_per_provider(last_download_succeeds):
    # Run the service through all three failures from each provider; the sixth
    # candidate must still be allowed to fulfill the tracker and attach a PDF.
    result = PdfFromDOIRequestFactory(citation__doi=DOI)
    outcomes = [DoiPdfError("Download refused") for _ in range(6)]
    if last_download_succeeds:
        outcomes[-1] = BytesIO(PDF)
    with (
        patch.object(
            UnpaywallClient,
            "iter_pdf_urls",
            return_value=iter(
                [f"https://publisher.example/{i}.pdf" for i in range(10)]
            ),
        ),
        patch.object(
            OpenAlexClient,
            "iter_pdf_urls",
            return_value=iter(
                [
                    f"https://content.openalex.org/works/W{i}.pdf"
                    for i in range(10)
                ]
            ),
        ),
        patch(
            "my_app.services.doi_pdf_service.download_pdf",
            side_effect=outcomes,
        ) as download,
    ):
        if last_download_succeeds:
            DoiPdfService(result.citation).perform()
        else:
            with pytest.raises(DoiPdfError, match="Download refused"):
                DoiPdfService(result.citation).perform()
    assert download.call_count == 2 * PDF_FROM_DOI_MAX_RETRIES
    assert [call.args[0] for call in download.call_args_list] == [
        *[f"https://publisher.example/{i}.pdf" for i in range(3)],
        *[f"https://content.openalex.org/works/W{i}.pdf" for i in range(3)],
    ]
    result.refresh_from_db()
    if last_download_succeeds:
        assert result.status == result.Status.FULFILLED
        assert (
            result.selected_url == "https://content.openalex.org/works/W2.pdf"
        )
        result.citation.refresh_from_db()
        assert result.citation.document.file.read() == PDF
    else:
        assert result.status == result.Status.FAILED


def test_command_can_test_openalex_without_unpaywall():
    output = StringIO()
    with (
        patch.object(UnpaywallClient, "iter_pdf_urls") as unpaywall,
        patch.object(
            OpenAlexClient, "iter_pdf_urls", return_value=iter([CACHED_URL])
        ),
        patch(
            "my_app.management.commands.check_doi_pdf_resolution.download_pdf",
            return_value=BytesIO(PDF),
        ),
    ):
        call_command(
            "check_doi_pdf_resolution",
            DOI,
            provider="openalex",
            download=True,
            stdout=output,
        )
    unpaywall.assert_not_called()
    assert "PDF download check passed" in output.getvalue()
    assert CACHED_URL in output.getvalue()
    assert API_KEY not in output.getvalue()


def test_command_reports_missing_openalex_key(settings):
    settings.OPENALEX_API_KEY = None
    with pytest.raises(CommandError, match="OPENALEX_API_KEY"):
        call_command(
            "check_doi_pdf_resolution", DOI, provider="openalex", download=True
        )
