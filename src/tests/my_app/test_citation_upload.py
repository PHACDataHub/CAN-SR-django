from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.models import (
    Citation,
    CitationDataset,
    CitationDatasetColumn,
    Review,
    ReviewUserLink,
)
from my_app.services.upload_citation_dataset_service import (
    CitationDatasetImporter,
    CsvCitationDatasetImportSource,
    RisCitationDatasetImportSource,
    import_citation_dataset,
)

pytestmark = pytest.mark.view


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


def test_ris_source_collects_fields_across_citations():
    source = RisCitationDatasetImportSource.from_input(
        b"TY  - JOUR\nTI  - First citation\nAB  - First abstract\n"
        b"AU  - Doe, Jane\nAU  - Smith, John\nPY  - 2020\nER  - \n"
        b"TY  - JOUR\nT1  - Second citation\nN2  - Second abstract\n"
        b"KW  - public health\nER  - \n"
    )

    columns = source.get_column_names()
    assert {"title", "abstract", "authors", "year", "keywords"} <= set(columns)
    rows = [dict(zip(columns, values)) for values in source.iter_row_values()]
    assert rows[0]["title"] == "First citation"
    assert rows[0]["authors"] == "Doe, Jane; Smith, John"
    assert rows[1]["title"] == "Second citation"
    assert rows[1]["abstract"] == "Second abstract"
    assert rows[1]["year"] == ""
    assert rows[1]["keywords"] == "public health"


def test_ris_source_rejects_files_without_citations():
    with pytest.raises(ValueError, match="no citations"):
        RisCitationDatasetImportSource.from_input("not a RIS file")


def test_build_citation_dataset_from_source_creates_expected_records():
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )
    source = StubCitationDatasetImportSource(
        [" TITLE ", "year", " abstract "],
        [
            ("First citation", "2020", "First abstract"),
            ("Second citation", "2021", "Second abstract"),
        ],
    )

    result = CitationDatasetImporter(review, source).run()

    assert result.row_count == 2
    assert result.column_count == 1
    assert result.dataset.review == review

    dataset = result.dataset
    assert [column.name for column in dataset.columns.order_by("id")] == [
        "year"
    ]
    assert [row.order for row in dataset.rows.order_by("order")] == [1, 2]
    assert dataset.rows.get(order=1).title == "First citation"
    assert dataset.rows.get(order=1).abstract == "First abstract"
    assert dataset.rows.get(order=1).data == {"year": "2020"}
    assert dataset.rows.get(order=2).title == "Second citation"
    assert dataset.rows.get(order=2).abstract == "Second abstract"
    assert dataset.rows.get(order=2).data == {"year": "2021"}


def test_build_citation_dataset_from_source_rolls_back_on_row_length_mismatch():
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )

    source = StubCitationDatasetImportSource(
        ["title", "year"],
        [("First citation", "2020"), ("Broken row",)],
    )

    with pytest.raises(ValueError, match="same number of values"):
        CitationDatasetImporter(review, source).run()

    assert CitationDataset.objects.filter(review=review).count() == 0


example_csv = """title,year,abstract,month,day
First citation,2020,An abstract,January,1
Second citation,2021,Another abstract,February,2
Third citation,2022,Yet another abstract,March,3
Fourth citation,2023,More abstract,April,4
Fifth citation,2024,Last abstract,May,5
Sixth citation,2025,Extra abstract,June,6
"""


def test_import_citation_dataset_parses_uploaded_file():
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )

    result = import_citation_dataset(
        review,
        example_csv,
    )

    assert result.row_count == 6
    assert result.column_count == 3
    assert result.dataset.review == review
    assert CitationDataset.objects.filter(review=review).count() == 1

    assert result.dataset.columns.count() == 3
    assert result.dataset.rows.count() == 6

    assert list(
        result.dataset.columns.values_list("name", flat=True).order_by("id")
    ) == ["year", "month", "day"]

    first_row = result.dataset.rows.get(order=1)
    assert first_row.title == "First citation"
    assert first_row.abstract == "An abstract"
    assert first_row.data == {
        "year": "2020",
        "month": "January",
        "day": "1",
    }


