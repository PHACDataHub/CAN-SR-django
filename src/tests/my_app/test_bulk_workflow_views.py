from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    BulkWorkflowRequestFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
)
from my_app.models import (
    BulkWorkflowRequest,
    L1CriticalScreeningResult,
    L2HumanAnswer,
    ScreeningActions,
)
from my_app.services.bulk_workflow import QueueBulkResultsService
from tests.bulk_workflow_cases import bulk_context

pytestmark = pytest.mark.view


def launch_url(phase, review):
    if phase == 1:
        return reverse("phase1_bulk_workflow", args=[review.pk])
    return reverse("phase3_bulk_workflow", args=[review.pk])


def status_url(phase, review, bulk):
    if phase == 1:
        return reverse(
            "phase1_bulk_workflow_status", args=[review.pk, bulk.pk]
        )
    return reverse("phase3_bulk_workflow_status", args=[review.pk, bulk.pk])


@pytest.mark.parametrize("phase", [1, 3])
def test_bulk_launch_status_and_list_links(
    phase, vanilla_client, vanilla_user
):
    review, citations, _, _ = bulk_context(phase)
    url = launch_url(phase, review)
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
        assert response.status_code == 200
        assert f"Phase {phase} workflow" in response.content.decode()
        assert b"should_download_pdf" not in response.content
        response = vanilla_client.post(url)
        assert response.status_code == 302
        bulk = BulkWorkflowRequest.objects.get()
        assert bulk.phase == phase
        assert bulk.requested_by == vanilla_user
        status = vanilla_client.get(response.url)
        assert status.status_code == 200
        assert b"Pending" in status.content
        assert citations[0].title in status.content.decode()
        if phase == 1:
            list_url = reverse("l1_citations_list", args=[review.pk])
            detail_url = reverse(
                "l1_citation_detail", args=[review.pk, citations[0].pk]
            )
        else:
            list_url = reverse(
                "parameter_extraction_citations_list", args=[review.pk]
            )
            detail_url = reverse(
                "parameter_extraction_citation_detail",
                args=[review.pk, citations[0].pk],
            )
        assert detail_url in status.content.decode()
        assert url in vanilla_client.get(list_url).content.decode()


@pytest.mark.parametrize("phase", [1, 3])
def test_bulk_views_require_review_access(phase, vanilla_client):
    review, _, _, _ = bulk_context(phase)
    bulk = BulkWorkflowRequestFactory(review=review, phase=phase)
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(launch_url(phase, review)).status_code == 403
        assert (
            vanilla_client.post(launch_url(phase, review)).status_code == 403
        )
        assert (
            vanilla_client.get(status_url(phase, review, bulk)).status_code
            == 403
        )


@pytest.mark.parametrize("phase", [1, 3])
def test_configuration_error_is_shown_without_creating_request(
    phase, vanilla_client
):
    review, _, question, _ = bulk_context(phase)
    question.soft_delete()
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(launch_url(phase, review))
    assert response.status_code == 200
    assert b"Configure" in response.content
    assert b'role="alert"' in response.content
    assert not BulkWorkflowRequest.objects.exists()


@pytest.mark.parametrize("phase", [1, 3])
def test_pending_bulk_is_shown_as_form_error(phase, vanilla_client):
    review, _, _, _ = bulk_context(phase)
    QueueBulkResultsService(review, phase).perform()
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(launch_url(phase, review))
    assert response.status_code == 200
    assert b"already pending" in response.content
    assert BulkWorkflowRequest.objects.count() == 1


@pytest.mark.parametrize("phase", [1, 2, 3])
def test_bulk_launch_selects_first_100_eligible_citations(
    phase, vanilla_client
):
    context_phase = 1 if phase == 2 else phase
    review, citations, question, _ = bulk_context(context_phase, count=102)
    eligible = citations
    url = launch_url(phase, review)
    options = {}
    if phase == 1:
        for _ in range(5):
            extra_question = L1ScreeningQuestionFactory(review=review)
            L1ScreeningQuestionOptionFactory(question=extra_question)
    elif phase == 2:
        eligible = citations[1:]
        include = L1ScreeningQuestionOptionFactory(
            question=question, screening_action=ScreeningActions.ScreenIn
        )
        for citation in eligible:
            L1HumanAnswerFactory(
                citation=citation, question=question, selected_option=include
            )
        url = reverse("phase2_bulk_workflow", args=[review.pk])
        options = {"should_download_pdf": "on"}
    else:
        eligible = citations[1:]
        L2HumanAnswer.objects.filter(citation=citations[0]).delete()

    with patch_rules(can_access_review=True):
        response = vanilla_client.post(url, options)

    assert response.status_code == 302
    bulk = BulkWorkflowRequest.objects.get(review=review, phase=phase)
    if phase == 1:
        results = bulk.l1_results
        assert results.count() == 600
    elif phase == 2:
        results = bulk.citation_requests
        assert results.count() == 100
    else:
        results = bulk.parameter_results
        assert results.count() == 100
    assert set(results.values_list("citation_id", flat=True)) == {
        citation.pk for citation in eligible[:100]
    }


@pytest.mark.parametrize("phase", [1, 3])
def test_status_is_scoped_to_review_and_phase(phase, vanilla_client):
    review, _, _, _ = bulk_context(phase)
    foreign = BulkWorkflowRequestFactory(phase=phase)
    other_phase = BulkWorkflowRequestFactory(review=review, phase=2)
    with patch_rules(can_access_review=True):
        assert (
            vanilla_client.get(status_url(phase, review, foreign)).status_code
            == 404
        )
        assert (
            vanilla_client.get(
                status_url(phase, review, other_phase)
            ).status_code
            == 404
        )
        assert (
            vanilla_client.get(
                reverse(
                    "phase2_bulk_workflow_status",
                    args=[foreign.review_id, foreign.pk],
                )
            ).status_code
            == 404
        )


@pytest.mark.parametrize("phase", [1, 3])
def test_status_groups_questions_by_citation_and_waits_for_critical(
    phase, vanilla_client
):
    review, citations, _, _ = bulk_context(phase, count=1)
    bulk = QueueBulkResultsService(review, phase).perform()
    if phase == 1:
        bulk.l1_results.update(status="completed")
    else:
        bulk.parameter_results.update(status="completed")
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(status_url(phase, review, bulk))
    body = response.content.decode()
    assert body.count(citations[0].title) == 1
    if phase == 1:
        assert ": Pending" in body
        L1CriticalScreeningResult.objects.create(
            initial_result=bulk.l1_results.get(), status="completed"
        )
        with patch_rules(can_access_review=True):
            response = vanilla_client.get(status_url(phase, review, bulk))
        assert ": Completed" in response.content.decode()
    else:
        assert ": Completed" in body
