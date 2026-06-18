from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings

import pytest
from django_database_task.models import DatabaseTask

from my_app.models import Document, TextExtractionResult
from my_app.services.text_extraction import (
    QueueTextExtractionService,
    TextExtractionService,
)

pytestmark = pytest.mark.backend


def _build_pdf_file(name="example.pdf"):
    return SimpleUploadedFile(
        name,
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
        content_type="application/pdf",
    )


def test_queue_text_extraction_service_creates_pending_result_and_enqueues_task(
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
            QueueTextExtractionService(document=document).perform()

    text_extraction_result = TextExtractionResult.objects.get(
        document=document
    )

    assert (
        text_extraction_result.status
        == TextExtractionResult.TextExtractionStatus.PENDING
    )
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {"document_id": document.id}


def test_process_text_extraction_result_task_populates_result_and_marks_completed(
    tmp_path,
):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        QueueTextExtractionService(document=document).perform()

        assert DatabaseTask.objects.count() == 1
        queued_task = DatabaseTask.objects.get()
        assert queued_task.kwargs_json["document_id"] == document.id

        call_command("run_database_tasks", verbosity=0)

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
