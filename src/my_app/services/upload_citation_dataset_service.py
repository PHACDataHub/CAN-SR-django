import csv
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction

from my_app.models import Citation, CitationDataset, CitationDatasetColumn


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
    def __init__(self, review, source):
        self.review = review
        self.source = source

    def run(self):
        column_names = list(self.source.get_column_names())
        if not column_names or any(not name.strip() for name in column_names):
            raise ValueError("CSV header row must include column names.")

        row_values = [list(row) for row in self.source.iter_row_values()]
        column_specs = self._get_column_specs(column_names)

        with transaction.atomic():
            dataset = CitationDataset.objects.create(review=self.review)
            columns = [
                CitationDatasetColumn(
                    dataset=dataset,
                    name=column_spec["name"],
                )
                for column_spec in column_specs["data_columns"]
            ]
            CitationDatasetColumn.objects.bulk_create(columns)

            rows = []
            for order, values in enumerate(row_values, start=1):
                if len(values) != len(column_names):
                    raise ValueError(
                        "CSV rows must have the same number of values as the header."
                    )

                rows.append(
                    Citation(
                        dataset=dataset,
                        order=order,
                        title=self._get_special_value(
                            values, column_specs["title_index"]
                        ),
                        abstract=self._get_special_value(
                            values, column_specs["abstract_index"]
                        ),
                        data={
                            column_spec["name"]: values[column_spec["index"]]
                            for column_spec in column_specs["data_columns"]
                        },
                    )
                )

            Citation.objects.bulk_create(rows)

        return CitationDatasetImportResult(
            dataset=dataset,
            row_count=len(rows),
            column_count=len(columns),
        )

    def _get_column_specs(self, column_names):
        special_indices = {"title": None, "abstract": None}
        data_columns = []

        for index, column_name in enumerate(column_names):
            clean_name = column_name.strip()
            normalized_name = clean_name.casefold()
            if (
                normalized_name in special_indices
                and special_indices[normalized_name] is None
            ):
                special_indices[normalized_name] = index
                continue

            data_columns.append(
                {
                    "index": index,
                    "name": clean_name,
                }
            )

        return {
            "title_index": special_indices["title"],
            "abstract_index": special_indices["abstract"],
            "data_columns": data_columns,
        }

    def _get_special_value(self, values, index):
        if index is None:
            return ""

        return values[index]


def build_citation_dataset_from_source(review, source):
    return CitationDatasetImporter(review, source).run()


def import_citation_dataset(review, csv_input):
    source = CsvCitationDatasetImportSource.from_input(csv_input)
    return build_citation_dataset_from_source(review, source)
