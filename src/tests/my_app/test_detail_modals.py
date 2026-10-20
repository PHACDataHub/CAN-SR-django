from django.urls import reverse

import pytest
from bs4 import BeautifulSoup
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    ParameterExtractionResultFactory,
    ParameterFactory,
    ParameterHumanAnswerFactory,
)
from tests.detail_modal_cases import ANSWER_CASES, create_answer_case

pytestmark = pytest.mark.view


@pytest.mark.parametrize("stage", ["l1", "l2"])
@pytest.mark.parametrize("case", ANSWER_CASES)
def test_answer_modal_states(vanilla_client, stage, case):
    data = create_answer_case(stage, case)
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                f"{stage}_answer_detail_modal",
                args=[data.citation.pk, data.question.pk],
            )
        )
    assert response.status_code == 200
    text = BeautifulSoup(response.content, "html.parser").get_text(
        " ", strip=True
    )
    assert data.citation.title in text
    assert data.question.question_text in text
    assert "Confidence threshold" in text
    if case in {"neither", "human-only"}:
        assert "No AI answer yet." in text
    if case in {
        "neither",
        "ai-only",
        "pending",
        "error",
        "critical-disagreement",
        "critical-pending",
        "critical-error",
    }:
        assert "No human answers yet." in text
    if case == "agreement":
        assert "AI and human answers agree" in text
    if case in {"disagreement", "multiple-humans"}:
        assert "AI and human answers disagree" in text
    if case == "multiple-humans":
        assert "Alex Smith" in text and "Blair Chen" in text
        assert text.index("Blair Chen") < text.index("Alex Smith")
    if case == "pending":
        assert "AI answer is pending." in text
    if case == "error":
        assert "UnexpectedLLMOutputError" in text
        assert "Abandoned" in text
    if case == "critical-disagreement":
        assert "Critical agent disagrees" in text
    if case == "critical-pending":
        assert "Critical agent review is loading." in text
    if case == "critical-error":
        assert "Critical agent review could not be completed." in text
        assert "UnexpectedLLMOutputError" in text
    if stage == "l2" and data.result:
        assert "Participants were adults living in Canada." in text
        assert "Evidence tables" in text and "Evidence figures" in text


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("L1", "l1"),
        ("L2", "l2"),
        ("parameters", "parameters"),
        ("invalid", "l1"),
        (None, "l1"),
    ],
)
def test_citation_modal_stage_and_details(vanilla_client, stage, expected):
    data = create_answer_case("l1", "multiple-humans")
    parameter = ParameterFactory(review=data.review, name="Study setting")
    ParameterExtractionResultFactory(
        citation=data.citation,
        question=parameter,
        status="completed",
        found=True,
        value="Community clinics",
    )
    ParameterHumanAnswerFactory(
        citation=data.citation,
        question=parameter,
        found=True,
        value="Primary care clinics",
        notes="Confirmed from methods.",
    )
    params = {}
    if stage:
        params["stage"] = stage
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("citation_detail_modal", args=[data.citation.pk]), params
        )
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert [
        section["data-detail-stage"]
        for section in soup.select("details[data-detail-stage][open]")
    ] == [expected]
    text = soup.get_text(" ", strip=True)
    assert data.citation.title in text and data.citation.abstract in text
    assert text.index("Population") < text.index("Authors")
    assert "Community clinics" in text and "Primary care clinics" in text
    assert "Screening status" in text
    assert "AI extraction completed: 1 / 1" in text
    assert soup.select_one(
        f'button[hx-get="{reverse("l1_answer_detail_modal", args=[data.citation.pk, data.question.pk])}?size=lg"]'
    )


def test_citation_modal_batches_question_answers(
    vanilla_client, django_assert_num_queries
):
    data = create_answer_case("l1", "agreement")
    url = reverse("citation_detail_modal", args=[data.citation.pk])
    with patch_rules(can_access_review=True):
        with django_assert_num_queries(16):
            vanilla_client.get(url)
        for _ in range(5):
            question = L1ScreeningQuestionFactory(review=data.review)
            L1HumanAnswerFactory(citation=data.citation, question=question)
        with django_assert_num_queries(16):
            vanilla_client.get(url)


