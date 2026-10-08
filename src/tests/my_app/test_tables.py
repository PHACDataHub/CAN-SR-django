from django.db import connection
from django.http import QueryDict
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

import pytest
from freezegun import freeze_time
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetColumnFactory,
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningResultFactory,
    L2HumanAnswerFactory,
    L2ScreeningResultFactory,
    ReviewFactory,
)
from my_app.models import (
    Citation,
    CitationHumanStatus,
    L1CriticalScreeningResult,
    ScreeningActions,
    ScreeningResultStatus,
)
from my_app.tables.ai_answer_table import L1AIAnswerTableDef
from my_app.tables.citation_table import CitationTableDef
from my_app.tables.table_framework import AttributeColumn, TableDef, TableView

TABLE_ROUTES = [
    "citation_table",
    "l1_ai_answer_table",
    "l2_ai_answer_table",
    "l1_human_answer_table",
    "l2_human_answer_table",
]


def selection(*columns, **params):
    data = QueryDict(mutable=True)
    data["column_selection_form-submitted"] = "True"
    data.setlist("column_selection_form-columns", columns)
    data.update(params)
    return data


@pytest.mark.parametrize("route", TABLE_ROUTES)
def test_table_access_and_navigation(vanilla_client, route):
    review = ReviewFactory()
    url = reverse(route, args=[review.pk])
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
    assert response.status_code == 200
    for name in TABLE_ROUTES:
        assert reverse(name, args=[review.pk]) in response.content.decode()


def test_review_links_to_tables(vanilla_client):
    review = ReviewFactory()
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse("review_detail", args=[review.pk])
        )
    for name in TABLE_ROUTES:
        assert reverse(name, args=[review.pk]) in response.content.decode()


def test_citation_defaults_and_dataset_selection(vanilla_client):
    citation = CitationFactory(data={"Journal": "Journal example"})
    dataset_column = CitationDatasetColumnFactory(
        dataset=citation.dataset, name="Journal"
    )
    table = CitationTableDef(review=citation.dataset.review)
    key = f"dataset_{dataset_column.pk}"
    assert key not in {column.key for column in table.enabled_columns}
    assert len(table.filter_forms) == 6
    assert "view" not in {column.key for column in table.export_columns}
    url = reverse("citation_table", args=[citation.dataset.review_id])
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url, selection(key))
        empty = vanilla_client.get(url, selection())
    assert [column.key for column in response.context["columns"]] == [
        key,
        "view",
    ]
    assert "Journal example" in response.content.decode()
    assert not response.context["filter_forms"]
    assert [column.key for column in empty.context["columns"]] == ["view"]


def test_citation_filter_only_applies_to_enabled_columns(vanilla_client):
    first = CitationFactory()
    other = CitationFactory(dataset=first.dataset)
    answer = L1HumanAnswerFactory(citation=first)
    answer.selected_option.screening_action = ScreeningActions.ScreenIn
    answer.selected_option.save()
    params = {"filter_form_l1_human_status-status": CitationHumanStatus.In}
    url = reverse("citation_table", args=[first.dataset.review_id])
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            url, selection("title", "l1_human_status", **params)
        )
        disabled = vanilla_client.get(url, selection("title", **params))
    assert [row.pk for row in response.context["page_obj"]] == [first.pk]
    assert {row.pk for row in disabled.context["page_obj"]} == {
        first.pk,
        other.pk,
    }
    assert (
        'name="filter_form_l1_human_status-status"'
        not in disabled.content.decode()
    )


def test_sort_and_invalid_inputs(vanilla_client):
    first = CitationFactory(title="A")
    last = CitationFactory(dataset=first.dataset, title="Z")
    url = reverse("citation_table", args=[first.dataset.review_id])
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            url,
            selection(
                "title",
                **{"sort_form-column": "title", "sort_form-direction": "desc"},
            ),
        )
        invalid = vanilla_client.get(
            url, selection("title", **{"sort_form-column": "arbitrary_sql"})
        )
    assert [row.pk for row in response.context["page_obj"]] == [
        last.pk,
        first.pk,
    ]
    assert invalid.status_code == 200
    assert invalid.context["sort_form"].errors


