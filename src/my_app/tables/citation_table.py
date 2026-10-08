from datetime import datetime, timezone

from django.db.models import DateTimeField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Greatest, NullIf

from proj.text import tdt

from my_app.models import (
    Citation,
    L1CriticalScreeningResult,
    L1HumanAnswer,
    L1ScreeningResult,
    L2CriticalScreeningResult,
    L2HumanAnswer,
    L2ScreeningResult,
)

from .common import (
    AnnotateCitationStatuses,
    DetailColumn,
    ReviewTableDef,
    StatusColumns,
)
from .table_framework import (
    AbbreviatedAttributeColumn,
    AttributeColumn,
    DateTimeAttributeColumn,
)


class CitationTableDef(ReviewTableDef):
    title = tdt("Citations")
    default_ordering = ("order", "pk")

    def get_columns(self):
        return [
            AttributeColumn(
                "id",
                tdt("Citation ID"),
                sort_field="pk",
                default_enabled=False,
            ),
            AbbreviatedAttributeColumn(
                "title", tdt("Title"), sort_field="title"
            ),
            AbbreviatedAttributeColumn("abstract", tdt("Abstract")),
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

    def get_base_queryset(self):
        return Citation.objects.filter(dataset__review=self.review)

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
