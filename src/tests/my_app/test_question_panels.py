from django.urls import reverse

import pytest
from bs4 import BeautifulSoup
from phac_aspc.rules import patch_rules

from my_app import models
from tests.detail_modal_cases import panel_case

STAGES = ("l1", "l2", "parameters")
PAGE_ROUTES = {
    "l1": "l1_citation_detail",
    "l2": "l2_citation_detail",
    "parameters": "parameter_extraction_citation_detail",
}
FORM_ROUTES = {
    "l1": "l1_question_human_answer",
    "l2": "l2_question_human_answer",
    "parameters": "parameter_question_human_answer",
}
RESULT_MODELS = {
    "l1": models.L1ScreeningResult,
    "l2": models.L2ScreeningResult,
    "parameters": models.ParameterExtractionResult,
}
ANSWER_MODELS = {
    "l1": models.L1HumanAnswer,
    "l2": models.L2HumanAnswer,
    "parameters": models.ParameterHumanAnswer,
}


def get_panel(client, stage, data):
    with patch_rules(can_access_review=True):
        response = client.get(
            reverse(
                PAGE_ROUTES[stage], args=[data.review.pk, data.citation.pk]
            )
        )
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    return soup.select_one(
        f'.question-panel[data-question-id="{data.question.pk}"]'
    )


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize(
    "case",
    [
        "neither",
        "human-only",
        "ai-only",
        "agreement",
        "disagreement",
        "multiple-humans",
        "pending",
        "error",
    ],
)
def test_question_panel_summary_and_expansion(vanilla_client, stage, case):
    data = panel_case(stage, case)
    panel = get_panel(vanilla_client, stage, data)
    assert panel is not None
    summary = panel.select_one(":scope > dl")
    assert [label.get_text(strip=True) for label in summary.select("dt")] == [
        "Question",
        "Status",
        "Answer",
    ]
    values = summary.select("dd")
    if case in {"human-only", "agreement", "disagreement", "multiple-humans"}:
        assert values[2].select_one(".badge").get_text() == "Human"
        latest = (
            ANSWER_MODELS[stage]
            .objects.filter(citation=data.citation, question=data.question)
            .order_by("-updated_at", "-pk")
            .first()
        )
        if stage == "parameters":
            expected = latest.value
        else:
            expected = latest.selected_option.option_text
        assert expected in values[2].get_text()
    elif case in {"ai-only"}:
        assert values[2].select_one(".badge").get_text() == "AI"
    else:
        assert "No answer yet" in values[2].get_text()
    if case in {"disagreement", "multiple-humans"}:
        assert values[1].get_text() == "Controversial"
    details = panel.select_one(":scope > details")
    assert details.has_attr("open") == (
        case in {"disagreement", "multiple-humans", "error"}
    )
    assert details.select_one(":scope > dl.custom-dl")
    form_url = reverse(
        FORM_ROUTES[stage],
        args=[data.review.pk, data.citation.pk, data.question.pk],
    )
    assert panel.select_one(f'button[hx-get="{form_url}"]')
    detail_links = panel.select('button[hx-get*="/details/"]')
    assert len(detail_links) == 1
    assert details.select_one('button[hx-get*="/details/"]')
    assert "Includes Canadian adults" not in panel.get_text()


@pytest.mark.parametrize("stage", ("l1", "l2"))
@pytest.mark.parametrize(
    "case", ["critical-disagreement", "critical-error", "critical-pending"]
)
def test_question_panel_critical_review_expansion(vanilla_client, stage, case):
    data = panel_case(stage, case)
    panel = get_panel(vanilla_client, stage, data)
    assert panel.select_one(":scope > details").has_attr("open") == (
        case != "critical-pending"
    )
    assert "Critical agent review" in panel.get_text()


@pytest.mark.parametrize("stage", STAGES)
def test_human_answer_without_ai_and_after_ai_restart(
    vanilla_client, vanilla_user, stage
):
    data = panel_case(stage, "neither")
    url = reverse(
        FORM_ROUTES[stage],
        args=[data.review.pk, data.citation.pk, data.question.pk],
    )
    if stage == "parameters":
        payload = {
            "found": "True",
            "value": "Community clinics",
            "notes": "Manual review",
        }
    else:
        option = data.question.options.first()
        payload = {"selected_option": option.pk, "notes": "Manual review"}
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
    with patch_rules(can_access_review=True):
        form_response = vanilla_client.get(url)
        assert form_response.status_code == 200
        modal_body = BeautifulSoup(
            form_response.content, "html.parser"
        ).select_one(".modal-body")
        assert modal_body.find("h2").get_text() == data.question.title
        assert modal_body.find("h2").find_next_sibling("form") is not None
        assert (
            not RESULT_MODELS[stage]
            .objects.filter(citation=data.citation)
            .exists()
        )
        response = vanilla_client.post(url, payload)
    assert response.status_code == 200
    assert (
        not RESULT_MODELS[stage]
        .objects.filter(citation=data.citation)
        .exists()
    )
    answer = ANSWER_MODELS[stage].objects.get(citation=data.citation)
    assert answer.user == vanilla_user and answer.notes == "Manual review"
    assert (
        response["HX-Retarget"]
        == f"#{stage}-question-panel-{data.citation.pk}-{data.question.pk}"
    )
    panel = get_panel(vanilla_client, stage, data)
    assert panel.select_one(".badge").get_text() == "Human"
    assert "Edit your answer" in panel.get_text()
    # An open human form must survive an AI result being replaced or removed.
    RESULT_MODELS[stage].objects.create(
        citation=data.citation, question=data.question
    )
    with patch_rules(can_access_review=True):
        assert vanilla_client.get(url).status_code == 200
    RESULT_MODELS[stage].objects.filter(citation=data.citation).delete()
    payload["notes"] = "Updated manual review"
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(url, payload)
    assert response.status_code == 200
    assert (
        ANSWER_MODELS[stage].objects.filter(citation=data.citation).count()
        == 1
    )
    answer.refresh_from_db()
    assert answer.notes == "Updated manual review"


