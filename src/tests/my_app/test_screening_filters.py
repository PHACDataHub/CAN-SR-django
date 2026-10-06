from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

from django.urls import reverse

import pytest
from autocomplete import AutocompleteWidget
from phac_aspc.rules import patch_rules

from my_app.autocompletes import (
    CitationHumanStatusAutocomplete,
    CitationStatusAutocomplete,
)
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
from my_app.models import ScreeningActions
from tests.utils_for_testing import soup_from_str

pytestmark = pytest.mark.view


class ScreeningLayer(NamedTuple):
    stage: str
    question_factory: type
    option_factory: type
    answer_factory: type
    result_factory: type


@pytest.fixture(
    params=[
        ScreeningLayer(
            "l1",
            L1ScreeningQuestionFactory,
            L1ScreeningQuestionOptionFactory,
            L1HumanAnswerFactory,
            L1ScreeningResultFactory,
        ),
        ScreeningLayer(
            "l2",
            L2ScreeningQuestionFactory,
            L2ScreeningQuestionOptionFactory,
            L2HumanAnswerFactory,
            L2ScreeningResultFactory,
        ),
    ],
    ids=["L1", "L2"],
)
def layer(request):
    return request.param


def list_url(layer, review, partial=False):
    if layer.stage == "l1":
        if partial:
            return reverse("l1_citations_list_partial", args=[review.id])
        return reverse("l1_citations_list", args=[review.id])
    if partial:
        return reverse("l2_citations_list_partial", args=[review.id])
    return reverse("l2_citations_list", args=[review.id])


def page_ids(response):
    return [row.id for row in response.context_data["page_obj"]]


@pytest.fixture
def screening_rows(layer):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    question = layer.question_factory(review=review)
    included = CitationFactory(dataset=dataset, title="Included citation")
    excluded = CitationFactory(dataset=dataset, title="Excluded citation")
    undecided = CitationFactory(dataset=dataset, title="Undecided citation")
    not_started = CitationFactory(dataset=dataset, title="New citation")
    for row, action in [
        (included, ScreeningActions.ScreenIn),
        (excluded, ScreeningActions.ScreenOut),
    ]:
        layer.answer_factory(
            citation=row,
            question=question,
            selected_option=layer.option_factory(
                question=question, screening_action=action
            ),
        )
    layer.result_factory(citation=undecided, question=question)
    return review, [included, excluded, undecided, not_started]


@pytest.mark.parametrize(
    "statuses, indices",
    [
        ([], [0, 1, 2, 3]),
        (["in"], [0]),
        (["out"], [1]),
        (["ambiguous"], [2]),
        (["unanswered"], [3]),
        (["in", "out"], [0, 1]),
    ],
)
def test_screening_status_filters(
    vanilla_client, layer, screening_rows, statuses, indices
):
    review, rows = screening_rows
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            list_url(layer, review), {"screening": statuses, "page": 1}
        )
    assert response.status_code == 200
    assert set(page_ids(response)) == {rows[index].id for index in indices}
    form = soup_from_str(response.content).find("form", {"method": "get"})
    assert form.parent.name == "details"
    assert form.parent.has_attr("open") == bool(statuses)


@pytest.mark.parametrize(
    "statuses, indices",
    [
        ([], [0, 1, 2, 3]),
        (["in"], [0]),
        (["out"], [1]),
        (["unanswered"], [2, 3]),
        (["in", "out"], [0, 1]),
    ],
)
def test_review_status_filters(
    vanilla_client, layer, screening_rows, statuses, indices
):
    review, rows = screening_rows
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            list_url(layer, review), {"review": statuses}
        )
    assert response.status_code == 200
    assert set(page_ids(response)) == {rows[index].id for index in indices}


def test_review_screening_and_search_filters_combine(
    vanilla_client, layer, screening_rows
):
    review, rows = screening_rows
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            list_url(layer, review),
            {
                "review": ["unanswered"],
                "screening": ["ambiguous"],
                "search": "citation",
            },
        )
    assert response.status_code == 200
    assert page_ids(response) == [rows[2].id]


def test_search_matches_title_or_abstract_and_combines_with_screening(
    vanilla_client, layer, screening_rows
):
    review, rows = screening_rows
    rows[0].title = "A MixedCase title"
    rows[0].save()
    rows[1].abstract = "A MIXEDCASE abstract"
    rows[1].save()
    CitationFactory(title="MixedCase in another review")
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            list_url(layer, review), {"search": "mixedcase"}
        )
        combined = vanilla_client.get(
            list_url(layer, review),
            {"search": "mixedcase", "screening": ["out", "ambiguous"]},
        )
    assert set(page_ids(response)) == {rows[0].id, rows[1].id}
    assert page_ids(combined) == [rows[1].id]
    form = soup_from_str(response.content).find("form", {"method": "get"})
    assert form.parent.has_attr("open")


def test_filter_form_resets_page_and_pagination_preserves_filters(
    vanilla_client, layer
):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    CitationFactory.create_batch(11, dataset=dataset, title="Match this title")
    CitationFactory(dataset=dataset, title="Other citation")
    params = {
        "review": ["in", "unanswered"],
        "screening": ["in", "unanswered"],
        "search": "match",
        "page": 2,
    }
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(list_url(layer, review), params)
    assert response.status_code == 200
    soup = soup_from_str(response.content)
    form = soup.find("form", {"method": "get"})
    assert form["action"] == list_url(layer, review)
    assert form.find(attrs={"name": "page"}) is None
    assert form.find(attrs={"name": "csrfmiddlewaretoken"}) is None
    assert form.find("select") is None
    assert len(form.select("[data-autocomplete-multiselect]")) == 2
    filter_form = response.context_data["filter_form"]
    for name, ac_class in [
        ("review", CitationHumanStatusAutocomplete),
        ("screening", CitationStatusAutocomplete),
    ]:
        widget = filter_form.fields[name].widget
        assert isinstance(widget, AutocompleteWidget)
        assert widget.ac_class is ac_class
        assert widget.config == {
            "multiselect": True,
            "placeholder": "Select statuses",
        }
    assert [
        input_["value"]
        for input_ in form.find_all("input", {"name": "review"})
    ] == ["in", "unanswered"]
    assert "Validated-in" in form.text
    assert "Not-validated" in form.text
    assert form.find("input", {"name": "search"})["value"] == "match"
    component = soup.find(id=f"{layer.stage}-screening-component")
    assert form.sourceline < component.sourceline
    previous = component.find("button", {"hx-get": True})["hx-get"]
    query = parse_qs(urlsplit(previous).query)
    assert query == {**params, "page": ["1"], "search": ["match"]}
    with patch_rules(can_access_review=True):
        partial = vanilla_client.get(previous)
    assert partial.status_code == 200
    partial_soup = soup_from_str(partial.content)
    assert len(partial_soup.select(".citation-item")) == 10
    assert parse_qs(urlsplit(partial["HX-Push-Url"]).query) == query


def test_search_with_no_matches_renders_empty_page(vanilla_client, layer):
    review = ReviewFactory()
    CitationFactory(dataset=CitationDatasetFactory(review=review))
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            list_url(layer, review), {"search": "no matching citation"}
        )
    assert response.status_code == 200
    assert page_ids(response) == []
