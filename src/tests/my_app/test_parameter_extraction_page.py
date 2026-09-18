from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
    ParameterHumanAnswerFactory,
    ParameterOptionFactory,
    ReviewFactory,
    TextExtractionResultFactory,
)
from my_app.models import (
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
    Parameter,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    ScreeningResultStatus,
    TextExtractionResult,
)

pytestmark = [pytest.mark.view]


def test_parameter_extraction_shell_renders_component_and_refresh_button(
    vanilla_client,
):
    review = ReviewFactory()
    CitationDatasetFactory(review=review)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("parameter_extraction_citations_list", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Parameter extraction" in body
    assert (
        reverse(
            "parameter_extraction_citations_list_partial", args=[review.id]
        )
        in body
    )
    assert 'hx-target="#parameter-extraction-component"' in body
    assert 'hx-swap="morph:outerHTML"' in body
    assert (
        'hx-trigger="click from:#refresh-button, citations-update from:body, every 5s"'
        in body
    )
    assert "Refresh" in body


@override_settings(ENABLE_HTMX_POLLING=False)
def test_parameter_extraction_shell_can_disable_polling(vanilla_client):
    review = ReviewFactory()
    CitationDatasetFactory(review=review)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("parameter_extraction_citations_list", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert (
        'hx-trigger="click from:#refresh-button, citations-update from:body"'
        in body
    )
    assert "every 5s" not in body


def test_parameter_extraction_component_view_renders(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    parameter_review = review
    parameter = ParameterFactory(review=parameter_review)
    row = CitationFactory(dataset=dataset, order=1)
    ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                "parameter_extraction_citations_list_partial", args=[review.id]
            ),
            {"page": 1},
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "parameter-extraction-component" in body
    assert "parameter-extraction-progress-panel" in body
    assert "Progress" in body
    assert "Completed" in body


def test_parameter_extraction_row_details_view_renders_pdf_and_results(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    previous_row = CitationFactory(dataset=dataset, order=0)
    document = DocumentFactory()
    row = CitationFactory(
        dataset=dataset,
        order=1,
        title="Parameter citation",
        document=document,
    )
    next_row = CitationFactory(dataset=dataset, order=2)
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    )
    FigureExtractionResult.objects.create(
        document=document,
        status=FigureExtractionResult.Status.COMPLETED,
    )
    parameter_review = review
    parameter = ParameterFactory(review=parameter_review, name="Daily dose")
    ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
        found=True,
        value="10 mg",
        explanation="Reported in the methods.",
        evidence_sentences=[1],
        evidence_tables=[2],
        evidence_figures=[3],
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                "parameter_extraction_citation_detail",
                args=[review.id, row.id],
            )
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Parameter PDF extraction" in body
    assert (
        reverse("parameter_extraction_citations_list", args=[review.id])
        in body
    )
    assert (
        reverse(
            "parameter_extraction_citation_detail",
            args=[review.id, previous_row.id],
        )
        in body
    )
    assert (
        reverse(
            "parameter_extraction_citation_detail",
            args=[review.id, next_row.id],
        )
        in body
    )
    assert "Parameter citation" in body
    assert "Parameter extraction results" in body
    assert "Daily dose" in body
    assert "10 mg" in body
    assert "Reported in the methods." in body
    assert "AI answer" in body
    assert "Validate" in body
    assert "Add your answer" in body
    assert 'hx-swap="morph:outerHTML"' in body
    assert 'id="parameter-extraction-citation-data"' in body
    assert (
        f'data-pdf-url="{reverse("citation_download_pdf_document", args=[review.id, row.id])}"'
        in body
    )
    assert (
        f'data-metadata-url="{reverse("parameter_extraction_citation_pdf_metadata", args=[review.id, row.id])}"'
        in body
    )
    assert 'id="citation-pdf-scroll"' in body
    assert 'id="citation-pdf-pages"' in body
    assert "citation_pdf.js" in body
    assert "citation_pdf.css" in body
    assert 'class="btn btn-sm btn-outline-primary evidence-chip"' in body
    assert (
        'data-evidence-type="sentence" data-evidence-index="1">Sentence 1</button>'
        in body
    )
    assert (
        'data-evidence-type="table" data-evidence-index="2">Table 2</button>'
        in body
    )
    assert (
        'data-evidence-type="figure" data-evidence-index="3">Figure 3</button>'
        in body
    )
    assert "Re-extract" in body


def test_parameter_extraction_validate_ai_answer_creates_human_answer(
    vanilla_client, vanilla_user
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    parameter = ParameterFactory(review=review)
    result = ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
        found=True,
        value="10 mg",
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse(
                "parameter_extraction_citation_validate_ai_answer",
                args=[review.id, result.id],
            )
        )

    body = response.content.decode()
    human_answer = ParameterHumanAnswer.objects.get()

    assert response.status_code == 200
    assert human_answer.user == vanilla_user
    assert human_answer.citation == row
    assert human_answer.question == parameter
    assert human_answer.found is True
    assert human_answer.value == "10 mg"
    assert human_answer.notes is None
    assert "Correct" in body
    assert "Your answer" in body
    assert "10 mg" in body


def test_parameter_extraction_human_answer_modal_saves_and_edits_values(
    vanilla_client, vanilla_user
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    parameter = ParameterFactory(review=review)
    result = ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
        found=True,
        value="10 mg",
    )
    other_reviewer_answer = ParameterHumanAnswerFactory(
        citation=row,
        question=parameter,
        found=True,
        value="10 mg",
        notes="Other reviewer notes.",
    )
    url = reverse(
        "parameter_extraction_citation_human_answer",
        args=[review.id, result.id],
    )

    with patch_rules(can_access_review=True):
        get_response = vanilla_client.get(url)
        post_response = vanilla_client.post(
            url,
            {
                "found": "False",
                "value": "Not reported",
                "notes": "Checked the full text.",
            },
        )

    human_answer = ParameterHumanAnswer.objects.get(user=vanilla_user)
    get_body = get_response.content.decode()
    post_body = post_response.content.decode()

    assert get_response.status_code == 200
    assert "Your parameter answer" in get_body
    assert "Found" in get_body
    assert post_response.status_code == 200
    assert post_response["HX-Trigger-After-Settle"] == "modal-close"
    assert post_response["HX-Reswap"] == "morph:outerHTML"
    assert human_answer.found is False
    assert human_answer.value == "Not reported"
    assert human_answer.notes == "Checked the full text."
    assert "Your answer" in post_body
    assert other_reviewer_answer.user.username in post_body
    assert "Detection disagreement" in post_body
    assert "Not reported" in post_body

    with patch_rules(can_access_review=True):
        edit_response = vanilla_client.post(
            url,
            {
                "found": "True",
                "value": "10 mg",
                "notes": "Updated notes.",
            },
        )

    human_answer.refresh_from_db()
    assert edit_response.status_code == 200
    assert human_answer.found is True
    assert human_answer.value == "10 mg"
    assert human_answer.notes == "Updated notes."
    assert ParameterHumanAnswer.objects.count() == 2


def test_parameter_extraction_human_answer_selects_parameter_option(
    vanilla_client, vanilla_user
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset)
    parameter = ParameterFactory(
        review=review,
        option_type=Parameter.OptionType.SELECT,
    )
    option = ParameterOptionFactory(parameter=parameter, name="High dose")
    deleted_option = ParameterOptionFactory(
        parameter=parameter,
        name="Deleted dose",
    )
    deleted_option.soft_delete()
    result = ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
        found=True,
        selected_option=option,
    )
    url = reverse(
        "parameter_extraction_citation_human_answer",
        args=[review.id, result.id],
    )

    with patch_rules(can_access_review=True):
        get_response = vanilla_client.get(url)
        response = vanilla_client.post(
            url,
            {
                "found": "True",
                "selected_option": option.id,
                "notes": "Matched the reported band.",
            },
        )

    answer = ParameterHumanAnswer.objects.get(user=vanilla_user)
    assert response.status_code == 200
    assert "High dose" in get_response.content.decode()
    assert "Deleted dose" not in get_response.content.decode()
    assert answer.selected_option == option
    assert "High dose" in response.content.decode()


