from io import BytesIO, StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import override_settings

from my_app.management.commands.check_azure_docint import (
    build_docint_smoke_test_pdf,
)
from my_app.pdf.figure_extraction.azure import (
    ExtractedFigure,
    ExtractedTable,
    FigureExtractionResultData,
    FigureImage,
)
from my_app.pdf.figure_extraction.client import AzureDocIntExtractionClient
from my_app.pdf.types import PdfCoordinate


class FakeAzureDocIntExtractionClient(AzureDocIntExtractionClient):
    def __init__(self, result):
        self.result = result

    def extract_figures(self, file):
        assert file.read().startswith(b"%PDF-1.4")
        return self.result


def build_result():
    coordinates = [PdfCoordinate(page=1, x=72, y=102, width=120, height=90)]
    return FigureExtractionResultData(
        figures=[
            ExtractedFigure(
                index=1,
                provider_id="1.1",
                caption="Dummy image",
                coordinates=coordinates,
                image=FigureImage(png_bytes=b"png bytes"),
            )
        ],
        tables=[
            ExtractedTable(
                index=1,
                markdown="| Outcome | Group A |\n| --- | --- |\n| Cases | 12 |",
                coordinates=coordinates,
            )
        ],
    )


@override_settings(FIGURE_EXTRACTION_MODE="")
def test_check_azure_docint_rejects_non_azure_mode():
    try:
        call_command("check_azure_docint", verbosity=0)
    except CommandError as exc:
        assert "FIGURE_EXTRACTION_MODE='azure_doc_int'" in str(exc)
    else:
        raise AssertionError("Expected CommandError")


@override_settings(
    FIGURE_EXTRACTION_MODE="azure_doc_int",
    AZURE_DOC_INT_MODE="key",
    AZURE_DOC_INT_ENDPOINT="https://docint.example",
    AZURE_DOC_INT_API_KEY="secret",
)
def test_check_azure_docint_runs_generated_pdf_smoke_test():
    stdout = StringIO()
    result = build_result()

    with patch(
        "my_app.management.commands.check_azure_docint.get_figure_extraction_client",
        return_value=FakeAzureDocIntExtractionClient(result),
    ):
        call_command("check_azure_docint", stdout=stdout, verbosity=0)

    assert "Azure Document Intelligence check passed" in stdout.getvalue()
    assert "tables=1 figures=1" in stdout.getvalue()


@override_settings(
    FIGURE_EXTRACTION_MODE="azure_doc_int",
    AZURE_DOC_INT_MODE="key",
    AZURE_DOC_INT_ENDPOINT="https://docint.example",
    AZURE_DOC_INT_API_KEY="secret",
)
def test_check_azure_docint_rejects_empty_tables():
    result = FigureExtractionResultData(figures=[], tables=[])

    with patch(
        "my_app.management.commands.check_azure_docint.get_figure_extraction_client",
        return_value=FakeAzureDocIntExtractionClient(result),
    ):
        try:
            call_command("check_azure_docint", verbosity=0)
        except CommandError as exc:
            assert "did not return any tables" in str(exc)
        else:
            raise AssertionError("Expected CommandError")


@override_settings(
    FIGURE_EXTRACTION_MODE="azure_doc_int",
    AZURE_DOC_INT_MODE="key",
    AZURE_DOC_INT_ENDPOINT="https://docint.example",
    AZURE_DOC_INT_API_KEY="secret",
)
def test_check_azure_docint_uses_pdf_path(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(build_docint_smoke_test_pdf())
    result = build_result()

    class PathCheckingClient(FakeAzureDocIntExtractionClient):
        def extract_figures(self, file):
            assert isinstance(file, BytesIO) is False
            assert file.read() == pdf_path.read_bytes()
            return self.result

    with patch(
        "my_app.management.commands.check_azure_docint.get_figure_extraction_client",
        return_value=PathCheckingClient(result),
    ):
        call_command(
            "check_azure_docint",
            "--pdf-path",
            str(pdf_path),
            stdout=StringIO(),
            verbosity=0,
        )
