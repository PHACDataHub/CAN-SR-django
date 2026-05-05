from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

import pytest

from phac_aspc.rules import patch_rules

from my_app.models import (
    CitationDataset,
    CitationDatasetCell,
    CitationDatasetColumn,
    CitationDatasetRow,
    SystematicReview,
    SystematicReviewUserLink,
)
from my_app.services.upload_citation_dataset_service import (
    CsvCitationDatasetImportSource,
    build_citation_dataset_from_source,
    import_citation_dataset,
)


class StubCitationDatasetImportSource:
    def __init__(self, column_names, row_values):
        self._column_names = column_names
        self._row_values = row_values

    def get_column_names(self):
        return self._column_names

    def iter_row_values(self):
        return iter(self._row_values)


def test_csv_source_parses_headers_and_rows():
    source = CsvCitationDatasetImportSource.from_input(
        b"title,year\nFirst citation,2020\nSecond citation,2021\n"
    )

    assert source.get_column_names() == ["title", "year"]
    assert list(source.iter_row_values()) == [
        ("First citation", "2020"),
        ("Second citation", "2021"),
    ]


def test_build_citation_dataset_from_source_creates_expected_records():
    review = SystematicReview.objects.create(
        title="Review",
        description="Review description",
    )
    source = StubCitationDatasetImportSource(
        ["title", "year"],
        [("First citation", "2020"), ("Second citation", "2021")],
    )

    result = build_citation_dataset_from_source(review, source)

    assert result.row_count == 2
    assert result.column_count == 2
    assert result.dataset.systematic_review == review

    dataset = result.dataset
    assert [column.name for column in dataset.columns.order_by("id")] == [
        "title",
        "year",
    ]
    assert [row.order for row in dataset.rows.order_by("order")] == [1, 2]
    assert [
        cell.value for cell in dataset.rows.get(order=1).cells.order_by("id")
    ] == ["First citation", "2020"]
    assert [
        cell.value for cell in dataset.rows.get(order=2).cells.order_by("id")
    ] == ["Second citation", "2021"]


def test_build_citation_dataset_from_source_rolls_back_on_row_length_mismatch():
    review = SystematicReview.objects.create(
        title="Review",
        description="Review description",
    )

    source = StubCitationDatasetImportSource(
        ["title", "year"],
        [("First citation", "2020"), ("Broken row",)],
    )

    with pytest.raises(ValueError, match="same number of values"):
        build_citation_dataset_from_source(review, source)

    assert review.citation_datasets.count() == 0


example_csv = """title,year,abstract,month,day
First citation,2020,An abstract,January,1
Second citation,2021,Another abstract,February,2
Third citation,2022,Yet another abstract,March,3
Fourth citation,2023,More abstract,April,4
Fifth citation,2024,Last abstract,May,5
Sixth citation,2025,Extra abstract,June,6
"""


def test_import_citation_dataset_parses_uploaded_file():
    review = SystematicReview.objects.create(
        title="Review",
        description="Review description",
    )

    result = import_citation_dataset(
        review,
        example_csv,
    )

    assert result.row_count == 6
    assert result.column_count == 5
    assert result.dataset.systematic_review == review
    assert review.citation_datasets.count() == 1

    assert result.dataset.columns.count() == 5
    assert result.dataset.rows.count() == 6
    assert CitationDatasetCell.objects.count() == 30

    assert list(
        result.dataset.columns.values_list("name", flat=True).order_by("id")
    ) == ["title", "year", "abstract", "month", "day"]

    first_row = result.dataset.rows.get(order=1)
    first_row_cells = first_row.cells.select_related("column").order_by(
        "column__id"
    )
    assert {(cell.column.name, cell.value) for cell in first_row_cells} == {
        ("title", "First citation"),
        ("year", "2020"),
        ("abstract", "An abstract"),
        ("month", "January"),
        ("day", "1"),
    }


def test_import_citation_dataset_uses_bulk_inserts():
    review = SystematicReview.objects.create(
        title="Review",
        description="Review description",
    )

    with CaptureQueriesContext(connection) as queries:
        result = import_citation_dataset(review, example_csv)

    assert result.row_count == 6
    assert result.column_count == 5

    insert_queries = [
        query["sql"]
        for query in queries
        if query["sql"].lstrip().upper().startswith("INSERT")
    ]
    assert len(insert_queries) == 4
    assert len(queries) <= 6


def test_citation_upload_creates_dataset_and_redirects(
    vanilla_user_client, vanilla_user
):
    review = SystematicReview.objects.create(
        title="Review",
        description="Review description",
    )
    SystematicReviewUserLink.objects.create(
        user=vanilla_user,
        systematic_review=review,
    )

    url = reverse("citation_upload", args=[review.id])

    with patch_rules(can_access_systematic_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    uploaded_file = SimpleUploadedFile(
        "citations.csv",
        b"title,year\nFirst citation,2020\nSecond citation,2021\n",
        content_type="text/csv",
    )

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.post(
            url,
            {"citation_file": uploaded_file},
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Imported citation dataset with 2 rows and 2 columns." in body

    dataset = CitationDataset.objects.get(systematic_review=review)
    assert CitationDatasetColumn.objects.filter(dataset=dataset).count() == 2
    assert CitationDatasetRow.objects.filter(dataset=dataset).count() == 2
    assert (
        CitationDatasetCell.objects.filter(row__dataset=dataset).count() == 4
    )

    rows = list(dataset.rows.all())
    assert [row.order for row in rows] == [1, 2]
    assert [cell.value for cell in rows[0].cells.order_by("column_id")] == [
        "First citation",
        "2020",
    ]


def test_systematic_review_detail_disables_import_button_when_dataset_exists(
    vanilla_user_client, vanilla_user
):
    review = SystematicReview.objects.create(
        title="Review",
        description="Review description",
    )
    SystematicReviewUserLink.objects.create(
        user=vanilla_user,
        systematic_review=review,
    )
    CitationDataset.objects.create(systematic_review=review)

    with patch_rules(can_access_systematic_review=True):
        response = vanilla_user_client.get(
            reverse("systematic_review_detail", args=[review.id])
        )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Import citation dataset" in body
    assert 'aria-disabled="true"' in body
    assert "disabled" in body
    assert "✓" in body