def test_parameter_extraction_process_view_enqueues_extraction_and_returns_control(
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
    parameter_review = review
    parameter1 = ParameterFactory(review=parameter_review)
    parameter2 = ParameterFactory(review=parameter_review)
    deleted_parameter = ParameterFactory(review=parameter_review)
    deleted_parameter.soft_delete()

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.tasks.parameter_extraction.process_parameter_extraction_task"
        ) as task_mock:
            response = vanilla_client.post(
                reverse(
                    "parameter_extraction_citation_process_extraction",
                    args=[review.id, row.id],
                )
            )

    body = response.content.decode()
    results = ParameterExtractionResult.objects.filter(citation=row)

    assert response.status_code == 200
    assert f'id="parameter-extraction-control-{row.id}"' in body
    assert "Pending" in body
    assert "Parameter extraction" in body
    assert "Extract parameters" not in body
    assert (
        results.filter(
            question__in=[parameter1, parameter2],
            status=ScreeningResultStatus.PENDING,
        ).count()
        == 2
    )
    assert task_mock.enqueue.call_count == 2
    assert not results.filter(question=deleted_parameter).exists()
    assert {
        call.kwargs["result_id"] for call in task_mock.enqueue.call_args_list
    } == {result.id for result in results}


def test_parameter_extraction_process_view_rejects_unprocessed_document(
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
    ParameterFactory(review=review)

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.tasks.parameter_extraction.process_parameter_extraction_task"
        ) as task_mock:
            response = vanilla_client.post(
                reverse(
                    "parameter_extraction_citation_process_extraction",
                    args=[review.id, row.id],
                )
            )

    body = response.content.decode()

    assert response.status_code == 409
    assert "Not Started" in body
    assert "Extract parameters" not in body
    assert ParameterExtractionResult.objects.filter(citation=row).count() == 0
    assert task_mock.enqueue.call_count == 0


