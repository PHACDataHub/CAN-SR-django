from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import ReviewFactory, ReviewUserLinkFactory
from my_app.models import CitationDataset
from my_app.services.upload_citation_dataset_service import (
    import_citation_dataset,
)

pytestmark = pytest.mark.view

EXAMPLE_CSV = """title,year,abstract,month,day
First citation,2020,An abstract,January,1
Second citation,2021,Another abstract,February,2
Third citation,2022,Yet another abstract,March,3
Fourth citation,2023,More abstract,April,4
Fifth citation,2024,Last abstract,May,5
Sixth citation,2025,Extra abstract,June,6
"""


def _create_review_with_dataset(vanilla_user):
    review = ReviewFactory(
        title="Review",
        description="Review description",
    )
    ReviewUserLinkFactory(user=vanilla_user, review=review)
    import_citation_dataset(review, EXAMPLE_CSV)
    return review


def test_citation_dataset_detail_shows_summary_and_rows(
    vanilla_user_client, vanilla_user
):
    review = _create_review_with_dataset(vanilla_user)
    url = reverse("citation_dataset_detail", args=[review.id])

    with patch_rules(can_access_review=True):
        with CaptureQueriesContext(connection) as queries:
            response = vanilla_user_client.get(url)

    assert response.status_code == 200
    body = response.content.decode()
    assert "Dataset summary" in body
    assert "Number of rows" in body
    assert "First citation" in body
    assert "An abstract" in body
    assert "Sixth citation" in body
    assert "Delete dataset" in body
    assert reverse("delete_citation_dataset", args=[review.id]) in body
    assert len(queries) <= 14


def test_citation_dataset_detail_returns_400_when_dataset_missing(
    vanilla_user_client, vanilla_user
):
    review = ReviewFactory(
        title="Review",
        description="Review description",
    )
    ReviewUserLinkFactory(user=vanilla_user, review=review)

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(
            reverse("citation_dataset_detail", args=[review.id])
        )

    assert response.status_code == 400


def test_delete_citation_dataset_removes_dataset_and_redirects(
    vanilla_user_client, vanilla_user
):
    review = _create_review_with_dataset(vanilla_user)
    url = reverse("delete_citation_dataset", args=[review.id])

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(url)

    assert response.status_code == 200
    assert "Delete dataset" in response.content.decode()

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.post(
            url, {"confirm": True}, follow=True
        )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == reverse(
        "review_detail", args=[review.id]
    )
    assert not CitationDataset.objects.filter(review=review).exists()