@pytest.mark.parametrize("stage", STAGES)
def test_question_form_rejects_other_reviews_deleted_questions_and_invalid_options(
    vanilla_client, stage
):
    data = panel_case(stage, "neither")
    other = panel_case(stage, "neither")
    with patch_rules(can_access_review=True):
        url = reverse(
            FORM_ROUTES[stage],
            args=[data.review.pk, data.citation.pk, other.question.pk],
        )
        assert vanilla_client.get(url).status_code == 404
        url = reverse(
            FORM_ROUTES[stage],
            args=[data.review.pk, other.citation.pk, data.question.pk],
        )
        assert vanilla_client.get(url).status_code == 404
        url = reverse(
            FORM_ROUTES[stage],
            args=[data.review.pk, data.citation.pk, data.question.pk],
        )
        if stage != "parameters":
            response = vanilla_client.post(
                url, {"selected_option": other.question.options.first().pk}
            )
            assert response.status_code == 200
            assert "Select a valid choice" in response.content.decode()
            assert (
                not ANSWER_MODELS[stage]
                .objects.filter(citation=data.citation)
                .exists()
            )
        data.question.soft_delete()
        assert vanilla_client.get(url).status_code == 404
    assert get_panel(vanilla_client, stage, data) is None


@pytest.mark.parametrize("stage", STAGES)
def test_question_loading_is_batched(vanilla_client, stage):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from my_app.model_factories import (
        L1ScreeningQuestionFactory,
        L2ScreeningQuestionFactory,
        ParameterFactory,
    )

    data = panel_case(stage, "neither")
    with CaptureQueriesContext(connection) as initial:
        assert get_panel(vanilla_client, stage, data) is not None
    factory = {
        "l1": L1ScreeningQuestionFactory,
        "l2": L2ScreeningQuestionFactory,
        "parameters": ParameterFactory,
    }[stage]
    extra = factory.create_batch(5, review=data.review)
    with CaptureQueriesContext(connection) as expanded:
        assert get_panel(vanilla_client, stage, data) is not None
    assert len(expanded) == len(initial)
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                PAGE_ROUTES[stage], args=[data.review.pk, data.citation.pk]
            )
        )
    assert (
        len(
            BeautifulSoup(response.content, "html.parser").select(
                ".question-panel"
            )
        )
        == len(extra) + 1
    )


@pytest.mark.parametrize("stage", STAGES)
def test_human_answer_wins_over_pending_or_failed_ai(vanilla_client, stage):
    data = panel_case(stage, "human-only")
    for status in ("pending", "abandoned"):
        RESULT_MODELS[stage].objects.update_or_create(
            citation=data.citation,
            question=data.question,
            defaults={"status": status},
        )
        panel = get_panel(vanilla_client, stage, data)
        assert panel.select_one(".badge").get_text() == "Human"
        assert panel.select_one(":scope > details").has_attr("open") == (
            status == "abandoned"
        )
        assert not panel.select("button[hx-post]")


def test_parameter_option_form_without_ai(vanilla_client):
    from my_app.model_factories import ParameterOptionFactory

    data = panel_case("parameters", "neither")
    data.question.option_type = models.Parameter.OptionType.SELECT
    data.question.save()
    valid = ParameterOptionFactory(
        parameter=data.question, name="Community clinics"
    )
    foreign = ParameterOptionFactory()
    deleted = ParameterOptionFactory(parameter=data.question)
    deleted.soft_delete()
    url = reverse(
        FORM_ROUTES["parameters"],
        args=[data.review.pk, data.citation.pk, data.question.pk],
    )
    with patch_rules(can_access_review=True):
        for option in (foreign, deleted):
            response = vanilla_client.post(
                url, {"found": "True", "selected_option": option.pk}
            )
            assert "Select a valid choice" in response.content.decode()
            assert not models.ParameterHumanAnswer.objects.filter(
                citation=data.citation
            ).exists()
        response = vanilla_client.post(
            url, {"found": "True", "selected_option": valid.pk}
        )
    assert response.status_code == 200
    assert (
        models.ParameterHumanAnswer.objects.get(
            citation=data.citation
        ).selected_option
        == valid
    )
    assert not models.ParameterExtractionResult.objects.filter(
        citation=data.citation
    ).exists()