def test_pagination_preserves_multiple_selections(vanilla_client):
    citation = CitationFactory()
    CitationFactory.create_batch(25, dataset=citation.dataset)
    CitationFactory()
    url = reverse("citation_table", args=[citation.dataset.review_id])
    params = selection(
        "title",
        "l1_ai_status",
        **{"sort_form-column": "title", "sort_form-direction": "asc"},
    )
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url, params)
        params["page"] = 2
        second = vanilla_client.get(url, params)
    assert len(response.context["page_obj"]) == 25
    assert len(second.context["page_obj"]) == 1
    content = response.content.decode()
    assert (
        "column_selection_form-columns=title&amp;column_selection_form-columns=l1_ai_status"
        in content
    )
    assert "sort_form-column=title" in content


@pytest.mark.parametrize(
    "route,factory",
    [
        ("l1_ai_answer_table", L1ScreeningResultFactory),
        ("l2_ai_answer_table", L2ScreeningResultFactory),
        ("l1_human_answer_table", L1HumanAnswerFactory),
        ("l2_human_answer_table", L2HumanAnswerFactory),
    ],
)
def test_answer_tables_are_review_scoped(vanilla_client, route, factory):
    record = factory()
    foreign = factory()
    factory(citation=record.citation, question=foreign.question)
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(route, args=[record.citation.dataset.review_id])
        )
    assert response.status_code == 200
    assert [row.pk for row in response.context["page_obj"]] == [record.pk]
    table = response.context["table_def"]
    assert not any(
        column.key.startswith("dataset_") for column in table.columns
    )
    question_column = next(
        column for column in table.columns if column.key == "question"
    )
    assert question_column.render_cell(record) == record.question.question_text


def test_joined_answer_fields_and_latest_human(vanilla_client):
    result = L1ScreeningResultFactory(explanation="AI explanation here")
    L1CriticalScreeningResult.objects.create(
        initial_result=result,
        status=ScreeningResultStatus.COMPLETED,
        confidence=0.93,
    )
    with freeze_time("2026-01-01"):
        L1HumanAnswerFactory(
            citation=result.citation,
            question=result.question,
            notes="Old human notes",
        )
    with freeze_time("2026-01-02"):
        L1HumanAnswerFactory(
            citation=result.citation,
            question=result.question,
            notes="Latest human notes",
        )
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(
            reverse(
                "l1_ai_answer_table", args=[result.citation.dataset.review_id]
            )
        )
    content = response.content.decode()
    assert "Latest human notes" in content
    assert "Old human notes" not in content
    assert "AI explanation here" in content
    assert "0.93" in content
    assert (
        reverse(
            "l1_answer_detail_modal",
            args=[result.citation_id, result.question_id],
        )
        in content
    )


def test_answer_loading_is_batched():
    result = L1ScreeningResultFactory()
    table = L1AIAnswerTableDef(review=result.citation.dataset.review)
    with CaptureQueriesContext(connection) as single_queries:
        records = list(table.get_queryset())
        table.prepare_page(records)
        for record in records:
            for column in table.enabled_columns:
                column.render_cell(record)
    L1ScreeningResultFactory.create_batch(20, citation=result.citation)
    with CaptureQueriesContext(connection) as many_queries:
        records = list(table.get_queryset())
        table.prepare_page(records)
        for record in records:
            for column in table.enabled_columns:
                column.render_cell(record)
    assert len(many_queries) == len(single_queries)


