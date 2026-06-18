from __future__ import annotations

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from my_app.pdf.figure_extraction.azure import FigureExtractionResultData
from my_app.pdf.figure_extraction.client import (
    AzureDocIntExtractionClient,
    DocIntConfigurationError,
    get_figure_extraction_client,
)


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_command(x: int, y: int, value: str, size: int = 10) -> str:
    escaped_value = _escape_pdf_text(value)
    return f"BT /F1 {size} Tf {x} {y} Td ({escaped_value}) Tj ET"


def _build_pdf(objects: list[str]) -> bytes:
    pdf = "%PDF-1.4\n"
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf.encode("latin-1")))
        pdf += f"{index} 0 obj\n{obj}\nendobj\n"

    xref_offset = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objects) + 1}\n"
    pdf += "0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += (
        "trailer\n"
        f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        "startxref\n"
        f"{xref_offset}\n"
        "%%EOF\n"
    )
    return pdf.encode("latin-1")


def build_docint_smoke_test_pdf() -> bytes:
    commands = [
        _text_command(72, 740, "Azure Document Intelligence smoke test", 16),
        _text_command(72, 710, "Table 1. Example extraction data", 11),
        "1 w",
        "72 690 m 432 690 l S",
        "72 660 m 432 660 l S",
        "72 630 m 432 630 l S",
        "72 600 m 432 600 l S",
        "72 600 m 72 690 l S",
        "192 600 m 192 690 l S",
        "312 600 m 312 690 l S",
        "432 600 m 432 690 l S",
        _text_command(84, 672, "Outcome"),
        _text_command(204, 672, "Group A"),
        _text_command(324, 672, "Group B"),
        _text_command(84, 642, "Cases"),
        _text_command(204, 642, "12"),
        _text_command(324, 642, "9"),
        _text_command(84, 612, "Controls"),
        _text_command(204, 612, "30"),
        _text_command(324, 612, "28"),
        _text_command(72, 548, "Figure 1. Dummy image for extraction", 11),
        "0.90 0.95 1.00 rg",
        "72 380 210 150 re f",
        "0 0 0 RG",
        "2 w",
        "72 380 210 150 re S",
        "1 w",
        "92 415 m 150 500 l 220 420 l S",
        "155 445 m 190 490 l 245 420 l S",
        _text_command(106, 394, "Dummy image", 12),
    ]
    content = "\n".join(commands)

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 4 0 R >> >> "
            "/Contents 5 0 R >>"
        ),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream",
    ]
    return _build_pdf(objects)


def validate_docint_result(result: FigureExtractionResultData) -> None:
    if not result.tables:
        raise ValueError(
            "Azure Document Intelligence did not return any tables"
        )

    for table in result.tables:
        if not table.markdown.strip():
            raise ValueError(
                "Azure Document Intelligence returned an empty table"
            )
        if not table.coordinates:
            raise ValueError(
                "Azure Document Intelligence returned a table without coordinates"
            )

    for figure in result.figures:
        if not figure.provider_id:
            raise ValueError(
                "Azure Document Intelligence returned a figure without an Azure ID"
            )
        if figure.image is not None and not figure.image.png_bytes:
            raise ValueError(
                "Azure Document Intelligence returned an empty figure image"
            )


def get_azure_docint_client() -> AzureDocIntExtractionClient:
    if settings.FIGURE_EXTRACTION_MODE != "azure_doc_int":
        raise CommandError(
            "FIGURE_EXTRACTION_MODE='%s' does not select Azure Document "
            "Intelligence. Set FIGURE_EXTRACTION_MODE='azure_doc_int'."
            % settings.FIGURE_EXTRACTION_MODE
        )

    try:
        client = get_figure_extraction_client()
    except DocIntConfigurationError as exc:
        raise CommandError(str(exc)) from exc

    if not isinstance(client, AzureDocIntExtractionClient):
        raise CommandError(
            "Configured figure extraction client is %s, expected %s"
            % (
                client.__class__.__name__,
                AzureDocIntExtractionClient.__name__,
            )
        )

    return client


def run_smoke_test(pdf_path: Path | None = None) -> FigureExtractionResultData:
    client = get_azure_docint_client()

    if pdf_path is not None:
        with pdf_path.open("rb") as pdf_file:
            result = client.extract_figures(pdf_file)
    else:
        with tempfile.TemporaryFile() as pdf_file:
            pdf_file.write(build_docint_smoke_test_pdf())
            pdf_file.seek(0)
            result = client.extract_figures(pdf_file)

    validate_docint_result(result)
    return result


class Command(BaseCommand):
    help = (
        "Check the configured Azure Document Intelligence figure extraction "
        "client and run a real PDF smoke test."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf-path",
            help=(
                "Optional path to a PDF to process instead of the generated "
                "smoke-test PDF."
            ),
        )

    def handle(self, *args, **options):
        pdf_path = None
        if options["pdf_path"]:
            pdf_path = Path(options["pdf_path"])
            if not pdf_path.exists():
                raise CommandError("PDF file does not exist: %s" % pdf_path)
            if not pdf_path.is_file():
                raise CommandError("PDF path is not a file: %s" % pdf_path)

        try:
            result = run_smoke_test(pdf_path=pdf_path)
        except Exception as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError(
                "Azure Document Intelligence smoke test failed: %s" % exc
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Azure Document Intelligence check passed: tables=%s figures=%s"
                % (len(result.tables), len(result.figures))
            )
        )