@pytest.mark.parametrize("stage", ["l1", "l2"])
@pytest.mark.parametrize("disabled", [False, True])
def test_selected_option_summaries_and_stage_links(
    vanilla_client, stage, disabled
):
    data = create_answer_case(stage, "multiple-humans")
    data.question.disable_screening = disabled
    data.question.save()
    with patch_rules(can_access_review=True):
        citation_response = vanilla_client.get(
            reverse("citation_detail_modal", args=[data.citation.pk])
        )
        answer_response = vanilla_client.get(
            reverse(
                f"{stage}_answer_detail_modal",
                args=[data.citation.pk, data.question.pk],
            )
        )
    citation_soup = BeautifulSoup(citation_response.content, "html.parser")
    answer_soup = BeautifulSoup(answer_response.content, "html.parser")
    definitions = answer_soup.select_one("details")
    assert "Includes Canadian adults" in definitions.get_text()
    assert "Population outside the review scope" in definitions.get_text()
    definitions.extract()
    for soup in (citation_soup, answer_soup):
        assert "Includes Canadian adults" not in soup.get_text()
        assert "Population outside the review scope" not in soup.get_text()
        link = soup.select_one(
            f'a[href="{reverse(f"{stage}_citation_detail", args=[data.review.pk, data.citation.pk])}"]'
        )
        assert link["target"] == "_blank"
        assert "noopener" in link["rel"]
        assert link.select_one('svg[aria-hidden="true"]')
        assert "opens in a new tab" in link.get_text()
    summary = citation_soup.select_one(
        f'details[data-detail-stage="{stage}"] article'
    )
    if disabled:
        assert "Screening disabled" in summary.get_text()
    else:
        assert "Exclude" in summary.get_text()
        assert "Include" in answer_soup.get_text()


@pytest.mark.parametrize(
    "route",
    [
        "citation_detail_modal",
        "l1_answer_detail_modal",
        "l2_answer_detail_modal",
    ],
)
@pytest.mark.parametrize(
    "size,expected",
    [
        (None, "xl"),
        ("xl", "xl"),
        ("lg", "lg"),
        ("md", "md"),
        ("sm", "sm"),
        ("invalid", "xl"),
    ],
)
def test_modal_sizes(vanilla_client, route, size, expected):
    stage = "l1"
    if route == "l2_answer_detail_modal":
        stage = "l2"
    data = create_answer_case(stage, "neither")
    args = [data.citation.pk]
    if route != "citation_detail_modal":
        args.append(data.question.pk)
    params = {}
    if size is not None:
        params["size"] = size
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(reverse(route, args=args), params)
    soup = BeautifulSoup(response.content, "html.parser")
    assert f"modal-{expected}" in soup.select_one("[data-modal]")["class"]
    modal_buttons = soup.select("button[hx-get]")
    if expected != "xl":
        assert not modal_buttons
    elif route == "citation_detail_modal":
        assert modal_buttons
    else:
        button = soup.select_one("button[hx-get]")
        assert button["hx-get"] == (
            reverse("citation_detail_modal", args=[data.citation.pk])
            + f"?stage={stage}&size=lg"
        )
        assert soup.select_one(button["hx-target"]).has_attr("data-modal-slot")


@pytest.mark.parametrize("stage", ["l1", "l2"])
@pytest.mark.parametrize("disabled", [False, True])
def test_citation_pages_show_compact_answers_and_detail_links(
    vanilla_client, stage, disabled
):
    data = create_answer_case(stage, "multiple-humans")
    data.question.disable_screening = disabled
    data.question.save()
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                f"{stage}_citation_detail",
                args=[data.review.pk, data.citation.pk],
            )
        )
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    control = soup.select_one(
        f"#{stage}-question-panel-{data.citation.pk}-{data.question.pk}"
    )
    text = control.get_text(" ", strip=True)
    assert "Includes Canadian adults" not in text
    assert "Population outside the review scope" not in text
    assert "Exclude" in text
    assert control.select_one(".badge").get_text() == "Human"
    assert "Controversial" in text
    if disabled:
        assert text.count("Screening disabled") == 1
    else:
        assert text.count("Exclude") == 2
    url = reverse(
        f"{stage}_answer_detail_modal",
        args=[data.citation.pk, data.question.pk],
    )
    links = control.select(f'button[hx-get="{url}"]')
    assert len(links) == 1
    assert all(link["hx-target"] == "#modal-slot" for link in links)
    assert all(link.get_text(strip=True) == "Answer details" for link in links)
