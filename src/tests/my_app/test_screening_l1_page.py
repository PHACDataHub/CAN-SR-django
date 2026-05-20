from django.urls import reverse

from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationDatasetRowFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningResultFactory,
    SystematicReviewFactory,
)
from my_app.models import L1ScreeningResult, ScreeningResultStatus


def test_screening_l1_shell_renders_component_and_refresh_button(
    vanilla_client,
):
    review = SystematicReviewFactory()
    dataset = CitationDatasetFactory(systematic_review=review)
    question = L1ScreeningQuestionFactory(review=review)
    row = CitationDatasetRowFactory(dataset=dataset, order=1)
    L1ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.COMPLETED,
    )

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_client.get(
            reverse("screening_l1", args=[review.id]), {"page": 1}
        )

    body = response.content.decode()
    shell_url = reverse("screening_l1", args=[review.id])

    assert response.status_code == 200
    assert "L1 Screening" in body
    assert reverse("screening_l1_component", args=[review.id]) in body
    assert 'hx-target="#l1-screening-component"' in body
    assert 'hx-swap="outerHTML"' in body
    assert "Completed" in body


def test_screening_l1_component_view_renders(vanilla_client):
    review = SystematicReviewFactory()
    dataset = CitationDatasetFactory(systematic_review=review)
    question = L1ScreeningQuestionFactory(review=review)
    row = CitationDatasetRowFactory(dataset=dataset, order=1)
    L1ScreeningResultFactory(
        citation=row,
        question=question,
        status=ScreeningResultStatus.PENDING,
    )

    with patch_rules(can_access_systematic_review=True):
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
    review = SystematicReviewFactory()
    dataset = CitationDatasetFactory(systematic_review=review)
    question = L1ScreeningQuestionFactory(review=review)
    for order in range(1, 12):
        row = CitationDatasetRowFactory(dataset=dataset, order=order)
        L1ScreeningResultFactory(
            citation=row,
            question=question,
            status=ScreeningResultStatus.COMPLETED,
        )

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_client.get(
            reverse("screening_l1_component", args=[review.id]),
            {"page": 1},
        )

    body = response.content.decode()
    component_url = reverse("screening_l1_component", args=[review.id])
    shell_url = reverse("screening_l1", args=[review.id])

    assert response.status_code == 200
    assert f"{component_url}?page=2" in body
    assert "Next" in body


def test_screen_l1_row_view_starts_screening_and_returns_status(
    vanilla_client,
):
    review = SystematicReviewFactory()
    dataset = CitationDatasetFactory(systematic_review=review)
    question1 = L1ScreeningQuestionFactory(review=review)
    question2 = L1ScreeningQuestionFactory(review=review)
    row = CitationDatasetRowFactory(dataset=dataset, order=1)

    with patch_rules(can_access_systematic_review=True):
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
