from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

import pytest
from django_tasks_db.models import DBTaskResult

from my_app.models import Document, TextExtractionResult
from my_app.services.text_extraction import TextExtractionService
from my_app.tasks.text_extraction_task import process_text_extraction_result

pytestmark = pytest.mark.backend


def _build_pdf_file(name="example.pdf"):
    return SimpleUploadedFile(
        name,
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
        content_type="application/pdf",
    )


def test_text_extraction_service_prepare_creates_pending_result_and_does_not_enqueue(
    tmp_path,
):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())

        task_mock = MagicMock()
        task_mock.enqueue = MagicMock()

        with patch(
            "my_app.tasks.text_extraction_task.process_text_extraction_result",
            task_mock,
        ):
            TextExtractionService(document=document).prepare()

    text_extraction_result = TextExtractionResult.objects.get(
        document=document
    )

    assert (
        text_extraction_result.status
        == TextExtractionResult.TextExtractionStatus.PENDING
    )
    assert task_mock.enqueue.call_count == 0


def test_process_text_extraction_result_task_populates_result_and_marks_completed(
    tmp_path, run_database_tasks
):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        TextExtractionService(document=document).prepare()
        process_text_extraction_result.enqueue(document_id=document.id)

        assert DBTaskResult.objects.count() == 1
        queued_task = DBTaskResult.objects.get()
        assert queued_task.args_kwargs["kwargs"]["document_id"] == document.id

        run_database_tasks()

    queued_task.refresh_from_db()
    assert queued_task.status == "SUCCESSFUL"

    text_extraction_result = TextExtractionResult.objects.get(
        document=document
    )
    assert (
        text_extraction_result.status
        == TextExtractionResult.TextExtractionStatus.COMPLETED
    )
    assert text_extraction_result.pages
    assert text_extraction_result.coordinates
    assert text_extraction_result.raw_xml


def test_text_extraction_service_marks_failed_when_processing_raises(
    tmp_path,
):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        text_extraction_result = TextExtractionResult.objects.create(
            document=document
        )

        processor = MagicMock()
        processor.process_pdf.side_effect = RuntimeError("boom")

        with patch(
            "my_app.services.text_extraction.get_pdf_processor",
            return_value=processor,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                TextExtractionService(document=document).perform()

    text_extraction_result.refresh_from_db()
    assert (
        text_extraction_result.status
        == TextExtractionResult.TextExtractionStatus.FAILED
    )
