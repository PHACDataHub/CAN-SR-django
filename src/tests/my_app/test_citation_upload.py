import base64

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
    assert len(queries) <= 12


def submit_mappings(client, review, names, **overrides):
    mapping_page = client.get(
        reverse("citation_upload_mapping", args=[review.id])
    )
    data = {
        "form-TOTAL_FORMS": str(len(names)),
        "form-INITIAL_FORMS": str(len(names)),
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
    }
    for index, name in enumerate(names):
        data[f"form-{index}-name"] = name
        data[f"form-{index}-include"] = "on"
        if index < len(mapping_page.context["formset"].forms):
            selected = (
                mapping_page.context["formset"]
                .forms[index]["existing_column"]
                .value()
            )
            if selected:
                data[f"form-{index}-existing_column"] = selected
    data.update(overrides)
    return client.post(
        reverse("citation_upload_mapping", args=[review.id]),
        data,
        follow=True,
    )


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
        upload_response = vanilla_user_client.post(
            url,
            {"format": "csv", "citation_file": uploaded_file},
        )
        assert upload_response.status_code == 302
        assert upload_response.url == reverse(
            "citation_upload_mapping", args=[review.id]
        )
        assert not CitationDataset.objects.filter(review=review).exists()
        pending = vanilla_user_client.session[f"citation_import_{review.id}"]
        assert pending["format"] == "csv"
        assert base64.b64decode(pending["content"]).startswith(b"title,year")
        mapping_response = vanilla_user_client.get(upload_response.url)
        assert b"Rows to import: 2" in mapping_response.content
        response = submit_mappings(
            vanilla_user_client, review, ["title", "year"]
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
    assert f"citation_import_{review.id}" not in vanilla_user_client.session


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
        )
        mapping_page = vanilla_user_client.get(response.url)
        names = mapping_page.context["column_names"]
        response = submit_mappings(vanilla_user_client, review, names)

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


