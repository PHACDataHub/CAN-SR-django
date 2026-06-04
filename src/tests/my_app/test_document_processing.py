from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings

import pytest
from django_database_task.models import DatabaseTask

from my_app.models import Document, DocumentMetadata
from my_app.services.preprocess_pdf import (
    PreprocessPDFService,
    QueuePreprocessPDFService,
)


def _build_pdf_file(name="example.pdf"):
    return SimpleUploadedFile(
        name,
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
        content_type="application/pdf",
    )


def test_queue_preprocess_pdf_service_creates_pending_metadata_and_enqueues_task(
    tmp_path,
):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())

        task_mock = MagicMock()
        task_mock.enqueue = MagicMock()

        with patch(
            "my_app.tasks.process_document_task.process_document_metadata",
            task_mock,
        ):
            QueuePreprocessPDFService(document=document).perform()

    metadata = DocumentMetadata.objects.get(document=document)

    assert metadata.status == DocumentMetadata.DocumentProcessingStatus.PENDING
    assert task_mock.enqueue.call_count == 1
    assert task_mock.enqueue.call_args.kwargs == {"document_id": document.id}


def test_process_document_metadata_task_populates_metadata_and_marks_completed(
    tmp_path,
):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        QueuePreprocessPDFService(document=document).perform()

        assert DatabaseTask.objects.count() == 1
        queued_task = DatabaseTask.objects.get()
        assert queued_task.kwargs_json["document_id"] == document.id

        call_command("run_database_tasks", verbosity=0)

    queued_task.refresh_from_db()
    assert queued_task.status == "SUCCESSFUL"

    metadata = DocumentMetadata.objects.get(document=document)
    assert (
        metadata.status == DocumentMetadata.DocumentProcessingStatus.COMPLETED
    )
    assert metadata.pages
    assert metadata.coordinates
    assert metadata.raw_xml


def test_preprocess_pdf_service_marks_failed_when_processing_raises(
    tmp_path,
):
    with override_settings(MEDIA_ROOT=tmp_path):
        document = Document.objects.create(file=_build_pdf_file())
        metadata = DocumentMetadata.objects.create(document=document)

        processor = MagicMock()
        processor.process_pdf.side_effect = RuntimeError("boom")

        with patch(
            "my_app.services.preprocess_pdf.get_pdf_processor",
            return_value=processor,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                PreprocessPDFService(document=document).perform()

    metadata.refresh_from_db()
    assert metadata.status == DocumentMetadata.DocumentProcessingStatus.FAILED
