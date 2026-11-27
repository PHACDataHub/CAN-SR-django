from dataclasses import dataclass
from datetime import datetime, timezone

from django.db.models import DateTimeField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Greatest, NullIf

import htpy as h

from my_app.models import (
    Citation,
    L1CriticalScreeningResult,
    L1HumanAnswer,
    L1ScreeningResult,
    L2CriticalScreeningResult,
    L2HumanAnswer,
    L2ScreeningResult,
)
from shortcuts import reverse, tdt

from .common import (
    AnnotateCitationStatuses,
    CitationIDColumn,
    DetailColumn,
    ReviewTableDef,
    StatusColumns,
)
from .table_framework import (
    AbbreviatedAttributeColumn,
    DateTimeAttributeColumn,
)


class CitationTitleColumn(AbbreviatedAttributeColumn):
    def render_cell(self, record):
        title = super().render_cell(record) or tdt("Untitled citation")
        return f"#{record.pk} {title}"


@dataclass
class CitationTitleLinkColumn(CitationTitleColumn):
    review_id: int = None

    def render_cell(self, record):
        return h.a(
            href=reverse("citation_detail", args=[self.review_id, record.pk])
        )[super().render_cell(record)]


class CitationDatasetTableDef(ReviewTableDef):
    title = tdt("Dataset")
    default_ordering = ("order", "pk")

    def get_title_column(self):
        return CitationTitleLinkColumn(
            "title", tdt("Title"), sort_field="title", review_id=self.review.pk
        )

    def get_citation_columns(self):
        return [
            CitationIDColumn(
                "id",
                tdt("Citation ID"),
                sort_field="pk",
                default_enabled=False,
            ),
            self.get_title_column(),
            AbbreviatedAttributeColumn("abstract", tdt("Abstract")),
            AbbreviatedAttributeColumn("doi", tdt("DOI")),
        ]

    def get_columns(self):
        return [*self.get_citation_columns(), *self.dataset_columns()]

    def get_base_queryset(self):
        return Citation.objects.filter(dataset__review=self.review)


class CitationTableDef(CitationDatasetTableDef):
    title = tdt("Citations")

    def get_title_column(self):
        return CitationTitleColumn("title", tdt("Title"), sort_field="title")

    def get_columns(self):
        return [
            *self.get_citation_columns(),
            *StatusColumns(filters=True),
            DateTimeAttributeColumn(
                "last_updated",
                tdt("Last updated"),
                sort_field="last_updated",
                default_enabled=False,
            ),
            *self.dataset_columns(),
            DetailColumn(),
        ]

    def annotate_queryset(self, queryset):
        keys = {column.key for column in self.enabled_columns}
        queryset = AnnotateCitationStatuses(queryset, keys)
        if "last_updated" in keys:
            epoch = Value(
                datetime(1970, 1, 1, tzinfo=timezone.utc),
                output_field=DateTimeField(),
            )
            latest_updates = [
                Coalesce(
                    Subquery(
                        model.objects.filter(**{lookup: OuterRef("pk")})
                        .order_by("-updated_at")
                        .values("updated_at")[:1]
                    ),
                    epoch,
                )
                for model, lookup in (
                    (L1ScreeningResult, "citation_id"),
                    (L2ScreeningResult, "citation_id"),
                    (L1HumanAnswer, "citation_id"),
                    (L2HumanAnswer, "citation_id"),
                    (L1CriticalScreeningResult, "initial_result__citation_id"),
                    (L2CriticalScreeningResult, "initial_result__citation_id"),
                )
            ]
            queryset = queryset.annotate(
                last_updated=NullIf(Greatest(*latest_updates), epoch)
            )
        return queryset