def test_parameter_answer_modal_access_and_human_only(vanilla_client):
    data = panel_case("parameters", "human-only")
    url = reverse(
        "parameter_answer_detail_modal",
        args=[data.citation.pk, data.question.pk],
    )
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
        other = panel_case("parameters", "neither")
        assert (
            vanilla_client.get(
                reverse(
                    "parameter_answer_detail_modal",
                    args=[data.citation.pk, other.question.pk],
                )
            ).status_code
            == 404
        )
    assert response.status_code == 200
    assert b"No AI answer yet" in response.content
    assert b"Community clinics" in response.content


@pytest.mark.parametrize("stage", STAGES)
def test_ai_confidence_and_missing_selection(vanilla_client, stage):
    data = panel_case(stage, "ai-only")
    panel = get_panel(vanilla_client, stage, data)
    status = panel.select_one(":scope > dl").select("dd")[1].get_text()
    assert status == ("Completed" if stage == "parameters" else "Included")
    data.result.confidence = 0.3
    data.result.save()
    panel = get_panel(vanilla_client, stage, data)
    assert (
        panel.select_one(":scope > dl").select("dd")[1].get_text()
        == "Needs human review"
    )
    if stage != "parameters":
        data.result.selected_option = None
        data.result.save()
        panel = get_panel(vanilla_client, stage, data)
        assert "No answer yet" in panel.get_text()
        assert (
            panel.select_one(":scope > dl").select("dd")[1].get_text()
            == "Needs human review"
        )


@pytest.mark.parametrize("stage", STAGES)
def test_pending_ai_cannot_be_validated(vanilla_client, stage):
    data = panel_case(stage, "pending")
    route = {
        "l1": "l1_citation_validate_correct",
        "l2": "l2_citation_validate_correct",
        "parameters": "parameter_extraction_citation_validate_ai_answer",
    }[stage]
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse(route, args=[data.review.pk, data.result.pk])
        )
    assert response.status_code == 200
    assert (
        not ANSWER_MODELS[stage]
        .objects.filter(citation=data.citation)
        .exists()
    )


@pytest.mark.parametrize("stage", STAGES)
def test_human_only_answers_count_as_reviewed(vanilla_client, stage):
    data = panel_case(stage, "human-only")
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                PAGE_ROUTES[stage], args=[data.review.pk, data.citation.pk]
            )
        )
    progress = BeautifulSoup(response.content, "html.parser").select_one(
        '[role="progressbar"]'
    )
    assert progress["aria-valuenow"] == "100"
    assert (
        not RESULT_MODELS[stage]
        .objects.filter(citation=data.citation)
        .exists()
    )


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("case", ["human-only", "ai-only"])
def test_deleted_questions_with_answers_remain_read_only(
    vanilla_client, stage, case
):
    data = panel_case(stage, case)
    data.question.soft_delete()
    panel = get_panel(vanilla_client, stage, data)
    assert panel is not None
    summary = panel.select_one(":scope > dl")
    assert data.question.title in summary.get_text()
    assert "Deleted question" in summary.get_text()
    assert summary.select_one(".badge") is None
    assert not panel.select(
        'button[hx-get*="/human-answer/"], button[hx-post]'
    )
    details = panel.select_one(":scope > details")
    if case == "human-only":
        answer = ANSWER_MODELS[stage].objects.get(citation=data.citation)
        assert "Historical human answer" in details.get_text()
        assert answer.user.get_username() in details.get_text()
    else:
        assert "Historical AI answer" in details.get_text()
    assert len(panel.select('button[hx-get*="/details/"]')) == 1


@pytest.mark.parametrize("stage", STAGES)
def test_deleted_human_option_is_visible_but_does_not_override_valid_ai(
    vanilla_client, stage
):
    data = panel_case(stage, "disagreement")
    human = ANSWER_MODELS[stage].objects.get(citation=data.citation)
    if stage == "parameters":
        from my_app.model_factories import ParameterOptionFactory

        data.question.option_type = models.Parameter.OptionType.SELECT
        data.question.save()
        data.result.selected_option = ParameterOptionFactory(
            parameter=data.question, name="Current setting"
        )
        data.result.save()
        human.selected_option = ParameterOptionFactory(
            parameter=data.question, name="Historical setting"
        )
        human.save()
    historical_label = str(human.selected_option)
    human.selected_option.soft_delete()
    panel = get_panel(vanilla_client, stage, data)
    summary = panel.select_one(":scope > dl")
    assert summary.select_one(".badge").get_text() == "AI"
    assert "Controversial" not in summary.get_text()
    assert historical_label not in summary.get_text()
    details = panel.select_one(":scope > details")
    assert historical_label in details.get_text()
    assert "Deleted option" in details.get_text()
    assert human.user.get_username() in details.get_text()
    assert panel.select_one('button[hx-get*="/human-answer/"]')