def test_citation_last_updated_handles_missing_related_records():
    citation = CitationFactory()
    with freeze_time("2026-01-01"):
        result = L1ScreeningResultFactory(citation=citation)
    with freeze_time("2026-01-03"):
        critical = L1CriticalScreeningResult.objects.create(
            initial_result=result
        )
    empty = CitationFactory(dataset=citation.dataset)
    table = CitationTableDef(
        review=citation.dataset.review, data=selection("last_updated")
    )
    rows = {row.pk: row for row in table.get_queryset()}
    assert rows[citation.pk].last_updated == critical.updated_at
    assert rows[empty.pk].last_updated is None


@pytest.mark.parametrize(
    "route,factory",
    [
        ("citation_detail_modal", None),
        ("l1_answer_detail_modal", L1ScreeningResultFactory),
        ("l2_answer_detail_modal", L2ScreeningResultFactory),
    ],
)
def test_detail_modals_access_and_cross_review(vanilla_client, route, factory):
    citation = CitationFactory()
    args = [citation.pk]
    if factory:
        result = factory(citation=citation)
        args.append(result.question_id)
    url = reverse(route, args=args)
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
        assert response.status_code == 200
        assert b"data-modal" in response.content
        if factory:
            foreign = factory()
            assert (
                vanilla_client.get(
                    reverse(route, args=[citation.pk, foreign.question_id])
                ).status_code
                == 404
            )


def test_framework_can_paginate_union_queryset():
    first = CitationFactory()
    second = CitationFactory(dataset=first.dataset)

    class UnionTable(TableDef):
        columns = [AttributeColumn("title", "Title", sort_field="title")]

        def get_base_queryset(self):
            return (
                Citation.objects.filter(pk=first.pk)
                .order_by()
                .union(Citation.objects.filter(pk=second.pk).order_by())
            )

    class UnionView(TableView):
        table_def_class = UnionTable
        paginate_by = 1

    view = UnionView()
    view.setup(RequestFactory().get("/", {"sort_form-column": "title"}))
    queryset = view.get_queryset()
    paginator, page, records, is_paginated = view.paginate_queryset(
        queryset, 1
    )
    assert paginator.count == 2
    assert len(records) == 1
    assert is_paginated


@pytest.mark.parametrize("length", [0, 100, 101, 250])
def test_abbreviated_columns_preserve_full_export_text(length):
    from types import SimpleNamespace

    from my_app.tables.table_framework import AbbreviatedAttributeColumn

    text = ("A" * 50 + "middle" * 30 + "Z" * 50)[:length]
    column = AbbreviatedAttributeColumn(
        "text", "Text", null_fallback="Missing"
    )
    record = SimpleNamespace(text=text)
    expected = text
    if length > 100:
        expected = text[:50] + "…" + text[-50:]
    assert column.render_cell(record) == expected
    assert column.render_plaintext_cell(record) == text
    assert column.render_cell(SimpleNamespace(text=None)) == "Missing"


def test_choice_and_datetime_attribute_columns():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from my_app.tables.table_framework import (
        AttributeColumn,
        ChoiceAttributeColumn,
        DateTimeAttributeColumn,
    )

    record = SimpleNamespace(
        status=CitationHumanStatus.Unanswered,
        timestamp=datetime(
            2026, 10, 8, 13, 14, 15, 123456, tzinfo=timezone.utc
        ),
    )
    assert (
        AttributeColumn("status", "Status").render_cell(record) == "unanswered"
    )
    choice = ChoiceAttributeColumn(
        "status", "Status", choices=CitationHumanStatus
    )
    assert choice.render_cell(record) == CitationHumanStatus.Unanswered.label
    timestamp = DateTimeAttributeColumn("timestamp", "Timestamp")
    assert timestamp.render_cell(record) == "2026-10-08 13:14:15"
    assert timestamp.render_cell(SimpleNamespace(timestamp=None)) == ""


def test_status_filters_have_distinct_labels():
    table = CitationTableDef(review=ReviewFactory())
    labels = [
        form.fields["status"].label for form in table.filter_forms.values()
    ]
    assert len(set(labels)) == 6
    assert labels == [
        column.render_plaintext_header()
        for column in table.enabled_columns
        if column.key in table.filter_forms
    ]
