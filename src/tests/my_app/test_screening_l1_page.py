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

    previous_row = CitationFactory(
        dataset=dataset,
        order=0,
        title="Previous citation",
    )
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
    next_row = CitationFactory(
        dataset=dataset,
        order=2,
        title="Next citation",
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
    assert "L1 citation screening" in body
    assert reverse("screening_l1", args=[review.id]) in body
    assert (
        reverse("screen_l1_row_details", args=[review.id, previous_row.id])
        in body
    )
    assert (
        reverse("screen_l1_row_details", args=[review.id, next_row.id]) in body
    )
    assert "Viewing 1 of 3" in body
    assert "Human reviewed" in body
    assert "0 / 3" in body
    assert "Included fields" in body
    assert "A test citation" in body
    assert "A test abstract" in body
    assert "Journal" in body
    assert "The BMJ" in body
    assert "Other fields" in body
    assert "Ignored" in body
    assert "Hidden value" in body
    assert "L1 screening results" in body
    assert question.question_text in body
    assert selected_option.option_text in body
    assert selected_option.option_value in body
    assert "Looks good." in body
    assert f'id="l1-citation-screening-control-{row.id}"' in body
    assert reverse("screen_l1_row_process", args=[review.id, row.id]) in body
    assert "Re-screen" in body
    assert "Validate correct" in body
    assert "Manually answer screening" in body


def test_screen_l1_row_details_view_renders_screening_process_button(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("screen_l1_row_details", args=[review.id, row.id])
        )

    body = response.content.decode()
    process_url = reverse("screen_l1_row_process", args=[review.id, row.id])

    assert response.status_code == 200
    assert f'id="l1-citation-screening-control-{row.id}"' in body
    assert f'hx-post="{process_url}"' in body
    assert 'hx-target="closest .l1-citation-screening-control"' in body
    assert 'hx-swap="outerHTML"' in body
    assert "Screen this citation" in body


def test_screen_l1_row_process_view_replaces_existing_screening_results(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset, order=1)
    question = L1ScreeningQuestionFactory(review=review)
    old_result = L1ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse("screen_l1_row_process", args=[review.id, row.id])
        )

    body = response.content.decode()
    result = L1ScreeningResult.objects.get(citation=row, question=question)

    assert response.status_code == 200
    assert f'id="l1-citation-screening-control-{row.id}"' in body
    assert "Pending" in body
    assert result.id != old_result.id
    assert result.status == ScreeningResultStatus.PENDING


def test_l1_human_validation_can_be_set_and_undone(
    vanilla_client, vanilla_user
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset)
    question = L1ScreeningQuestionFactory(review=review)
    selected_option = L1ScreeningQuestionOptionFactory(question=question)
    result = L1ScreeningResultFactory(
        citation=row,
        question=question,
        selected_option=selected_option,
    )

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse("screen_l1_validate_correct", args=[review.id, result.id])
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
            reverse("screen_l1_undo_validation", args=[review.id, result.id])
        )

    result.refresh_from_db()
    body = response.content.decode()
    assert response.status_code == 200
    assert result.human_validated_by is None
    assert result.human_validation_timestamp is None
    assert "Validate correct" in body
    assert "Manually answer screening" in body


def test_l1_human_answer_modal_saves_question_option_and_notes(
    vanilla_client,
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    row = CitationFactory(dataset=dataset)
    question = L1ScreeningQuestionFactory(review=review)
    answer = L1ScreeningQuestionOptionFactory(question=question)
    other_answer = L1ScreeningQuestionOptionFactory()
    result = L1ScreeningResultFactory(citation=row, question=question)
    url = reverse("screen_l1_human_answer", args=[review.id, result.id])

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
    assert "Human entered" in body
