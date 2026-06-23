from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterQuestionFactory,
    ReviewFactory,
    TextExtractionResultFactory,
)
from my_app.models import (
    Document,
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
    L1ScreeningResult,
    L2ScreeningResult,
    ParameterExtractionResult,
    ScreeningResultStatus,
    TextExtractionResult,
)

pytestmark = [pytest.mark.view, pytest.mark.l2_screening]


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
    previous_row = CitationFactory(
        dataset=dataset,
        order=0,
        title="Previous full text",
    )
    row = CitationFactory(
        dataset=dataset,
        order=1,
        title="A full-text citation",
        abstract="With an abstract",
    )
    next_row = CitationFactory(
        dataset=dataset,
        order=2,
        title="Next full text",
    )
    document = DocumentFactory()
    row.document = document
    row.save(update_fields=["document"])
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
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
        evidence_figures=[4],
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_details", args=[review.id, row.id])
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "L2 PDF screening" in body
    assert reverse("screening_l2", args=[review.id]) in body
    assert (
        reverse("screen_l2_row_details", args=[review.id, previous_row.id])
        in body
    )
    assert (
        reverse("screen_l2_row_details", args=[review.id, next_row.id]) in body
    )
    assert "Viewing 1 of 3" in body
    assert "Human reviewed" in body
    assert "0 / 3" in body
    assert "A full-text citation" in body
    assert "With an abstract" not in body
    assert "Uploaded" in body
    assert "Completed" in body
    assert "L2 screening results" in body
    assert question.question_text in body
    assert selected_option.option_text in body
    assert "Looks eligible." in body
    assert 'id="l2-citation-data"' in body
    assert (
        f'data-pdf-url="{reverse("screen_l2_row_pdf", args=[review.id, row.id])}"'
        in body
    )
    assert (
        f'data-metadata-url="{reverse("screen_l2_row_pdf_metadata", args=[review.id, row.id])}"'
        in body
    )
    assert 'id="l2-pdf-scroll"' in body
    assert 'id="l2-pdf-pages"' in body
    assert "screen_l2_citation.js" in body
    assert "screen_l2_citation.css" in body
    assert 'class="btn btn-sm btn-outline-primary l2-evidence-chip"' in body
    assert (
        'data-evidence-type="sentence" data-evidence-index="1">Sentence 1</button>'
        in body
    )
    assert (
        'data-evidence-type="sentence" data-evidence-index="3">Sentence 3</button>'
        in body
    )
    assert (
        'data-evidence-type="table" data-evidence-index="2">Table 2</button>'
        in body
    )
    assert (
        'data-evidence-type="figure" data-evidence-index="4">Figure 4</button>'
        in body
    )
    assert reverse("screen_l2_row_upload", args=[review.id, row.id]) in body
    assert "More" in body
    assert "Re-upload" in body
    assert "Re-screen" in body


def test_screen_l2_row_details_view_renders_screening_process_button(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_details", args=[review.id, row.id])
        )

    body = response.content.decode()
    process_url = reverse("screen_l2_row_process", args=[review.id, row.id])

    assert response.status_code == 200
    assert f'id="l2-pdf-screening-control-{row.id}"' in body
    assert f'hx-post="{process_url}"' in body
    assert 'hx-target="closest .l2-pdf-screening-control"' in body
    assert 'hx-swap="outerHTML"' in body
    assert "Screen this document" in body


def test_screen_l2_row_process_view_enqueues_screening_and_returns_control(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    )
    FigureExtractionResult.objects.create(
        document=document,
        status=FigureExtractionResult.Status.COMPLETED,
    )
    question1 = L2ScreeningQuestionFactory(review=review)
    question2 = L2ScreeningQuestionFactory(review=review)

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.tasks.l2_screening.process_l2_screening_task"
        ) as task_mock:
            response = vanilla_client.post(
                reverse("screen_l2_row_process", args=[review.id, row.id])
            )

    body = response.content.decode()
    results = L2ScreeningResult.objects.filter(citation=row)

    assert response.status_code == 200
    assert f'id="l2-pdf-screening-control-{row.id}"' in body
    assert "Pending" in body
    assert "L2 screening" in body
    assert "Screen this document" not in body
    assert (
        results.filter(
            question__in=[question1, question2],
            status=ScreeningResultStatus.PENDING,
        ).count()
        == 2
    )
    assert task_mock.enqueue.call_count == 2
    assert {
        call.kwargs["result_id"] for call in task_mock.enqueue.call_args_list
    } == {result.id for result in results}


