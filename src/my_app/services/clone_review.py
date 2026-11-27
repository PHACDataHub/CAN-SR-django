from itertools import batched

from django.db import transaction

from proj.text import tdt

from my_app.models import (
    Citation,
    CitationDataset,
    CitationDatasetColumn,
    Document,
    Review,
)


@transaction.atomic
def clone_review(source, user):
    suffix = tdt(" (copy)")
    title_limit = Review._meta.get_field("title").max_length
    clone = Review.objects.create(
        title=source.title[: title_limit - len(suffix)] + suffix,
        description=source.description,
        language_model_id=source.language_model_id,
        disable_filtering=source.disable_filtering,
        confidence=source.confidence,
    )
    clone.users.add(user)

    for criteria, parent_field in (
        (source.l1_screening_questions, "question_id"),
        (source.l2_screening_questions, "question_id"),
        (source.parameters, "parameter_id"),
    ):
        _clone_criteria(criteria, clone, parent_field)

    if source_dataset := getattr(source, "citation_dataset", None):
        _clone_dataset(source_dataset, clone)

    return clone


def _clone_criteria(criteria, review, parent_field):
    for criterion in criteria.order_by("pk").prefetch_related("options"):
        cloned_criterion = _copy_criterion_row(criterion, review_id=review.pk)
        for option in sorted(criterion.options.all(), key=lambda row: row.pk):
            _copy_criterion_row(option, **{parent_field: cloned_criterion.pk})


def _copy_criterion_row(row, **parent):
    fields = {
        field.attname: getattr(row, field.attname)
        for field in row._meta.concrete_fields
        if not field.primary_key
    }
    return type(row).objects.create(**(fields | parent))


def _clone_dataset(source, review):
    dataset = CitationDataset.objects.create(review=review)
    columns = {
        column.pk: CitationDatasetColumn.objects.create(
            dataset=dataset, name=column.name
        )
        for column in source.columns.order_by("pk")
    }
    dataset.screening_columns.set(
        columns[pk]
        for pk in source.screening_columns.values_list("pk", flat=True)
        if pk in columns
    )

    # PDF replacement locks the citation before changing its document.
    rows = source.rows.select_for_update().iterator(chunk_size=500)
    documents = {}
    for batch in batched(rows, 500):
        document_ids = {row.document_id for row in batch if row.document_id}
        source_documents = (
            Document.objects.select_for_update()
            .filter(pk__in=document_ids.difference(documents))
            .order_by("pk")
        )
        for document in source_documents:
            documents[document.pk] = Document.objects.create(
                file=document.file.name
            )
        Citation.objects.bulk_create(
            [
                Citation(
                    dataset=dataset,
                    title=row.title,
                    abstract=row.abstract,
                    doi=row.doi,
                    data=row.data,
                    order=row.order,
                    document=documents.get(row.document_id),
                )
                for row in batch
            ]
        )
