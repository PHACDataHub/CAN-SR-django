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


@pytest.fixture(params=["l1", "l2"])
def stage(request):
    return request.param


def statistics_url(stage, review):
    if stage == "l1":
        return reverse("l1_screening_statistics", args=[review.id])
    return reverse("l2_screening_statistics", args=[review.id])


def metric_details(section):
    return {
        item.dt.get_text(): item.dd.get_text()
        for item in section.select("dl > div")
    }


def test_statistics_modal_shows_stage_metrics_for_active_questions(
    vanilla_client, stage
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    citations = CitationFactory.create_batch(6, dataset=dataset)
    if stage == "l1":
        question_factory = L1ScreeningQuestionFactory
        option_factory = L1ScreeningQuestionOptionFactory
        result_factory = L1ScreeningResultFactory
        answer_factory = L1HumanAnswerFactory
    else:
        question_factory = L2ScreeningQuestionFactory
        option_factory = L2ScreeningQuestionOptionFactory
        result_factory = L2ScreeningResultFactory
        answer_factory = L2HumanAnswerFactory
        gate = L1ScreeningQuestionFactory(
            review=review, question_text="Other stage question"
        )
        gate_in = L1ScreeningQuestionOptionFactory(
            question=gate, screening_action=ScreeningActions.ScreenIn
        )
        for citation in citations[:5]:
            L1HumanAnswerFactory(
                citation=citation, question=gate, selected_option=gate_in
            )

    question = question_factory(review=review, question_text="First question")
    empty = question_factory(
        review=review, question_text="Unanswered question"
    )
    question_factory(
        review=review,
        question_text="Disabled question",
        disable_screening=True,
    )
    deleted = question_factory(review=review, question_text="Deleted question")
    deleted.soft_delete()
    question_factory(question_text="Another review question")
    included = option_factory(
        question=question, screening_action=ScreeningActions.ScreenIn
    )
    excluded = option_factory(
        question=question, screening_action=ScreeningActions.ScreenOut
    )
    for citation, ai, human in zip(
        citations,
        [included, included, excluded, excluded, None, excluded],
        [included, excluded, included, excluded, None, excluded],
    ):
        if ai is not None:
            result_factory(
                citation=citation,
                question=question,
                selected_option=ai,
                status=ScreeningResultStatus.COMPLETED,
            )
            answer_factory(
                citation=citation, question=question, selected_option=human
            )

    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            statistics_url(stage, review),
            {"search": "No matching citations", "screening": "out"},
        )
    assert response.status_code == 200
    soup = soup_from_str(response.content)
    modal = soup.select_one("[data-modal]")
    assert "modal-xl" in modal["class"]
    assert modal["aria-labelledby"] == "screening-statistics-title"
    sections = modal.select("section[data-question-id]")
    assert [int(section["data-question-id"]) for section in sections] == [
        question.id,
        empty.id,
    ]
    body = modal.get_text()
    for text in (
        "Other stage question",
        "Disabled question",
        "Deleted question",
        "Another review question",
    ):
        assert text not in body

    first = sections[0]
    expected_tn = 2
    expected_pairs = 5
    expected_total_missing = 7
    expected_accuracy = "60.0%"
    expected_npv = "66.7%"
    if stage == "l2":
        expected_tn = 1
        expected_pairs = 4
        expected_total_missing = 6
        expected_accuracy = "50.0%"
        expected_npv = "50.0%"
    cells = {
        cell.select_one(".small")
        .get_text(): cell.select_one(".fw-semibold")
        .get_text()
        for cell in first.select("tbody td")
    }
    assert cells == {
        "True positives": "1",
        "False positives": "1",
        "False negatives": "1",
        "True negatives": str(expected_tn),
    }
    assert metric_details(first) == {
        "Paired answers": str(expected_pairs),
        "Exact agreements": str(expected_pairs - 2),
        "Missing answer pairs": "1",
        "Accuracy (exact agreement)": expected_accuracy,
        "Precision": "50.0%",
        "Recall": "50.0%",
        "F1 score": "50.0%",
        "Negative predictive value": expected_npv,
    }
    overall = modal.select_one("section")
    assert metric_details(overall)["Missing answer pairs"] == str(
        expected_total_missing
    )
    assert metric_details(overall)["Paired answers"] == str(expected_pairs)
    assert metric_details(sections[1])["Precision"] == "Not available"


def test_statistics_modal_empty_review_and_access_control(
    vanilla_client, stage
):
    review = ReviewFactory()
    url = statistics_url(stage, review)
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
    assert response.status_code == 200
    soup = soup_from_str(response.content)
    assert "No screening questions." in soup.get_text()
    assert metric_details(soup.select_one("section"))["Paired answers"] == "0"
    assert (
        metric_details(soup.select_one("section"))[
            "Accuracy (exact agreement)"
        ]
        == "Not available"
    )