def test_screen_l2_row_process_view_replaces_existing_screening_results(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    )
    FigureExtractionResult.objects.create(
        document=document,
        status=FigureExtractionResult.Status.COMPLETED,
    )
    question = L2ScreeningQuestionFactory(review=review)
    old_result = L2ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.tasks.l2_screening.process_l2_screening_task"
        ) as task_mock:
            response = vanilla_client.post(
                reverse("screen_l2_row_process", args=[review.id, row.id])
            )

    result = L2ScreeningResult.objects.get(citation=row, question=question)

    assert response.status_code == 200
    assert result.id != old_result.id
    assert result.status == ScreeningResultStatus.PENDING
    task_mock.enqueue.assert_called_once_with(result_id=result.id)


def test_screen_l2_row_process_view_rejects_unprocessed_document(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.PENDING,
    )
    L2ScreeningQuestionFactory(review=review)

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.tasks.l2_screening.process_l2_screening_task"
        ) as task_mock:
            response = vanilla_client.post(
                reverse("screen_l2_row_process", args=[review.id, row.id])
            )

    body = response.content.decode()

    assert response.status_code == 409
    assert "Not Started" in body
    assert "Screen this document" not in body
    assert L2ScreeningResult.objects.filter(citation=row).count() == 0
    assert task_mock.enqueue.call_count == 0


def test_l2_human_validation_can_be_set_and_undone(
    vanilla_client, vanilla_user
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset)
    question = L2ScreeningQuestionFactory(review=review)
    selected_option = L2ScreeningQuestionOptionFactory(question=question)
    result = L2ScreeningResultFactory(
        citation=row,
        question=question,
        selected_option=selected_option,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse("screen_l2_validate_correct", args=[review.id, result.id])
        )

    result.refresh_from_db()
    body = response.content.decode()
    assert response.status_code == 200
    assert result.human_validated_by == vanilla_user
    assert result.human_validation_timestamp is not None
    assert "Validated" in body
    assert vanilla_user.username in body
    assert "Undo" in body

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse("screen_l2_undo_validation", args=[review.id, result.id])
        )

    result.refresh_from_db()
    body = response.content.decode()
    assert response.status_code == 200
    assert result.human_validated_by is None
    assert result.human_validation_timestamp is None
    assert "Validate correct" in body
    assert "Manually answer screening" in body


def test_l2_human_answer_modal_saves_question_option_and_notes(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset)
    question = L2ScreeningQuestionFactory(review=review)
    answer = L2ScreeningQuestionOptionFactory(question=question)
    other_answer = L2ScreeningQuestionOptionFactory()
    result = L2ScreeningResultFactory(citation=row, question=question)
    url = reverse("screen_l2_human_answer", args=[review.id, result.id])

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)

    body = response.content.decode()
    assert response.status_code == 200
    assert "Manually answer screening" in body
    assert answer.option_text in body
    assert other_answer.option_text not in body
    assert "human_selected_answer" in body
    assert "human_notes" in body

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            url,
            {
                "human_selected_answer": answer.id,
                "human_notes": "Human review notes.",
            },
        )

    result.refresh_from_db()
    body = response.content.decode()
    assert response.status_code == 200
    assert result.human_selected_answer == answer
    assert result.human_notes == "Human review notes."
    assert result.human_validation_timestamp is None
    assert result.human_validated_by is None
    assert response["HX-Trigger-After-Settle"] == "modal-close"
    assert response["HX-Retarget"] == f"#l2-human-review-{result.id}"
    assert answer.option_text in body
    assert "Human review notes." in body
    assert "Human entered" in body
    assert "Edit" in body


def test_l2_human_review_views_require_access_and_matching_review(
    vanilla_client,
):
    result = L2ScreeningResultFactory()
    other_review = ReviewFactory()
    endpoints = [
        "screen_l2_validate_correct",
        "screen_l2_undo_validation",
        "screen_l2_human_answer",
    ]

    with patch_rules(can_access_review=False):
        for endpoint in endpoints:
            response = vanilla_client.post(
                reverse(endpoint, args=[result.question.review_id, result.id])
            )
            assert response.status_code == 403

    with patch_rules(can_access_review=True):
        for endpoint in endpoints:
            response = vanilla_client.post(
                reverse(endpoint, args=[other_review.id, result.id])
            )
            assert response.status_code == 404


