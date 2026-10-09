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


def test_dataset_table_defaults_and_available_columns(
    vanilla_user_client, vanilla_user
):
    from my_app.tables.citation_table import CitationDatasetTableDef

    review = _create_review_with_dataset(vanilla_user)
    url = reverse("citation_dataset_detail", args=[review.pk])
    with patch_rules(can_access_review=False):
        assert vanilla_user_client.get(url).status_code == 403
    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(url)

    table = response.context["table_def"]
    assert isinstance(table, CitationDatasetTableDef)
    assert [column.key for column in table.enabled_columns] == [
        "title",
        "abstract",
    ]
    dataset_keys = {
        f"dataset_{column.pk}"
        for column in review.citation_dataset.columns.all()
    }
    assert {column.key for column in table.columns} == {
        "id",
        "title",
        "abstract",
        *dataset_keys,
    }
    assert not table.filter_forms
    assert not table.get_queryset().query.annotations
    assert not table.get_queryset().query.select_related
    assert all(column.exportable for column in table.columns)


def test_dataset_table_column_selection_sorting_and_pagination(
    vanilla_user_client, vanilla_user
):
    from my_app.model_factories import CitationFactory
    from my_app.tables.table_framework import TableDef

    review = _create_review_with_dataset(vanilla_user)
    dataset = review.citation_dataset
    CitationFactory.create_batch(
        25, dataset=dataset, data={"year": "Dataset year"}
    )
    foreign = CitationFactory(title="Foreign citation")
    year_column = dataset.columns.get(name="year")
    key = f"dataset_{year_column.pk}"
    prefix = TableDef.COL_SELECTION_FORM_PREFIX
    params = {
        f"{prefix}-submitted": "True",
        f"{prefix}-columns": ["id", key],
        "sort_form-column": "id",
        "sort_form-direction": "desc",
    }
    url = reverse("citation_dataset_detail", args=[review.pk])
    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(url, params)
        params["page"] = 2
        second = vanilla_user_client.get(url, params)
        empty_selection = vanilla_user_client.get(
            url, {f"{prefix}-submitted": "True"}
        )

    assert (
        response.status_code
        == second.status_code
        == empty_selection.status_code
        == 200
    )
    assert [column.key for column in response.context["columns"]] == [
        "id",
        key,
    ]
    page = response.context["page_obj"]
    assert page.paginator.count == 31
    assert len(page) == 25
    assert len(second.context["page_obj"]) == 6
    ids = [row.pk for row in page] + [
        row.pk for row in second.context["page_obj"]
    ]
    assert ids == list(
        dataset.rows.order_by("-pk").values_list("pk", flat=True)
    )
    assert foreign.pk not in ids
    assert "Dataset year" in response.content.decode()
    assert "sort_form-column=id" in response.content.decode()
    assert f"{prefix}-columns={key}" in response.content.decode()
    assert "Select at least one column" in empty_selection.content.decode()
