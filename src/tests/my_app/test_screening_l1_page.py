from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetColumnFactory,
    CitationDatasetFactory,
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import L1ScreeningResult, ScreeningResultStatus

pytestmark = [pytest.mark.view, pytest.mark.l1_screening]


def test_screening_l1_shell_renders_component_and_refresh_button(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L1ScreeningQuestionFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    L1ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l1", args=[review.id]), {"page": 1}
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "L1 Screening" in body
    assert reverse("screening_l1_component", args=[review.id]) in body
    assert 'hx-target="#l1-screening-component"' in body
    assert 'hx-swap="outerHTML"' in body
    assert "Completed" in body


def test_screening_l1_component_view_renders(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L1ScreeningQuestionFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    L1ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l1_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert "l1-screening-component" in body
    assert "l1-screening-progress-panel" in body
    assert "Progress" in body
    assert "Pending" in body


def test_screening_l1_component_view_renders_pagination_buttons(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = L1ScreeningQuestionFactory(review=review)
    for order in range(1, 12):
        row = CitationFactory(dataset=dataset, order=order)
        L1ScreeningResultFactory(
            citation=row,
            question=question,
            status=ScreeningResultStatus.COMPLETED,
        )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l1_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()
    component_url = reverse("screening_l1_component", args=[review.id])

    assert response.status_code == 200
    assert f"{component_url}?page=2" in body
    assert "Next" in body


def test_screening_l1_component_view_renders_row_details_link(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    L1ScreeningQuestionFactory(review=review)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screening_l1_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()
    details_url = reverse("screen_l1_row_details", args=[review.id, row.id])

    assert response.status_code == 200
    assert details_url in body
    assert "View more" in body


def test_screen_l1_row_view_starts_screening_and_returns_status(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question1 = L1ScreeningQuestionFactory(review=review)
    question2 = L1ScreeningQuestionFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse("screen_l1_row", args=[review.id, row.id]),
            {"page": 1},
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert f"l1-screening-row-status-{row.id}" in body
    assert "Pending" in body
    assert (
        L1ScreeningResult.objects.filter(
            citation=row,
            question__in=[question1, question2],
            status=ScreeningResultStatus.PENDING,
        ).count()
        == 2
    )


def test_screen_l1_row_details_view_renders_modal_content(vanilla_client):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    included_column = CitationDatasetColumnFactory(
        dataset=dataset, name="Journal"
    )
    dataset.screening_columns.add(included_column)

    row = CitationFactory(
        dataset=dataset,
        order=1,
        title="A test citation",
        abstract="A test abstract",
        data={
            "Journal": "The BMJ",
            "Ignored": "Hidden value",
        },
    )
    question = L1ScreeningQuestionFactory(
        review=review,
        question_text="Is this citation relevant?",
    )
    selected_option = L1ScreeningQuestionOptionFactory(
        question=question,
        option_text="Include",
        option_value="Include this record",
    )
    L1ScreeningResultFactory(
        citation=row,
        question=question,
        selected_option=selected_option,
        status=ScreeningResultStatus.COMPLETED,
        explanation="Looks good.",
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l1_row_details", args=[review.id, row.id])
        )

    body = response.content.decode()

    assert response.status_code == 200
    assert 'id="l1-screening-details-modal-' in body
    assert "Screening details for" in body
    assert "Included fields" in body
    assert "A test citation" in body
    assert "A test abstract" in body
    assert "Journal" in body
    assert "The BMJ" in body
    assert "Non-included fields" in body
    assert "Ignored" in body
    assert "Hidden value" in body
    assert "L1 screening results" in body
    assert question.question_text in body
    assert selected_option.option_text in body
    assert selected_option.option_value in body
    assert "Looks good." in body
