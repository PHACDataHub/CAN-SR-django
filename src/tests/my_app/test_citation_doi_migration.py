from importlib import import_module

from django.db import connection
from django.db.migrations.loader import MigrationLoader

import pytest

from my_app.model_factories import (
    CitationDatasetColumnFactory,
    CitationDatasetFactory,
    CitationFactory,
)


@pytest.mark.parametrize("name", ["doi", "DOI"])
def test_migration_moves_doi_and_removes_legacy_column(name):
    dataset = CitationDatasetFactory()
    column = CitationDatasetColumnFactory(dataset=dataset, name=name)
    year = CitationDatasetColumnFactory(dataset=dataset, name="year")
    dataset.screening_columns.add(column, year)
    populated = CitationFactory(
        dataset=dataset, data={name: "10.1234/example", "year": "2020"}
    )
    empty = CitationFactory(dataset=dataset, data={name: ""})
    missing = CitationFactory(dataset=dataset, data={"year": "2021"})
    null = CitationFactory(dataset=dataset, data={name: None})
    unrelated = CitationFactory(data={"year": "2022"})

    migration_name = "0030_citation_doi"
    apps = (
        MigrationLoader(connection)
        .project_state([("my_app", migration_name)])
        .apps
    )
    migration = import_module(f"my_app.migrations.{migration_name}")
    migration.move_doi_to_citations(apps, connection.schema_editor())

    populated.refresh_from_db()
    assert populated.doi == "10.1234/example"
    assert populated.data == {"year": "2020"}
    for citation in (empty, missing, null, unrelated):
        original_data = citation.data.copy()
        original_data.pop(name, None)
        citation.refresh_from_db()
        assert citation.doi == ""
        assert citation.data == original_data
    assert list(dataset.columns.all()) == [year]
    assert list(dataset.screening_columns.all()) == [year]
