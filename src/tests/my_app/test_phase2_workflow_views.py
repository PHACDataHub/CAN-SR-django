from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    BulkWorkflowRequestFactory,
    CitationFactory,
    Phase2CitationWorkflowRequestFactory,
    ReviewFactory,
)
from my_app.models import BulkWorkflowRequest, Phase2CitationWorkflowRequest

pytestmark = pytest.mark.view


@pytest.mark.parametrize("bulk", [False, True])
def test_launch_views_require_review_access(vanilla_client, bulk):
    citation = CitationFactory()
    args = [citation.dataset.review_id]
    name = "phase2_bulk_workflow"
    if not bulk:
        name = "phase2_citation_workflow"
        args.append(citation.pk)
    url = reverse(name, args=args)
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
        assert (
            vanilla_client.post(url, {"should_download_pdf": "on"}).status_code
            == 403
        )
    assert not Phase2CitationWorkflowRequest.objects.exists()
    assert not BulkWorkflowRequest.objects.exists()


@pytest.mark.parametrize("bulk", [False, True])
def test_launch_form_and_status(vanilla_client, vanilla_user, bulk):
    citation = CitationFactory()
    review = citation.dataset.review
    name = "phase2_citation_workflow"
    args = [review.pk, citation.pk]
    if bulk:
        name = "phase2_bulk_workflow"
        args = [review.pk]
    url = reverse(name, args=args)
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
        assert response.status_code == 200
        assert b"Start workflow" in response.content
        assert b"should_process_pdf" in response.content
        assert vanilla_client.post(url, {}).status_code == 200
        assert not Phase2CitationWorkflowRequest.objects.exists()
        response = vanilla_client.post(url, {"should_download_pdf": "on"})
        assert response.status_code == 302
        status_response = vanilla_client.get(response.url)
        assert status_response.status_code == 200
        assert b"Pending" in status_response.content
    model = Phase2CitationWorkflowRequest
    if bulk:
        model = BulkWorkflowRequest
    assert model.objects.get().requested_by == vanilla_user


def test_citation_launch_rejects_duplicate_and_unconfigured_l2(vanilla_client):
    citation = CitationFactory()
    url = reverse(
        "phase2_citation_workflow",
        args=[citation.dataset.review_id, citation.pk],
    )
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(url, {"should_run_l2": "on"})
        assert response.status_code == 200
        assert b"Configure L2" in response.content
        assert not Phase2CitationWorkflowRequest.objects.exists()
        Phase2CitationWorkflowRequestFactory(citation=citation)
        response = vanilla_client.post(url, {"should_download_pdf": "on"})
        assert response.status_code == 200
        assert b"already pending" in response.content


def test_citation_launch_cannot_target_another_reviews_citation(
    vanilla_client,
):
    citation = CitationFactory()
    review = ReviewFactory()
    url = reverse("phase2_citation_workflow", args=[review.pk, citation.pk])
    with patch_rules(can_access_review=True):
        assert vanilla_client.get(url).status_code == 404
        assert (
            vanilla_client.post(url, {"should_download_pdf": "on"}).status_code
            == 404
        )
    assert not Phase2CitationWorkflowRequest.objects.exists()


@pytest.mark.parametrize("bulk", [False, True])
def test_status_is_scoped_to_review_and_authorized(vanilla_client, bulk):
    workflow = Phase2CitationWorkflowRequestFactory()
    review_id = workflow.citation.dataset.review_id
    name = "phase2_citation_workflow_status"
    if bulk:
        workflow = BulkWorkflowRequestFactory()
        review_id = workflow.review_id
        name = "phase2_bulk_workflow_status"
    with patch_rules(can_access_review=False):
        assert (
            vanilla_client.get(
                reverse(name, args=[review_id, workflow.pk])
            ).status_code
            == 403
        )
    with patch_rules(can_access_review=True):
        assert (
            vanilla_client.get(
                reverse(name, args=[ReviewFactory().pk, workflow.pk])
            ).status_code
            == 404
        )


def test_bulk_status_links_to_citation_requests(vanilla_client):
    bulk = BulkWorkflowRequestFactory()
    child = Phase2CitationWorkflowRequestFactory(
        bulk_request=bulk, citation__dataset__review=bulk.review
    )
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                "phase2_bulk_workflow_status", args=[bulk.review_id, bulk.pk]
            )
        )
    assert response.status_code == 200
    assert (
        reverse(
            "phase2_citation_workflow_status", args=[bulk.review_id, child.pk]
        )
        in response.content.decode()
    )