def test_parameter_extraction_pdf_metadata_view_returns_evidence_highlights(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    pages = [{"width": 612.0, "height": 792.0}]
    coordinates = [
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
    ]
    TextExtractionResultFactory(
        document=document,
        pages=pages,
        coordinates=coordinates,
    )
    parameter = ParameterFactory(review=review)
    ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        evidence_sentences=[1, 99, -1, "0"],
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
            reverse(
                "parameter_extraction_citation_pdf_metadata",
                args=[review.id, row.id],
            )
        )

    assert response.status_code == 200
    assert response.json() == {
        "pages": pages,
        "highlights": [
            {
                **coordinates[1],
                "sentence_index": 1,
                "evidence_type": "sentence",
                "evidence_index": 1,
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
        "parameter_extraction_citation_detail",
        "parameter_extraction_citation_process_extraction",
        "citation_download_pdf_document",
        "parameter_extraction_citation_pdf_metadata",
        "parameter_extraction_citation_validate_ai_answer",
        "parameter_extraction_citation_human_answer",
    ],
)
def test_parameter_extraction_views_require_review_access(
    vanilla_client,
    url_name,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    document = DocumentFactory()
    row = CitationFactory(dataset=dataset, order=1, document=document)
    TextExtractionResultFactory(document=document)
    parameter = ParameterFactory(review=review)
    result = ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
    )

    with patch_rules(can_access_review=False):
        if url_name in (
            "parameter_extraction_citation_validate_ai_answer",
            "parameter_extraction_citation_human_answer",
        ):
            url = reverse(url_name, args=[review.id, result.id])
        else:
            url = reverse(url_name, args=[review.id, row.id])

        if url_name in (
            "parameter_extraction_citation_process_extraction",
            "parameter_extraction_citation_validate_ai_answer",
        ):
            response = vanilla_client.post(url)
        else:
            response = vanilla_client.get(url)

    assert response.status_code == 403
