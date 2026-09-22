import csv
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction
from django.db.models import Max

import rispy

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


class RisCitationDatasetImportSource(CitationDatasetImportSource):
    def __init__(self, column_names, row_values):
        self._column_names = column_names
        self._row_values = row_values

    @classmethod
    def from_input(cls, ris_input):
        content = ris_input
        if hasattr(ris_input, "read"):
            content = ris_input.read()

        try:
            ris_text = content
            if isinstance(content, bytes):
                ris_text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("RIS file must be UTF-8 encoded.") from exc

        if not ris_text or not ris_text.strip():
            raise ValueError("RIS file is empty.")

        entries = rispy.load(io.StringIO(ris_text))
        if not entries:
            raise ValueError("RIS file contains no citations.")

        rows = [cls._normalize_entry(entry) for entry in entries]
        column_names = list(dict.fromkeys(key for row in rows for key in row))
        row_values = [
            tuple(row.get(name, "") for name in column_names) for row in rows
        ]
        return cls(column_names, row_values)

    @staticmethod
    def _normalize_entry(entry):
        row = {
            key: RisCitationDatasetImportSource._format_value(value)
            for key, value in entry.items()
        }
        for alternate, canonical in (
            ("primary_title", "title"),
            ("notes_abstract", "abstract"),
        ):
            if canonical not in row and alternate in row:
                row[canonical] = row.pop(alternate)
        return row

    @staticmethod
    def _format_value(value):
        if isinstance(value, list):
            return "; ".join(value)
        return str(value)

    def get_column_names(self) -> list[str]:
        return self._column_names

    def iter_row_values(self) -> Iterable[tuple[str, ...]]:
        return iter(self._row_values)


class CitationDatasetImporter:
    def __init__(self, review, source, mappings=None):
        self.review = review
        self.source = source
        self.mappings = mappings

    def run(self):
        column_names = list(self.source.get_column_names())
        if not column_names or any(not name.strip() for name in column_names):
            raise ValueError("CSV header row must include column names.")

        row_values = [list(row) for row in self.source.iter_row_values()]
        mapped_names = self.mappings
        if mapped_names is None:
            mapped_names = column_names
        if len(mapped_names) != len(column_names):
            raise ValueError("Every uploaded column must have a mapping.")
        for values in row_values:
            if len(values) != len(column_names):
                raise ValueError(
                    "CSV rows must have the same number of values as the header."
                )

        with transaction.atomic():
            dataset, _ = CitationDataset.objects.get_or_create(
                review=self.review
            )
            dataset = CitationDataset.objects.select_for_update().get(
                pk=dataset.pk
            )
            existing_by_name = {
                name.casefold(): name
                for name in dataset.columns.values_list("name", flat=True)
            }
            canonical_names = [
                (
                    existing_by_name.get(name.strip().casefold(), name)
                    if name is not None
                    else None
                )
                for name in mapped_names
            ]
            column_specs = self._get_column_specs(canonical_names)
            columns = [
                CitationDatasetColumn(
                    dataset=dataset,
                    name=column_spec["name"],
                )
                for column_spec in column_specs["data_columns"]
                if column_spec["name"].casefold() not in existing_by_name
            ]
            CitationDatasetColumn.objects.bulk_create(columns)

            rows = []
            first_order = (
                dataset.rows.aggregate(Max("order"))["order__max"] or 0
            ) + 1
            for order, values in enumerate(row_values, start=first_order):
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
            column_count=len(column_specs["data_columns"]),
        )

    def _get_column_specs(self, column_names):
        special_indices = {"title": None, "abstract": None}
        data_columns = []

        used_names = set()
        for index, column_name in enumerate(column_names):
            if column_name is None:
                continue
            clean_name = column_name.strip()
            if not clean_name:
                raise ValueError("Mapped column names cannot be blank.")
            normalized_name = clean_name.casefold()
            if normalized_name in used_names:
                raise ValueError(
                    "Multiple uploaded columns map to the same dataset column."
                )
            used_names.add(normalized_name)
            if normalized_name in special_indices:
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


def parse_citation_dataset_source(citation_input, format="csv"):
    if format == "csv":
        source = CsvCitationDatasetImportSource.from_input(citation_input)
    elif format == "ris":
        source = RisCitationDatasetImportSource.from_input(citation_input)
    else:
        raise ValueError("Unsupported citation format.")
    return source


def import_citation_dataset(
    review, citation_input, format="csv", mappings=None
):
    source = parse_citation_dataset_source(citation_input, format)
    return CitationDatasetImporter(review, source, mappings=mappings).run()
