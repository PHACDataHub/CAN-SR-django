from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    DocumentMetadataFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterQuestionFactory,
    ReviewFactory,
)
from my_app.models import (
    Document,
    DocumentMetadata,
    L1ScreeningResult,
    L2ScreeningResult,
    ParameterExtractionResult,
    ScreeningResultStatus,
)


def _build_pdf_file(name="example.pdf"):
    return SimpleUploadedFile(
        name,
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
        content_type="application/pdf",
    )


def test_screening_l2_shell_renders_component_and_refresh_button(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L2ScreeningQuestionFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    L2ScreeningQuestionOptionFactory(question=question)
    L2ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l2", args=[review.id]), {"page": 1}
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "L2 Screening" in body
    assert reverse("screening_l2_component", args=[review.id]) in body
    assert 'hx-target="#l2-screening-component"' in body
    assert 'hx-swap="outerHTML"' in body
    assert "Refresh" in body


def test_screening_l2_component_view_renders(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L2ScreeningQuestionFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    L2ScreeningQuestionOptionFactory(question=question)
    L2ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l2_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "l2-screening-component" in body
    assert "l2-screening-progress-panel" in body
    assert "Progress" in body
    assert "Completed" in body


def test_screening_l2_component_view_renders_pagination_buttons(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L2ScreeningQuestionFactory(review=review)
    L2ScreeningQuestionOptionFactory(question=question)
    for order in range(1, 12):
        row = CitationFactory(dataset=dataset, order=order)
        L2ScreeningResultFactory(
            citation=row,
            question=question,
            status=ScreeningResultStatus.COMPLETED,
        )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l2_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()
    component_url = reverse("screening_l2_component", args=[review.id])

    assert response.status_code == 200
    assert f"{component_url}?page=2" in body
    assert "Next" in body


def test_screening_l2_component_view_renders_row_view_link(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l2_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()
    details_url = reverse("screen_l2_row_details", args=[review.id, row.id])
    upload_url = reverse("screen_l2_row_upload", args=[review.id, row.id])

    assert response.status_code == 200
    assert details_url in body
    assert upload_url in body
    assert "View" in body
    assert "Upload" in body


def test_screen_l2_row_details_view_renders_citation_and_results(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(
        dataset=dataset,
        order=1,
        title="A full-text citation",
        abstract="With an abstract",
    )
    document = DocumentFactory()
    row.document = document
    row.save(update_fields=["document"])
    DocumentMetadataFactory(
        document=document,
        status=DocumentMetadata.DocumentProcessingStatus.COMPLETED,
    )

    question = L2ScreeningQuestionFactory(review=review)
    selected_option = L2ScreeningQuestionOptionFactory(question=question)
    L2ScreeningResultFactory(
        citation=row,
        question=question,
        selected_option=selected_option,
        status=ScreeningResultStatus.COMPLETED,
        explanation="Looks eligible.",
        evidence_sentences=[1, 3],
        evidence_tables=[2],
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_details", args=[review.id, row.id])
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "L2 PDF screening" in body
    assert reverse("screening_l2", args=[review.id]) in body
    assert "A full-text citation" in body
    assert "With an abstract" in body
    assert "Uploaded" in body
    assert "Completed" in body
    assert "L2 screening results" in body
    assert question.question_text in body
    assert selected_option.option_text in body
    assert "Looks eligible." in body
    assert "1, 3" in body
    assert "2" in body
    assert reverse("screen_l2_row_upload", args=[review.id, row.id]) in body
    assert "Upload" in body or "Re-upload" in body


def test_screening_l2_component_view_renders_upload_and_screening_statuses(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L2ScreeningQuestionFactory(review=review)
    L2ScreeningQuestionOptionFactory(question=question)

    uploaded_row = CitationFactory(dataset=dataset, order=1)
    document = DocumentFactory()
    uploaded_row.document = document
    uploaded_row.save(update_fields=["document"])
    DocumentMetadataFactory(
        document=document,
        status=DocumentMetadata.DocumentProcessingStatus.COMPLETED,
    )
    L2ScreeningResultFactory(
        citation=uploaded_row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    CitationFactory(dataset=dataset, order=2)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l2_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Uploaded" in body
    assert "Completed" in body
    assert "Not uploaded" in body
    assert "Not Started" in body
    assert "Pending" in body


def test_screen_l2_row_upload_view_renders_plain_upload_form(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_upload", args=[review.id, row.id])
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Upload document" in body
    assert "Danger zone" not in body
    assert "confirm_replace" not in body


def test_screen_l2_row_upload_view_renders_replace_form_for_existing_document(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    row.document = DocumentFactory()
    row.save(update_fields=["document"])

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_upload", args=[review.id, row.id])
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Replace document" in body
    assert "Danger zone" in body
    assert "I understand this will delete the existing document" in body


def test_screen_l2_row_upload_view_uploads_document_and_triggers_refresh(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.views.screening_l2.QueuePreprocessPDFService.perform"
        ) as perform_mock:
            response = vanilla_client.post(
                reverse("screen_l2_row_upload", args=[review.id, row.id]),
                {
                    "document_file": _build_pdf_file(),
                },
            )

    assert response.status_code == 200
    assert response["HX-Trigger"] == "citations-update"
    assert response["HX-Trigger-After-Settle"] == "modal-close"
    assert response["HX-Reswap"] == "none"
    assert perform_mock.call_count == 1
    row.refresh_from_db()
    assert row.document is not None
    assert Document.objects.filter(pk=row.document_id).exists()


def test_screen_l2_row_upload_view_replaces_document_and_deletes_old_data(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L1ScreeningQuestionFactory(review=review)
    l2_question = L2ScreeningQuestionFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    old_document = DocumentFactory()
    row.document = old_document
    row.save(update_fields=["document"])
    DocumentMetadataFactory(document=old_document)

    L1ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )
    L2ScreeningResultFactory(
        citation=row,
        question=l2_question,
        status=ScreeningResultStatus.PENDING,
    )
    parameter_question = ParameterQuestionFactory(review=review)
    ParameterExtractionResultFactory(
        citation=row,
        question=parameter_question,
        status=ScreeningResultStatus.PENDING,
    )

    new_file = _build_pdf_file("replacement.pdf")

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.views.screening_l2.QueuePreprocessPDFService.perform"
        ) as perform_mock:
            response = vanilla_client.post(
                reverse("screen_l2_row_upload", args=[review.id, row.id]),
                {
                    "document_file": new_file,
                    "confirm_replace": "on",
                },
            )

    assert response.status_code == 200
    assert response["HX-Trigger"] == "citations-update"
    assert perform_mock.call_count == 1

    row.refresh_from_db()
    assert row.document is not None
    assert row.document_id != old_document.id
    assert Document.objects.filter(pk=old_document.id).count() == 0
    assert L1ScreeningResult.objects.filter(citation=row).count() == 0
    assert L2ScreeningResult.objects.filter(citation=row).count() == 0
    assert ParameterExtractionResult.objects.filter(citation=row).count() == 0


def test_screen_l2_row_upload_view_rejects_replace_without_confirmation(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    row.document = DocumentFactory()
    row.save(update_fields=["document"])

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse("screen_l2_row_upload", args=[review.id, row.id]),
            {
                "document_file": _build_pdf_file(),
            },
        )

    assert response.status_code == 200
    assert response["HX-Refocus"] == "#form-error-summary"
    assert Document.objects.filter(pk=row.document_id).exists()
