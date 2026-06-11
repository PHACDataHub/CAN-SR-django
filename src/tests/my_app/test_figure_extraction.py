from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings

from django_database_task.models import DatabaseTask

from my_app.model_factories import DocumentFactory
from my_app.models import (
    Document,
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
)
from my_app.pdf.figure_extraction.azure import (
    ExtractedFigure,
    ExtractedTable,
    FigureExtractionResultData,
    FigureImage,
)
from my_app.pdf.figure_extraction.client import AzureDocIntExtractionClient
from my_app.pdf.types import PdfCoordinate
from my_app.services.figure_extraction_service import (
    FigureExtractionService,
    QueueFigureExtractionService,
)


def _build_pdf_file(name="example.pdf"):
    return SimpleUploadedFile(
        name,
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
        content_type="application/pdf",
    )


def _build_result():
    box = PdfCoordinate(page=1, x=72, y=144, width=120, height=90)
    return FigureExtractionResultData(
        figures=[
            ExtractedFigure(
                index=1,
                provider_id="1.1",
                caption="Figure caption",
                coordinates=[box],
                image=FigureImage(png_bytes=b"png bytes"),
            )
        ],
        tables=[
            ExtractedTable(
                index=1,
                caption="Table caption",
                markdown="| Outcome | Count |\n| --- | --- |\n| Cases | 12 |",
                coordinates=[box],
            )
        ],
    )


def test_azure_docint_client_extracts_tables_and_figures():
    azure_result = SimpleNamespace(
        pages=[
            SimpleNamespace(
                page_number=1,
                width=8.5,
                height=11,
                unit="inch",
            )
        ],
        content=(
            "<table><tr><th>Outcome</th><th>Count</th></tr>"
            "<tr><td>Cases</td><td>12</td></tr></table>"
        ),
        tables=[
            SimpleNamespace(
                bounding_regions=[
                    SimpleNamespace(
                        page_number=1,
                        polygon=[1, 2, 3, 2, 3, 4, 1, 4],
                    )
                ]
            )
        ],
        figures=[
            SimpleNamespace(
                id="1.1",
                caption=SimpleNamespace(content="Figure caption"),
                bounding_regions=[
                    SimpleNamespace(
                        page_number=1,
                        polygon=[0.5, 1, 1.5, 1, 1.5, 2, 0.5, 2],
                    )
                ],
            )
        ],
    )
    poller = SimpleNamespace(
        result=lambda: azure_result,
        _polling_method=SimpleNamespace(
            _initial_response=SimpleNamespace(
                http_response=SimpleNamespace(
                    headers={
                        "operation-location": (
                            "https://example/analyzeResults/result-123"
                            "?api-version=2024-11-30"
                        )
                    }
                )
            )
        ),
    )
    docint_client = MagicMock()
    docint_client.begin_analyze_document.return_value = poller
    docint_client.get_analyze_result_figure.return_value = [b"png bytes"]

    result = AzureDocIntExtractionClient(docint_client).extract_figures(
        BytesIO(b"%PDF-1.4")
    )

    assert result.tables[0].markdown == (
        "| Outcome | Count |\n| --- | --- |\n| Cases | 12 |"
    )
    assert result.tables[0].coordinates[0].as_json_dict() == {
        "page": 1,
        "x": 72.0,
        "y": 144.0,
        "width": 144.0,
        "height": 144.0,
    }
    assert result.figures[0].caption == "Figure caption"
    assert result.figures[0].image.png_bytes == b"png bytes"
    docint_client.get_analyze_result_figure.assert_called_once_with(
        model_id="prebuilt-layout",
        result_id="result-123",
        figure_id="1.1",
    )


def test_figure_extraction_service_saves_result_to_database(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        result = _build_result()

        client = MagicMock()
        client.extract_figures.return_value = result

        with patch(
            "my_app.services.figure_extraction_service.get_figure_extraction_client",
            return_value=client,
        ):
            FigureExtractionService(document=document).perform()

        result_record = FigureExtractionResult.objects.get(document=document)
        table = DocumentTable.objects.get(document=document)
        figure = DocumentFigure.objects.get(document=document)
        figure_bytes = figure.file.read()

    assert result_record.status == FigureExtractionResult.Status.COMPLETED
    assert table.index == 1
    assert table.caption == "Table caption"
    assert table.table_markdown.startswith("| Outcome | Count |")
    assert table.bounding_box == [
        {"page": 1, "x": 72.0, "y": 144.0, "width": 120.0, "height": 90.0}
    ]
    assert figure.caption == "Figure caption"
    assert figure.bounding_box == table.bounding_box
    assert figure.file.name == (
        f"documents/{document.id}/figures/example_figure_1.png"
    )
    assert figure_bytes == b"png bytes"


def test_figure_extraction_service_replaces_existing_artifacts(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        DocumentTable.objects.create(
            document=document,
            index=1,
            table_markdown="old",
            bounding_box=[],
        )
        FigureExtractionResult.objects.create(
            document=document,
            status=FigureExtractionResult.Status.COMPLETED,
        )

        client = MagicMock()
        client.extract_figures.return_value = FigureExtractionResultData(
            figures=[],
            tables=[
                ExtractedTable(
                    index=2,
                    caption=None,
                    markdown="new",
                    coordinates=[],
                )
            ],
        )

        with patch(
            "my_app.services.figure_extraction_service.get_figure_extraction_client",
            return_value=client,
        ):
            FigureExtractionService(document=document).perform()

    assert list(
        DocumentTable.objects.filter(document=document).values_list(
            "index", "table_markdown"
        )
    ) == [(2, "new")]
    assert document.figure_extraction_result.status == (
        FigureExtractionResult.Status.COMPLETED
    )


def test_queue_figure_extraction_service_creates_pending_result_and_enqueues():
    document = DocumentFactory()
    task_mock = MagicMock()
    task_mock.enqueue = MagicMock()

    with patch(
        "my_app.tasks.figure_extraction_task.process_figure_extraction",
        task_mock,
    ):
        QueueFigureExtractionService(document=document).perform()

    result_record = FigureExtractionResult.objects.get(document=document)
    assert result_record.status == FigureExtractionResult.Status.PENDING
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {"document_id": document.id}


def test_process_figure_extraction_task_saves_database_result(tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        result = _build_result()

        client = MagicMock()
        client.extract_figures.return_value = result

        with patch(
            "my_app.services.figure_extraction_service.get_figure_extraction_client",
            return_value=client,
        ):
            QueueFigureExtractionService(document=document).perform()
            assert DatabaseTask.objects.count() == 1

            call_command("run_database_tasks", verbosity=0)

    assert FigureExtractionResult.objects.get(document=document).status == (
        FigureExtractionResult.Status.COMPLETED
    )
    assert DocumentFigure.objects.filter(document=document).count() == 1
    assert DocumentTable.objects.filter(document=document).count() == 1
