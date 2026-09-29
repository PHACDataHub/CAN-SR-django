"""The initial result controls whether a critical review is shown."""

from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import (
    L1CriticalScreeningResult,
    L2CriticalScreeningResult,
    ScreeningResultStatus,
)

pytestmark = pytest.mark.view


def _result_for_level(level, initial_status):
    review = ReviewFactory()
    citation = CitationFactory(dataset=CitationDatasetFactory(review=review))
    if level == 1:
        question = L1ScreeningQuestionFactory(review=review)
        selected = L1ScreeningQuestionOptionFactory(question=question)
        result = L1ScreeningResultFactory(
            citation=citation,
            question=question,
            selected_option=selected,
            status=initial_status,
        )
        critical_model = L1CriticalScreeningResult
    else:
        question = L2ScreeningQuestionFactory(review=review)
        selected = L2ScreeningQuestionOptionFactory(question=question)
        result = L2ScreeningResultFactory(
            citation=citation,
            question=question,
            selected_option=selected,
            status=initial_status,
        )
        critical_model = L2CriticalScreeningResult
    return review, citation, result, critical_model


@pytest.mark.parametrize("level", [1, 2])
def test_critical_review_waits_for_initial_success(vanilla_client, level):
    review, citation, result, critical_model = _result_for_level(
        level, ScreeningResultStatus.PENDING
    )
    critical_model.objects.create(
        initial_result=result,
        status=ScreeningResultStatus.COMPLETED,
        confidence=0.91,
    )
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(f"l{level}_citation_detail", args=[review.id, citation.id])
        )
    assert response.status_code == 200
    assert "Critical agent review" not in response.content.decode()


@pytest.mark.parametrize("level", [1, 2])
def test_old_completed_result_without_critical_review_has_no_placeholder(
    vanilla_client, level
):
    review, citation, _, _ = _result_for_level(
        level, ScreeningResultStatus.COMPLETED
    )
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(f"l{level}_citation_detail", args=[review.id, citation.id])
        )
    assert response.status_code == 200
    assert "Critical agent review" not in response.content.decode()