def test_import_citation_dataset_uses_bulk_inserts():
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )

    with CaptureQueriesContext(connection) as queries:
        result = import_citation_dataset(review, example_csv)

    assert result.row_count == 6
    assert result.column_count == 3

    insert_queries = [
        query["sql"]
        for query in queries
        if query["sql"].lstrip().upper().startswith("INSERT")
    ]
    assert len(insert_queries) == 3
    assert len(queries) <= 5


def test_citation_upload_creates_dataset_and_redirects(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )
    ReviewUserLink.objects.create(
        user=vanilla_user,
        review=review,
    )

    url = reverse("citation_upload", args=[review.id])

    with patch_rules(can_access_review=False):
        response = vanilla_user_client.get(url)
        assert response.status_code == 403

    uploaded_file = SimpleUploadedFile(
        "citations.csv",
        b"title,year\nFirst citation,2020\nSecond citation,2021\n",
        content_type="text/csv",
    )

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.post(
            url,
            {"format": "csv", "citation_file": uploaded_file},
            follow=True,
        )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Imported citation dataset with 2 rows and 1 column." in body

    dataset = CitationDataset.objects.get(review=review)
    assert CitationDatasetColumn.objects.filter(dataset=dataset).count() == 1
    assert Citation.objects.filter(dataset=dataset).count() == 2

    rows = list(dataset.rows.all())
    assert [row.order for row in rows] == [1, 2]
    assert rows[0].title == "First citation"
    assert rows[0].abstract == ""
    assert rows[0].data == {"year": "2020"}


def test_citation_upload_imports_ris_fields(vanilla_user_client, vanilla_user):
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )
    ReviewUserLink.objects.create(user=vanilla_user, review=review)
    uploaded_file = SimpleUploadedFile(
        "citations.ris",
        b"TY  - JOUR\nTI  - First citation\nAB  - First abstract\n"
        b"AU  - Doe, Jane\nAU  - Smith, John\nPY  - 2020\nER  - \n"
        b"TY  - JOUR\nTI  - Second citation\nKW  - screening\nER  - \n",
        content_type="application/x-research-info-systems",
    )

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.post(
            reverse("citation_upload", args=[review.id]),
            {"format": "ris", "citation_file": uploaded_file},
            follow=True,
        )

    assert response.status_code == 200
    dataset = CitationDataset.objects.get(review=review)
    assert set(dataset.columns.values_list("name", flat=True)) == {
        "type_of_reference",
        "authors",
        "year",
        "keywords",
    }
    first, second = dataset.rows.order_by("order")
    assert first.title == "First citation"
    assert first.abstract == "First abstract"
    assert first.data["authors"] == "Doe, Jane; Smith, John"
    assert second.title == "Second citation"
    assert second.data["year"] == ""
    assert second.data["keywords"] == "screening"


def test_citation_upload_rejects_mismatched_format(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )
    ReviewUserLink.objects.create(user=vanilla_user, review=review)
    uploaded_file = SimpleUploadedFile(
        "citations.csv", b"title\nFirst citation\n"
    )

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.post(
            reverse("citation_upload", args=[review.id]),
            {"format": "ris", "citation_file": uploaded_file},
        )

    assert response.status_code == 200
    assert (
        b"File extension must match the selected format." in response.content
    )
    assert not CitationDataset.objects.filter(review=review).exists()


def test_review_detail_disables_import_button_when_dataset_exists(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(
        title="Review",
        description="Review description",
    )
    ReviewUserLink.objects.create(
        user=vanilla_user,
        review=review,
    )
    CitationDataset.objects.create(review=review)

    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(
            reverse("review_detail", args=[review.id])
        )

    assert response.status_code == 200
    body = response.content.decode()
    assert "View dataset" in body
    assert reverse("citation_dataset_detail", args=[review.id]) in body
    assert "✓" in body