def test_screen_l2_row_details_view_renders_empty_pdf_viewer_without_document(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_details", args=[review.id, row.id])
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Upload a PDF to view the document." in body
    assert 'id="l2-pdf-scroll"' in body
    assert 'id="l2-pdf-pages"' in body
    assert "data-pdf-url" not in body
    assert "data-metadata-url" not in body


def test_screen_l2_row_pdf_view_streams_linked_document(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_pdf", args=[review.id, row.id])
        )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("inline;")
    assert b"".join(response.streaming_content).startswith(b"%PDF-1.4")


def test_screen_l2_row_pdf_metadata_view_returns_evidence_highlights(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    pages = [{"width": 612.0, "height": 792.0}]
    coordinates = [
        {
            "type": "p",
            "text": "Paragraph",
            "page": "1",
            "x": "1",
            "y": "2",
            "width": "3",
            "height": "4",
        },
        {
            "type": "s",
            "text": "First sentence.",
            "page": "1",
            "x": "10",
            "y": "20",
            "width": "30",
            "height": "40",
        },
        {
            "type": "s",
            "text": "Second sentence.",
            "page": "1",
            "x": "50",
            "y": "60",
            "width": "70",
            "height": "80",
        },
        {
            "type": "s",
            "text": "First sentence.",
            "page": "1",
            "x": "90",
            "y": "100",
            "width": "110",
            "height": "120",
        },
    ]
    TextExtractionResultFactory(
        document=document,
        pages=pages,
        coordinates=coordinates,
    )
    first_question = L2ScreeningQuestionFactory(review=review)
    second_question = L2ScreeningQuestionFactory(review=review)
    L2ScreeningResultFactory(
        citation=row,
        question=first_question,
        evidence_sentences=[1, 99, -1, "0"],
        evidence_tables=[2, 99, -1, "1"],
        evidence_figures=[3, 99, -1, "1"],
    )
    L2ScreeningResultFactory(
        citation=row,
        question=second_question,
        evidence_sentences=[1, 0],
        evidence_tables=[2],
        evidence_figures=[3],
    )
    table = DocumentTable.objects.create(
        document=document,
        index=2,
        caption="Evidence table",
        table_markdown="| Outcome | Count |",
        bounding_box=[
            {
                "page": 1,
                "x": 130,
                "y": 140,
                "width": 150,
                "height": 160,
            }
        ],
    )
    figure = DocumentFigure.objects.create(
        document=document,
        index=3,
        caption="Evidence figure",
        bounding_box=[
            {
                "page": 1,
                "x": 170,
                "y": 180,
                "width": 190,
                "height": 200,
            }
        ],
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_pdf_metadata", args=[review.id, row.id])
        )

    assert response.status_code == 200
    assert response.json() == {
        "pages": pages,
        "highlights": [
            {
                **coordinates[2],
                "sentence_index": 1,
                "evidence_type": "sentence",
                "evidence_index": 1,
            },
            {
                **coordinates[1],
                "sentence_index": 0,
                "evidence_type": "sentence",
                "evidence_index": 0,
            },
            {
                **coordinates[3],
                "sentence_index": 0,
                "evidence_type": "sentence",
                "evidence_index": 0,
            },
            {
                **table.bounding_box[0],
                "evidence_type": "table",
                "evidence_index": 2,
            },
            {
                **figure.bounding_box[0],
                "evidence_type": "figure",
                "evidence_index": 3,
            },
        ],
    }


@pytest.mark.parametrize(
    "url_name",
    [
        "screen_l2_row_pdf",
        "screen_l2_row_pdf_metadata",
    ],
)
def test_screen_l2_row_pdf_views_return_404_without_document(
    vanilla_client,
    url_name,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(url_name, args=[review.id, row.id])
        )

    assert response.status_code == 404


def test_screen_l2_row_pdf_metadata_view_returns_404_without_result(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(
        dataset=dataset,
        order=1,
        document=DocumentFactory(),
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l2_row_pdf_metadata", args=[review.id, row.id])
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "url_name",
    [
        "screen_l2_row_details",
        "screen_l2_row_process",
        "screen_l2_row_pdf",
        "screen_l2_row_pdf_metadata",
    ],
)
def test_screen_l2_row_pdf_views_require_review_access(
    vanilla_client,
    url_name,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    TextExtractionResultFactory(document=document)

    with patch_rules(can_access_review=False):
        url = reverse(url_name, args=[review.id, row.id])
        if url_name == "screen_l2_row_process":
            response = vanilla_client.post(url)
        else:
            response = vanilla_client.get(url)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "url_name",
    [
        "screen_l2_row_details",
        "screen_l2_row_process",
        "screen_l2_row_pdf",
        "screen_l2_row_pdf_metadata",
    ],
)
def test_screen_l2_row_pdf_views_return_404_for_row_from_another_review(
    vanilla_client,
    url_name,
):
    requested_review = ReviewFactory()
    row_review = ReviewFactory()
    dataset = CitationDatasetFactory(review=row_review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    TextExtractionResultFactory(document=document)

    with patch_rules(can_access_review=True):
        url = reverse(url_name, args=[requested_review.id, row.id])
        if url_name == "screen_l2_row_process":
            response = vanilla_client.post(url)
        else:
            response = vanilla_client.get(url)

    assert response.status_code == 404


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
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
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
    assert "Danger zone" not in body
    assert "I understand this will delete the existing document" in body


def test_screen_l2_row_upload_view_uploads_document_and_triggers_refresh(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.views.screening.l2_screening_views.QueueProcessDocumentService.perform"
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
    TextExtractionResultFactory(document=old_document)

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
            "my_app.views.screening.l2_screening_views.QueueProcessDocumentService.perform"
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