def test_citation_upload_appends_with_mapping_and_exclusion(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(title="Review", description="Description")
    ReviewUserLink.objects.create(user=vanilla_user, review=review)
    upload_url = reverse("citation_upload", args=[review.id])

    with patch_rules(can_access_review=True):
        vanilla_user_client.post(
            upload_url,
            {
                "format": "csv",
                "citation_file": SimpleUploadedFile(
                    "first.csv", b"title,year\nFirst,2020\n"
                ),
            },
        )
        submit_mappings(vanilla_user_client, review, ["title", "year"])
        dataset = CitationDataset.objects.get(review=review)
        year_column = dataset.columns.get(name="year")

        vanilla_user_client.post(
            upload_url,
            {
                "format": "csv",
                "citation_file": SimpleUploadedFile(
                    "second.csv",
                    b"heading,published,notes,skip\nSecond,2021,note,ignored\n",
                ),
            },
        )
        response = submit_mappings(
            vanilla_user_client,
            review,
            ["heading", "published", "notes", "skip"],
            **{
                "form-0-existing_column": "title",
                "form-1-existing_column": f"column:{year_column.id}",
                "form-2-name": "comment",
                "form-3-include": "",
            },
        )

    assert response.status_code == 200
    assert CitationDataset.objects.filter(review=review).count() == 1
    assert list(
        dataset.columns.values_list("name", flat=True).order_by("id")
    ) == ["year", "comment"]
    assert list(dataset.rows.values_list("order", flat=True)) == [1, 2]
    second = dataset.rows.get(order=2)
    assert second.title == "Second"
    assert second.data == {"year": "2021", "comment": "note"}
    assert f"citation_import_{review.id}" not in vanilla_user_client.session


def test_citation_mapping_rejects_duplicate_targets_and_preserves_file(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(title="Review", description="Description")
    ReviewUserLink.objects.create(user=vanilla_user, review=review)

    with patch_rules(can_access_review=True):
        vanilla_user_client.post(
            reverse("citation_upload", args=[review.id]),
            {
                "format": "csv",
                "citation_file": SimpleUploadedFile(
                    "citations.csv", b"one,two\na,b\n"
                ),
            },
        )
        response = submit_mappings(
            vanilla_user_client,
            review,
            ["year", "YEAR"],
        )

    assert (
        b"Multiple uploaded columns map to the same dataset column."
        in response.content
    )
    assert not CitationDataset.objects.filter(review=review).exists()
    assert f"citation_import_{review.id}" in vanilla_user_client.session


def test_citation_mapping_rejects_missing_forms(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(title="Review", description="Description")
    ReviewUserLink.objects.create(user=vanilla_user, review=review)

    with patch_rules(can_access_review=True):
        vanilla_user_client.post(
            reverse("citation_upload", args=[review.id]),
            {
                "format": "csv",
                "citation_file": SimpleUploadedFile(
                    "citations.csv", b"title,year\nFirst,2020\n"
                ),
            },
        )
        response = submit_mappings(vanilla_user_client, review, ["title"])

    assert b"The uploaded columns changed." in response.content
    assert not CitationDataset.objects.filter(review=review).exists()


def test_citation_mapping_requires_pending_upload(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(title="Review", description="Description")
    ReviewUserLink.objects.create(user=vanilla_user, review=review)
    with patch_rules(can_access_review=True):
        response = vanilla_user_client.get(
            reverse("citation_upload_mapping", args=[review.id])
        )
    assert response.status_code == 302
    assert response.url == reverse("citation_upload", args=[review.id])


def test_citation_mapping_defaults_to_matching_existing_columns(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(title="Review", description="Description")
    ReviewUserLink.objects.create(user=vanilla_user, review=review)
    dataset = CitationDataset.objects.create(review=review)
    year = CitationDatasetColumn.objects.create(dataset=dataset, name=" Year ")

    with patch_rules(can_access_review=True):
        vanilla_user_client.post(
            reverse("citation_upload", args=[review.id]),
            {
                "format": "csv",
                "citation_file": SimpleUploadedFile(
                    "citations.csv", b"YEAR,New field\n2020,value\n"
                ),
            },
        )
        response = vanilla_user_client.get(
            reverse("citation_upload_mapping", args=[review.id])
        )

    forms = response.context["formset"].forms
    assert forms[0]["existing_column"].value() == f"column:{year.id}"
    assert forms[0]["name"].value() == "YEAR"
    assert forms[0]["include"].value() is True
    assert forms[1]["existing_column"].value() == ""
    assert forms[1]["name"].value() == "New field"
    assert forms[1]["include"].value() is True
    body = response.content.decode()
    assert "Create by name" in body
    assert "Include" in body
    assert "data-column-mapping-row" in body


def test_citation_upload_can_append_ris_after_csv(
    vanilla_user_client, vanilla_user
):
    review = Review.objects.create(title="Review", description="Description")
    ReviewUserLink.objects.create(user=vanilla_user, review=review)
    upload_url = reverse("citation_upload", args=[review.id])

    with patch_rules(can_access_review=True):
        vanilla_user_client.post(
            upload_url,
            {
                "format": "csv",
                "citation_file": SimpleUploadedFile(
                    "first.csv", b"title,year\nFirst,2020\n"
                ),
            },
        )
        submit_mappings(vanilla_user_client, review, ["title", "year"])

        vanilla_user_client.post(
            upload_url,
            {
                "format": "ris",
                "citation_file": SimpleUploadedFile(
                    "second.ris",
                    b"TY  - JOUR\nTI  - Second\nPY  - 2021\nER  - \n",
                ),
            },
        )
        mapping_page = vanilla_user_client.get(
            reverse("citation_upload_mapping", args=[review.id])
        )
        response = submit_mappings(
            vanilla_user_client, review, mapping_page.context["column_names"]
        )

    assert response.status_code == 200
    dataset = CitationDataset.objects.get(review=review)
    assert list(dataset.rows.values_list("title", flat=True)) == [
        "First",
        "Second",
    ]
    assert dataset.columns.filter(name="year").count() == 1
    assert dataset.rows.get(order=2).data["year"] == "2021"


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
