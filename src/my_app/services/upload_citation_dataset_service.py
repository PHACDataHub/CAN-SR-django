from abc import ABC, abstractmethod
import itertools
import csv
import io
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction

from my_app.models import (
    CitationDataset,
    CitationDatasetCell,
    CitationDatasetColumn,
    CitationDatasetRow,
)


@dataclass(frozen=True)
class CitationDatasetImportResult:
    dataset: CitationDataset
    row_count: int
    column_count: int


class CitationDatasetImportSource(ABC):
    @abstractmethod
    def get_column_names(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def iter_row_values(self) -> Iterable[tuple[str, ...]]:
        raise NotImplementedError


class CsvCitationDatasetImportSource(CitationDatasetImportSource):
    def __init__(self, column_names, row_values):
        self._column_names = column_names
        self._row_values = row_values

    @classmethod
    def from_input(cls, csv_input):
        if hasattr(csv_input, "read"):
            content = csv_input.read()
        else:
            content = csv_input

        if isinstance(content, bytes):
            csv_text = content.decode("utf-8-sig")
        else:
            csv_text = content

        if not csv_text:
            raise ValueError("CSV file is empty.")

        reader = csv.reader(io.StringIO(csv_text), skipinitialspace=True)
        try:
            headers = [header.strip() for header in next(reader)]
        except StopIteration as exc:
            raise ValueError("CSV file is empty.") from exc

        if not headers or any(not header for header in headers):
            raise ValueError("CSV header row must include column names.")

        row_values = [
            tuple(row) for row in reader if any(cell.strip() for cell in row)
        ]
        return cls(headers, row_values)

    def get_column_names(self) -> list[str]:
        return self._column_names

    def iter_row_values(self) -> Iterable[tuple[str, ...]]:
        return iter(self._row_values)


class CitationDatasetImporter:
    def __init__(self, systematic_review, source):
        self.systematic_review = systematic_review
        self.source = source

    def run(self):
        column_names = list(self.source.get_column_names())
        if not column_names or any(not name for name in column_names):
            raise ValueError("CSV header row must include column names.")

        row_values = [list(row) for row in self.source.iter_row_values()]

        with transaction.atomic():
            dataset = CitationDataset.objects.create(
                systematic_review=self.systematic_review
            )
            columns = [
                CitationDatasetColumn(
                    dataset=dataset,
                    name=column_name,
                )
                for column_name in column_names
            ]
            CitationDatasetColumn.objects.bulk_create(columns)

            rows = []
            for order, values in enumerate(row_values, start=1):
                if len(values) != len(columns):
                    raise ValueError(
                        "CSV rows must have the same number of values as the header."
                    )

                rows.append(
                    CitationDatasetRow(
                        dataset=dataset,
                        order=order,
                    )
                )

            CitationDatasetRow.objects.bulk_create(rows)

            cells = self._get_cell_iterator(rows, columns, row_values)
            # separate cells in chunks of 200 to avoid memory issues
            # ~2600 cells (100x26) takes 1.5s in local dev,
            #   other tested chunk sizes seem slower
            # may have to move to background task if slow
            # and/or, use json-based rows instead of 1 record per cell
            for chunk_of_cells in itertools.batched(cells, 200):
                CitationDatasetCell.objects.bulk_create(chunk_of_cells)

        return CitationDatasetImportResult(
            dataset=dataset,
            row_count=len(rows),
            column_count=len(columns),
        )

    def _get_cell_iterator(self, rows, columns, row_values):
        # since we have cell-level records
        # we deal with a huge amount of memory
        # so we use a lazy iterator to chunk them
        for row, values in zip(rows, row_values):
            for column, value in zip(columns, values):
                yield CitationDatasetCell(
                    row=row,
                    column=column,
                    value=value,
                )


def build_citation_dataset_from_source(systematic_review, source):
    return CitationDatasetImporter(systematic_review, source).run()


def import_citation_dataset(systematic_review, csv_input):
    source = CsvCitationDatasetImportSource.from_input(csv_input)
    return build_citation_dataset_from_source(systematic_review, source)
