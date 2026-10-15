from django.test import override_settings
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningResultFactory,
    ParameterExtractionResultFactory,
    ParameterHumanAnswerFactory,
    ReviewFactory,
)
from my_app.models import ScreeningResultStatus
from tests.utils_for_testing import soup_from_str

pytestmark = pytest.mark.view


@pytest.fixture(params=["l1", "l2", "parameter_extraction"])
def workflow(request):
    stage = request.param
    review = ReviewFactory()
    citation = CitationFactory(dataset=CitationDatasetFactory(review=review))
    if stage == "l1":
        result = L1ScreeningResultFactory(citation=citation)
        detail_url = reverse(
            "l1_citation_detail", args=[review.id, citation.id]
        )
        list_url = reverse("l1_citations_list", args=[review.id])
        partial_url = reverse("l1_citations_list_partial", args=[review.id])
        answer_factory = L1HumanAnswerFactory
    elif stage == "l2":
        result = L2ScreeningResultFactory(citation=citation)
        detail_url = reverse(
            "l2_citation_detail", args=[review.id, citation.id]
        )
        list_url = reverse("l2_citations_list", args=[review.id])
        partial_url = reverse("l2_citations_list_partial", args=[review.id])
        answer_factory = L2HumanAnswerFactory
    else:
        result = ParameterExtractionResultFactory(citation=citation)
        detail_url = reverse(
            "parameter_extraction_citation_detail",
            args=[review.id, citation.id],
        )
        list_url = reverse(
            "parameter_extraction_citations_list", args=[review.id]
        )
        partial_url = reverse(
            "parameter_extraction_citations_list_partial", args=[review.id]
        )
        answer_factory = ParameterHumanAnswerFactory
    return (
        stage,
        citation,
        result,
        detail_url,
        list_url,
        partial_url,
        answer_factory,
    )


@pytest.mark.parametrize("polling", [True, False])
def test_workflow_pages_have_one_refresh_owner(
    vanilla_client, workflow, polling
):
    stage, citation, result, detail_url, list_url, _, _ = workflow
    with (
        override_settings(ENABLE_HTMX_POLLING=polling),
        patch_rules(can_access_review=True),
    ):
        for url in [detail_url, list_url]:
            response = vanilla_client.get(url)
            assert response.status_code == 200
            soup = soup_from_str(response.content)
            owners = soup.select(".workflow-refresh")
            assert len(owners) == 1
            owner = owners[0]
            assert owner["hx-sync"] == "body:drop"
            assert soup.body["hx-sync"] == "this:replace"
            assert "click from:#refresh-button" in owner["hx-trigger"]
            assert (
                "every 5s [!document.hidden]" in owner["hx-trigger"]
            ) == polling
            assert soup.find(id="refresh-button") is not None
            assert owner.find(id="modal-slot") is None
            assert not owner.has_attr("hx-include")
            if url == list_url and stage != "parameter_extraction":
                form = soup.find(id="screening-filters")
                assert not form.has_attr("data-filter-fields")
                assert owner.find(id="screening-filters") is None
            if url == detail_url:
                assert owner["hx-get"] == detail_url
                assert owner["hx-swap"] == "morph:outerHTML"
                assert owner["hx-select"] == "#workflow-detail-component"
                assert owner["hx-disinherit"] == "hx-select"


def test_detail_refresh_updates_one_component_and_preserves_pdf(
    vanilla_client, workflow
):
    _, citation, result, detail_url, _, _, answer_factory = workflow
    headers = {"HX-Request": "true", "HX-Target": "workflow-detail-component"}
    with patch_rules(can_access_review=True):
        before = vanilla_client.get(detail_url, headers=headers)
        result.status = ScreeningResultStatus.COMPLETED
        result.explanation = "Updated by the background worker"
        result.save()
        answer_factory(citation=citation, question=result.question)
        after = vanilla_client.get(detail_url, headers=headers)
    assert before.status_code == after.status_code == 200
    before_soup = soup_from_str(before.content).find(
        id="workflow-detail-component"
    )
    after_soup = soup_from_str(after.content).find(
        id="workflow-detail-component"
    )
    assert (
        before_soup.select_one('[role="progressbar"]')["aria-valuenow"] == "0"
    )
    assert (
        after_soup.select_one('[role="progressbar"]')["aria-valuenow"] == "100"
    )
    assert "Updated by the background worker" in after_soup.text
    assert after_soup.select("[hx-swap-oob]") == []
    if workflow[0] != "l1":
        assert after_soup.find(id="citation-pdf-viewer").has_attr(
            "hx-preserve"
        )
    assert after_soup.find(id="modal-slot") is None
    assert after_soup.find("form") is None
    assert after_soup.find("script") is None
    assert len(after_soup.select('[hx-trigger*="every"]')) == 0


def test_detail_refresh_requires_review_access(vanilla_client, workflow):
    detail_url = workflow[3]
    with patch_rules(can_access_review=False):
        response = vanilla_client.get(
            detail_url,
            headers={
                "HX-Request": "true",
                "HX-Target": "workflow-detail-component",
            },
        )
    assert response.status_code == 403


def test_list_refresh_updates_rows_and_metrics(vanilla_client, workflow):
    _, citation, result, _, _, partial_url, _ = workflow
    with patch_rules(can_access_review=True):
        before = vanilla_client.get(partial_url)
        result.status = ScreeningResultStatus.COMPLETED
        result.save()
        CitationFactory(dataset=citation.dataset)
        after = vanilla_client.get(partial_url)
    before_soup = soup_from_str(before.content)
    after_soup = soup_from_str(after.content)
    assert "Completed" in after_soup.select_one(".citation-item").text
    assert before_soup.select_one(".screening-progress-panel dd").text == "1"
    assert after_soup.select_one(".screening-progress-panel dd").text == "2"


def test_l1_rescreen_selects_only_the_control(vanilla_client):
    result = L1ScreeningResultFactory()
    citation = result.citation
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                "l1_citation_detail",
                args=[citation.dataset.review_id, citation.id],
            )
        )
    button = soup_from_str(response.content).find("button", string="Re-screen")
    assert button["hx-select"] == button["hx-target"]
    assert button["hx-swap"] == "outerHTML"


def test_list_refresh_clamps_page_when_citations_disappear(
    vanilla_client, workflow
):
    _, citation, _, _, _, partial_url, _ = workflow
    rows = CitationFactory.create_batch(10, dataset=citation.dataset)
    headers = {"HX-Request": "true"}
    with patch_rules(can_access_review=True):
        before = vanilla_client.get(partial_url, {"page": 2}, headers=headers)
        rows[0].delete()
        after = vanilla_client.get(partial_url, {"page": 2}, headers=headers)
    assert before.status_code == after.status_code == 200
    assert (
        "Page 2 of 2"
        in soup_from_str(before.content).find(id="page_x_of_y").text
    )
    assert (
        "Page 1 of 1"
        in soup_from_str(after.content).find(id="page_x_of_y").text
    )
