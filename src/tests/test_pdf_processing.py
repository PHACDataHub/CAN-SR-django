from django.test import override_settings

import pytest
from grobid_client.grobid_client import ServerUnavailableException

from my_app.pdf.text_extraction.processors import (
    MinimalDevPdfProcessor,
    TestPdfProcessor,
    get_pdf_processor,
)


def test_correct_client_is_used_in_tests():
    processor = get_pdf_processor()
    assert isinstance(processor, TestPdfProcessor)


@override_settings(GROBID_URL="dev", IS_RUNNING_PYTESTS=False)
def test_minimal_dev_client_used_when_grobid_url_set_to_dev():
    processor = get_pdf_processor()
    assert isinstance(processor, MinimalDevPdfProcessor)


@override_settings(GROBID_URL="", IS_RUNNING_PYTESTS=False)
def test_error_raised_when_no_grobid_url_in_non_test_mode():
    with pytest.raises(ValueError, match="GROBID_URL is not set"):
        get_pdf_processor()
