from unittest.mock import patch

from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    ParameterCategoryFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
    ReviewFactory,
    TextExtractionResultFactory,
)
from my_app.models import (
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
    ParameterExtractionResult,
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
            reverse("parameter_extraction", args=[review.id]), {"page": 1}
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Parameter extraction" in body
    assert reverse("parameter_extraction_component", args=[review.id]) in body
    assert 'hx-target="#parameter-extraction-component"' in body
    assert 'hx-swap="outerHTML"' in body
    assert "Refresh" in body


def test_parameter_extraction_component_view_renders(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    category = ParameterCategoryFactory(review=review)
    parameter = ParameterFactory(category=category)
    row = CitationFactory(dataset=dataset, order=1)
    ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("parameter_extraction_component", args=[review.id]),
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
    category = ParameterCategoryFactory(review=review, name="Dose")
    parameter = ParameterFactory(category=category, name="Daily dose")
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
                "parameter_extraction_row_details", args=[review.id, row.id]
            )
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "Parameter PDF extraction" in body
    assert reverse("parameter_extraction", args=[review.id]) in body
    assert (
        reverse(
            "parameter_extraction_row_details",
            args=[review.id, previous_row.id],
        )
        in body
    )
    assert (
        reverse(
            "parameter_extraction_row_details",
            args=[review.id, next_row.id],
        )
        in body
    )
    assert "Parameter citation" in body
    assert "Parameter extraction results" in body
    assert "Daily dose" in body
    assert "Dose" in body
    assert "10 mg" in body
    assert "Reported in the methods." in body
    assert "Needs human review" in body
    assert "Validate AI answer" in body
    assert "Modify human values" in body
    assert 'id="parameter-extraction-citation-data"' in body
    assert (
        f'data-pdf-url="{reverse("parameter_extraction_row_pdf", args=[review.id, row.id])}"'
        in body
    )
    assert (
        f'data-metadata-url="{reverse("parameter_extraction_row_pdf_metadata", args=[review.id, row.id])}"'
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


def test_parameter_extraction_validate_ai_answer_sets_human_values(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    parameter = ParameterFactory(
        category=ParameterCategoryFactory(review=review)
    )
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
                "parameter_extraction_validate_ai_answer",
                args=[review.id, result.id],
            )
        )

    result.refresh_from_db()
    body = response.content.decode()

    assert response.status_code == 200
    assert result.human_found is True
    assert result.human_value == "10 mg"
    assert "Human entered" in body
    assert "Human found" in body
    assert "10 mg" in body


def test_parameter_extraction_human_answer_modal_saves_values(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    parameter = ParameterFactory(
        category=ParameterCategoryFactory(review=review)
    )
    result = ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
        status=ScreeningResultStatus.COMPLETED,
        found=True,
        value="10 mg",
    )
    url = reverse(
        "parameter_extraction_human_answer",
        args=[review.id, result.id],
    )

    with patch_rules(can_access_review=True):
        get_response = vanilla_client.get(url)
        post_response = vanilla_client.post(
            url,
            {"human_found": "False", "human_value": "Not reported"},
        )

    result.refresh_from_db()
    get_body = get_response.content.decode()
    post_body = post_response.content.decode()

    assert get_response.status_code == 200
    assert "Modify human values" in get_body
    assert "Human found" in get_body
    assert post_response.status_code == 200
    assert post_response["HX-Trigger-After-Settle"] == "modal-close"
    assert result.human_found is False
    assert result.human_value == "Not reported"
    assert "Human entered" in post_body
    assert "Not reported" in post_body


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
    category = ParameterCategoryFactory(review=review)
    parameter1 = ParameterFactory(category=category)
    parameter2 = ParameterFactory(category=category)

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.tasks.parameter_extraction.process_parameter_extraction_task"
        ) as task_mock:
            response = vanilla_client.post(
                reverse(
                    "parameter_extraction_row_process",
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
    ParameterFactory(category=ParameterCategoryFactory(review=review))

    with patch_rules(can_access_review=True):
        with patch(
            "my_app.tasks.parameter_extraction.process_parameter_extraction_task"
        ) as task_mock:
            response = vanilla_client.post(
                reverse(
                    "parameter_extraction_row_process",
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
    parameter = ParameterFactory(
        category=ParameterCategoryFactory(review=review)
    )
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
                "parameter_extraction_row_pdf_metadata",
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
        "parameter_extraction_row_details",
        "parameter_extraction_row_process",
        "parameter_extraction_row_pdf",
        "parameter_extraction_row_pdf_metadata",
        "parameter_extraction_validate_ai_answer",
        "parameter_extraction_human_answer",
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
    parameter = ParameterFactory(
        category=ParameterCategoryFactory(review=review)
    )
    result = ParameterExtractionResultFactory(
        citation=row,
        question=parameter,
    )

    with patch_rules(can_access_review=False):
        if url_name in (
            "parameter_extraction_validate_ai_answer",
            "parameter_extraction_human_answer",
        ):
            url = reverse(url_name, args=[review.id, result.id])
        else:
            url = reverse(url_name, args=[review.id, row.id])

        if url_name in (
            "parameter_extraction_row_process",
            "parameter_extraction_validate_ai_answer",
        ):
            response = vanilla_client.post(url)
        else:
            response = vanilla_client.get(url)

    assert response.status_code == 403
