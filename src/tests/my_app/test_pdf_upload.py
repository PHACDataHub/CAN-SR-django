from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from my_app.models import Document


def test_pdf_upload_creates_document_and_shows_list_and_detail(
    admin_client, tmp_path
):
    url = reverse("upload_pdf")

    with override_settings(MEDIA_ROOT=tmp_path):
        response = admin_client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert "Upload a PDF" in content
        assert "multipart/form-data" in content
        assert reverse("upload_pdf") in content

        uploaded_file = SimpleUploadedFile(
            "example.pdf",
            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
            content_type="application/pdf",
        )
        response = admin_client.post(
            url,
            {"pdf_file": uploaded_file},
            follow=True,
        )

        assert response.status_code == 200
        assert "PDF uploaded" in response.content.decode()
        assert "Document list" in response.content.decode()
        assert "Upload new PDF" in response.content.decode()

    document = Document.objects.get()
    assert document.document_type == "pdf"
    assert document.uploaded_by.username == "admin"
    assert document.file.name == "documents/example.pdf"
    assert document.uploaded_at is not None
    assert (tmp_path / "documents" / "example.pdf").exists()

    detail_response = admin_client.get(
        reverse("document_detail", args=[document.id])
    )

    assert detail_response.status_code == 200
    detail_content = detail_response.content.decode()
    assert "Document detail" in detail_content
    assert "documents/example.pdf" in detail_content
    assert "Open file" in detail_content
