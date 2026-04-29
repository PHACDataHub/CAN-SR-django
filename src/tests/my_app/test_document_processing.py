from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from django_database_task.models import DatabaseTask

from my_app.models import Document, DocumentMetadata


def test_process_document_metadata_view_queues_task_and_saves_metadata(
    admin_client, tmp_path
):
    upload_url = reverse("upload_pdf")

    with override_settings(MEDIA_ROOT=tmp_path):
        uploaded_file = SimpleUploadedFile(
            "example.pdf",
            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
            content_type="application/pdf",
        )
        response = admin_client.post(
            upload_url,
            {"pdf_file": uploaded_file},
            follow=True,
        )

        assert response.status_code == 200

        document = Document.objects.get()
        detail_response = admin_client.get(
            reverse("document_detail", args=[document.id])
        )

        assert detail_response.status_code == 200
        assert "Process PDF" in detail_response.content.decode()

        process_response = admin_client.post(
            reverse("process_file", args=[document.id])
        )

        assert process_response.status_code == 302
        assert process_response.url == reverse(
            "document_detail", args=[document.id]
        )
        assert DatabaseTask.objects.count() == 1

        queued_task = DatabaseTask.objects.get()
        assert queued_task.kwargs_json["document_id"] == document.id

        call_command("run_database_tasks", verbosity=0)

        queued_task.refresh_from_db()
        assert queued_task.status == "SUCCESSFUL"

        metadata = DocumentMetadata.objects.get(document=document)
        assert metadata.metadata

        refreshed_detail_response = admin_client.get(
            reverse("document_detail", args=[document.id])
        )
        assert refreshed_detail_response.status_code == 200
        assert "<dl" in refreshed_detail_response.content.decode()
