from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    L2ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import ScreeningActions, ScreeningResultStatus
from tests.utils_for_testing import soup_from_str

pytestmark = pytest.mark.view


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("stage", ["l1", "l2", "parameter_extraction"])
def test_progress_panel_counts_all_review_citations_and_stage_statuses(
    vanilla_client, stage, partial
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    included = CitationFactory(dataset=dataset, title="Included citation")
    excluded = CitationFactory(dataset=dataset, title="Excluded citation")
    CitationFactory(dataset=dataset, title="Unanswered citation")
    CitationFactory()  # Another review must not affect the totals.

    for question_factory, option_factory, answer_factory, result_factory in (
        (
            L1ScreeningQuestionFactory,
            L1ScreeningQuestionOptionFactory,
            L1HumanAnswerFactory,
            L1ScreeningResultFactory,
        ),
        (
            L2ScreeningQuestionFactory,
            L2ScreeningQuestionOptionFactory,
            L2HumanAnswerFactory,
            L2ScreeningResultFactory,
        ),
    ):
        question = question_factory(review=review)
        question_factory(review=review, disable_screening=True)
        deleted = question_factory(review=review)
        deleted.soft_delete()
        screen_in = option_factory(
            question=question, screening_action=ScreeningActions.ScreenIn
        )
        screen_out = option_factory(
            question=question, screening_action=ScreeningActions.ScreenOut
        )
        answer_factory(
            citation=included, question=question, selected_option=screen_in
        )
        result_factory(
            citation=included,
            question=question,
            selected_option=screen_in,
            status=ScreeningResultStatus.COMPLETED,
            confidence=0,
        )
        option = screen_in
        if question_factory == L2ScreeningQuestionFactory:
            option = screen_out
        answer_factory(
            citation=excluded, question=question, selected_option=option
        )

    if stage == "l1":
        if partial:
            url = reverse("l1_citations_list_partial", args=[review.id])
        else:
            url = reverse("l1_citations_list", args=[review.id])
    elif stage == "l2":
        if partial:
            url = reverse("l2_citations_list_partial", args=[review.id])
        else:
            url = reverse("l2_citations_list", args=[review.id])
    elif partial:
        url = reverse(
            "parameter_extraction_citations_list_partial", args=[review.id]
        )
    else:
        url = reverse("parameter_extraction_citations_list", args=[review.id])
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url, {"search": "Included citation"})

    assert response.status_code == 200
    panel_id = f"{stage}-screening-progress-panel"
    if stage == "parameter_extraction":
        panel_id = "parameter-extraction-progress-panel"
    panel = soup_from_str(response.content).find(id=panel_id)
    metrics = {
        label.get_text(): value.get_text()
        for label, value in zip(panel.select("dt"), panel.select("dd"))
    }
    assert metrics["Total citations"] == "3"
    assert not panel.select('[role="progressbar"]')
    if stage != "l1":
        assert metrics["Screened-in citations from L1"] == "2"
    if stage == "parameter_extraction":
        assert metrics["Screened-in citations from L2"] == "1"
        assert len(metrics) == 3
        assert not panel.select("table")
        return

    assert metrics["Screening questions"] == "1"
    tables = {
        table.caption.get_text(): {
            row.th.get_text(): row.td.get_text()
            for row in table.select("tbody tr")
        }
        for table in panel.select("table")
    }
    total = 3
    human_counts = {"In": "2", "Out": "0", "Unanswered": "1"}
    if stage == "l2":
        total = 2
        human_counts = {"In": "1", "Out": "1", "Unanswered": "0"}
    assert tables["AI status"] == {
        "Not screened yet": str(total - 1),
        "Auto excluded": "0",
        "Confidently included": "0",
        "Ambiguously included": "1",
    }
    assert tables["Human status"] == human_counts
    assert tables["Overall screening status"] == {
        **human_counts,
        "Ambiguous": "0",
    }
