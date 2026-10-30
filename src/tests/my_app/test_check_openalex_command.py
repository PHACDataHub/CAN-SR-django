import json
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command

import pytest

from my_app.management.commands.check_openalex import DEFAULT_DOI

pytestmark = pytest.mark.backend

CACHED_URL = "https://content.openalex.org/works/W2760786931.pdf"
API_KEY = "openalex-command-test-key"


def response(body, *, status=200):
    result = MagicMock(status_code=status, is_redirect=False, headers={})
    result.iter_content.return_value = iter([body])
    result.__enter__.return_value = result
    return result


@pytest.fixture(autouse=True)
def openalex_settings(settings):
    settings.OPENALEX_API_KEY = API_KEY


@pytest.mark.parametrize("doi", [None, "https://doi.org/10.21105/joss.00026"])
def test_check_openalex_verifies_metadata_and_cached_pdf(doi, caplog):
    # Exercise the command through both HTTP clients: metadata alone cannot
    # establish that the configured key can access the cached-content API.
    metadata = {
        "id": "https://openalex.org/W2760786931",
        "has_content": {"pdf": True},
    }
    stdout = StringIO()
    args = []
    expected_doi = DEFAULT_DOI
    if doi:
        args.append(doi)
        expected_doi = "10.21105/joss.00026"
    with (
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get",
            side_effect=[
                response(json.dumps(metadata).encode()),
                response(b"%PDF-1.4\nexample\n%%EOF"),
            ],
        ) as get,
    ):
        call_command("check_openalex", *args, stdout=stdout)
    assert get.call_args_list[0].args[0].endswith(expected_doi)
    assert get.call_args_list[1].args[0] == CACHED_URL
    assert get.call_count == 2
    for call in get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert "OpenAlex check passed" in stdout.getvalue()
    assert CACHED_URL in stdout.getvalue()
    assert API_KEY not in stdout.getvalue() + caplog.text


@pytest.mark.parametrize("key", [None, "", "   "])
def test_check_openalex_requires_configured_key(settings, key):
    settings.OPENALEX_API_KEY = key
    with patch("my_app.services.doi_pdf_service.requests.get") as get:
        with pytest.raises(CommandError, match="OPENALEX_API_KEY"):
            call_command("check_openalex")
    get.assert_not_called()


def test_check_openalex_does_not_substitute_a_publisher_pdf():
    metadata = {
        "has_content": {"pdf": False},
        "best_oa_location": {
            "is_oa": True,
            "pdf_url": "https://publisher.example/paper.pdf",
        },
    }
    with (
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get",
            return_value=response(json.dumps(metadata).encode()),
        ) as get,
    ):
        with pytest.raises(CommandError, match="no cached PDF"):
            call_command("check_openalex")
    assert get.call_count == 1


@pytest.mark.parametrize(
    "replies,reason",
    [
        ([response(b"", status=401)], "401"),
        (
            [
                response(b'{"id":"W2760786931","has_content":{"pdf":true}}'),
                response(b"", status=403),
            ],
            "403",
        ),
        (
            [
                response(b'{"id":"W2760786931","has_content":{"pdf":true}}'),
                response(b"<html>Loading...</html>"),
            ],
            "did not return a PDF",
        ),
    ],
)
def test_check_openalex_reports_lookup_and_download_failures(replies, reason):
    with (
        patch("my_app.services.doi_pdf_service.validate_public_url"),
        patch(
            "my_app.services.doi_pdf_service.requests.get", side_effect=replies
        ),
    ):
        with pytest.raises(CommandError, match=reason):
            call_command("check_openalex")
