from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

import pytest
from phac_aspc.rules import patch_rules

from my_app.model_factories import (
    CitationDatasetColumnFactory,
    CitationFactory,
    L1HumanAnswerFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
)
from my_app.models import L1HumanAnswer, L2HumanAnswer
from my_app.services.create_human_answers import create_human_answers


@pytest.fixture
def mapping():
    column = CitationDatasetColumnFactory(name="Answer")
    question = L1ScreeningQuestionFactory(
        review=column.dataset.review, disable_screening=True
    )
    option = L1ScreeningQuestionOptionFactory(
        question=question, option_text="Not applicable"
    )
    return column.dataset.review, column, question, option


@pytest.mark.parametrize("stage", [1, 2])
def test_create_edit_clear_and_preserve_named_users(mapping, stage):
    review, column, question, option = mapping
    model = L1HumanAnswer
    factory = L1HumanAnswerFactory
    option_factory = L1ScreeningQuestionOptionFactory
    if stage == 2:
        question = L2ScreeningQuestionFactory(
            review=review, disable_screening=True
        )
        option_factory = L2ScreeningQuestionOptionFactory
        option = option_factory(
            question=question, option_text="Not applicable"
        )
        model = L2HumanAnswer
        factory = L2HumanAnswerFactory
    citation = CitationFactory(
        dataset=column.dataset,
        data={"Answer": " nOt\tApplicable\n"},
        document=None,
    )
    named = factory(
        citation=citation,
        question=question,
        selected_option=option,
        notes="Keep me",
    )
    create_human_answers(review, [(question, column)])
    answer = model.objects.get(user=None)
    assert answer.selected_option_id == option.pk
    assert answer.citation_id == citation.pk
    other = option_factory(question=question, option_text="Yes")
    citation.data = {"Answer": "YES"}
    citation.save()
    duplicate = factory(
        citation=citation, question=question, selected_option=option, user=None
    )
    create_human_answers(review, [(question, column)])
    answer.refresh_from_db()
    duplicate.refresh_from_db()
    assert (
        answer.selected_option_id == duplicate.selected_option_id == other.pk
    )
    citation.data = {"Answer": " \n\t"}
    citation.save()
    create_human_answers(review, [(question, column)])
    answer.refresh_from_db()
    duplicate.refresh_from_db()
    named.refresh_from_db()
    assert answer.selected_option_id is None
    assert duplicate.selected_option_id is None
    assert named.selected_option_id == option.pk
    assert named.notes == "Keep me"


@pytest.mark.parametrize(
    "data", [{}, {"Answer": None}, {"Answer": ""}, {"Answer": " \t\n"}]
)
def test_empty_values_do_not_create_answers(mapping, data):
    review, column, question, _ = mapping
    CitationFactory(dataset=column.dataset, data=data)
    create_human_answers(review, [(question, column)])
    assert not L1HumanAnswer.objects.exists()


def test_validation_reports_all_values_and_aborts_both_stages(mapping):
    review, column, question, option = mapping
    second_column = CitationDatasetColumnFactory(
        dataset=column.dataset, name="L2"
    )
    second_question = L2ScreeningQuestionFactory(review=review)
    L2ScreeningQuestionOptionFactory(
        question=second_question, option_text="Yes"
    )
    for value in ("Bad", "Other"):
        CitationFactory(
            dataset=column.dataset,
            data={"Answer": "Not applicable", "L2": value},
        )
    with pytest.raises(ValidationError) as error:
        create_human_answers(
            review, [(question, column), (second_question, second_column)]
        )
    assert "Bad" in str(error.value)
    assert "Other" in str(error.value)
    assert not L1HumanAnswer.objects.exists()
    assert not L2HumanAnswer.objects.exists()


def test_invalid_values_do_not_modify_existing_answers(mapping):
    review, column, question, option = mapping
    citation = CitationFactory(
        dataset=column.dataset, data={"Answer": "invalid"}
    )
    answer = L1HumanAnswerFactory(
        citation=citation, question=question, selected_option=option, user=None
    )
    with pytest.raises(ValidationError):
        create_human_answers(review, [(question, column)])
    answer.refresh_from_db()
    assert answer.selected_option_id == option.pk


def test_mirrored_answers_are_created_updated_and_cleared(mapping):
    review, column, question, option = mapping
    mirror = question.sync_to_l2()
    mirrored_option = option.sync_to_l2()
    L2ScreeningQuestionOptionFactory(question=mirror, l1_option=None)
    citation = CitationFactory(
        dataset=column.dataset, data={"Answer": "notapplicable"}
    )
    named = L2HumanAnswerFactory(
        citation=citation, question=mirror, selected_option=mirrored_option
    )
    create_human_answers(review, [(question, column)])
    answer = L2HumanAnswer.objects.get(user=None)
    assert answer.question_id == mirror.pk
    assert answer.selected_option_id == mirrored_option.pk
    other = L1ScreeningQuestionOptionFactory(
        question=question, option_text="Yes"
    )
    mirrored_other = other.sync_to_l2()
    citation.data = {"Answer": "yes"}
    citation.save()
    create_human_answers(review, [(question, column)])
    answer.refresh_from_db()
    assert answer.selected_option_id == mirrored_other.pk
    citation.data = {}
    citation.save()
    create_human_answers(review, [(question, column)])
    answer.refresh_from_db()
    named.refresh_from_db()
    assert answer.selected_option_id is None
    assert named.selected_option_id == mirrored_option.pk


def test_missing_or_deleted_mirror_option_aborts(mapping):
    review, column, question, option = mapping
    question.sync_to_l2()
    CitationFactory(dataset=column.dataset, data={"Answer": "notapplicable"})
    with pytest.raises(ValidationError, match="mirrored options"):
        create_human_answers(review, [(question, column)])
    assert not L1HumanAnswer.objects.exists()


def test_deleted_options_are_excluded_and_ambiguous_labels_rejected(mapping):
    review, column, question, option = mapping
    citation = CitationFactory(
        dataset=column.dataset, data={"Answer": "notapplicable"}
    )
    option.soft_delete()
    with pytest.raises(ValidationError, match="unmatched"):
        create_human_answers(review, [(question, column)])
    replacement = L1ScreeningQuestionOptionFactory(
        question=question, option_text="Not applicable"
    )
    create_human_answers(review, [(question, column)])
    assert L1HumanAnswer.objects.get().selected_option_id == replacement.pk
    L1ScreeningQuestionOptionFactory(
        question=question, option_text="NOTAPPLICABLE"
    )
    with pytest.raises(ValidationError, match="ambiguous"):
        create_human_answers(review, [(question, column)])


def test_service_rejects_foreign_and_deleted_questions_and_columns(mapping):
    review, column, question, option = mapping
    foreign_column = CitationDatasetColumnFactory()
    foreign_question = L1ScreeningQuestionFactory()
    for pair in ((question, foreign_column), (foreign_question, column)):
        with pytest.raises(ValidationError, match="does not belong"):
            create_human_answers(review, [pair])
    question.soft_delete()
    with pytest.raises(ValidationError, match="does not belong"):
        create_human_answers(review, [(question, column)])


def test_service_rejects_explicit_mirror_mapping(mapping):
    review, column, question, _ = mapping
    mirror = question.sync_to_l2()
    with pytest.raises(ValidationError, match="through L1"):
        create_human_answers(review, [(mirror, column)])


def test_no_mappings_is_noop(mapping):
    review, _, _, _ = mapping
    with CaptureQueriesContext(connection) as queries:
        create_human_answers(review, [])
    assert len(queries) == 2  # transaction savepoint only


def test_read_query_count_does_not_grow_with_questions_or_citations(mapping):
    review, column, question, _ = mapping
    CitationFactory(dataset=column.dataset, data={"Answer": "notapplicable"})
    with CaptureQueriesContext(connection) as queries:
        create_human_answers(review, [(question, column)])
    initial_reads = sum(query["sql"].startswith("SELECT") for query in queries)
    mappings = [(question, column)]
    for _ in range(20):
        other = L1ScreeningQuestionFactory(review=review)
        L1ScreeningQuestionOptionFactory(
            question=other, option_text="Not applicable"
        )
        mappings.append((other, column))
        CitationFactory(
            dataset=column.dataset, data={"Answer": "notapplicable"}
        )
    with CaptureQueriesContext(connection) as queries:
        create_human_answers(review, mappings)
    assert (
        sum(query["sql"].startswith("SELECT") for query in queries)
        == initial_reads
    )
    assert L1HumanAnswer.objects.count() == 21 * 21
    create_human_answers(review, mappings)
    assert L1HumanAnswer.objects.count() == 21 * 21


def post_data(column=None):
    data = {
        "l1-TOTAL_FORMS": "1",
        "l1-INITIAL_FORMS": "1",
        "l2-TOTAL_FORMS": "0",
        "l2-INITIAL_FORMS": "0",
        "l1-0-column": "",
    }
    if column is not None:
        data["l1-0-column"] = str(column.pk)
    return data


def test_view_permissions_static_rows_and_link(vanilla_client, mapping):
    review, column, question, option = mapping
    question.sync_to_l2()
    deleted = L1ScreeningQuestionFactory(
        review=review, question_text="Deleted question"
    )
    deleted.soft_delete()
    foreign_column = CitationDatasetColumnFactory(name="Foreign column")
    url = reverse("create_human_answers", args=[review.pk])
    with patch_rules(can_access_review=False):
        assert vanilla_client.get(url).status_code == 403
        assert vanilla_client.post(url, post_data(column)).status_code == 403
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
        assert response.status_code == 200
        html = response.content.decode()
        assert question.question_text in html
        assert "Deleted question" not in html
        assert "Foreign column" not in html
        assert 'name="l1-0-column"' in html
        assert 'name="l2-0-column"' not in html
        criteria = vanilla_client.get(
            reverse("screening_criteria", args=[review.pk])
        )
        assert url in criteria.content.decode()


def test_view_good_empty_bad_and_foreign_posts(vanilla_client, mapping):
    review, column, question, option = mapping
    citation = CitationFactory(
        dataset=column.dataset, data={"Answer": "notapplicable"}
    )
    url = reverse("create_human_answers", args=[review.pk])
    with patch_rules(can_access_review=True):
        assert vanilla_client.post(url, post_data()).status_code == 302
        assert not L1HumanAnswer.objects.exists()
        assert vanilla_client.post(url, post_data(column)).status_code == 302
        assert L1HumanAnswer.objects.get().selected_option_id == option.pk
        citation.data = {"Answer": "invalid"}
        citation.save()
        response = vanilla_client.post(url, post_data(column))
        assert response.status_code == 200
        assert "invalid" in response.content.decode()
        assert response.context_data["formsets"][0].forms[0].data[
            "l1-0-column"
        ] == str(column.pk)
        response = vanilla_client.post(
            url, post_data(CitationDatasetColumnFactory())
        )
        assert response.status_code == 200
        assert response.context_data["formsets"][0].forms[0].errors
        data = post_data(column)
        data["l1-TOTAL_FORMS"] = "2"
        response = vanilla_client.post(url, data)
        assert response.status_code == 200
        assert "Reload" in response.content.decode()


def test_view_maps_both_stages_and_skips_empty_questions(
    vanilla_client, mapping
):
    review, column, question, option = mapping
    skipped = L1ScreeningQuestionFactory(review=review)
    second = L2ScreeningQuestionFactory(review=review)
    second_option = L2ScreeningQuestionOptionFactory(
        question=second, option_text="Not applicable"
    )
    citation = CitationFactory(
        dataset=column.dataset, data={"Answer": "notapplicable"}
    )
    data = post_data(column)
    data.update(
        {
            "l1-TOTAL_FORMS": "2",
            "l1-INITIAL_FORMS": "2",
            "l1-1-column": "",
            "l2-TOTAL_FORMS": "1",
            "l2-INITIAL_FORMS": "1",
            "l2-0-column": str(column.pk),
        }
    )
    with patch_rules(can_access_review=True):
        response = vanilla_client.post(
            reverse("create_human_answers", args=[review.pk]), data
        )
    assert response.status_code == 302
    assert L1HumanAnswer.objects.get().question_id == question.pk
    assert not L1HumanAnswer.objects.filter(question=skipped).exists()
    assert L2HumanAnswer.objects.get().selected_option_id == second_option.pk


def test_view_without_questions_or_dataset_has_csrf_and_accepts_noop(
    vanilla_client,
):
    from my_app.model_factories import ReviewFactory

    review = ReviewFactory()
    url = reverse("create_human_answers", args=[review.pk])
    data = {
        f"{prefix}-{field}": "0"
        for prefix in ("l1", "l2")
        for field in ("TOTAL_FORMS", "INITIAL_FORMS")
    }
    with patch_rules(can_access_review=True):
        response = vanilla_client.get(url)
        assert response.status_code == 200
        assert 'name="csrfmiddlewaretoken"' in response.content.decode()
        assert vanilla_client.post(url, data).status_code == 302
        assert vanilla_client.post(url, {}).status_code == 200


def test_validation_collects_errors_from_multiple_questions(mapping):
    review, column, question, option = mapping
    second_column = CitationDatasetColumnFactory(
        dataset=column.dataset, name="Other"
    )
    second_question = L2ScreeningQuestionFactory(review=review)
    L2ScreeningQuestionOptionFactory(
        question=second_question, option_text="Yes"
    )
    CitationFactory(
        dataset=column.dataset, data={"Answer": "bad L1", "Other": "bad L2"}
    )
    with pytest.raises(ValidationError) as error:
        create_human_answers(
            review, [(question, column), (second_question, second_column)]
        )
    assert "bad L1" in str(error.value)
    assert "bad L2" in str(error.value)
    assert not L1HumanAnswer.objects.exists()
    assert not L2HumanAnswer.objects.exists()


def test_deleted_mirrors_are_not_backfilled(mapping):
    review, column, question, option = mapping
    mirror = question.sync_to_l2()
    option.sync_to_l2()
    mirror.soft_delete()
    CitationFactory(dataset=column.dataset, data={"Answer": "notapplicable"})
    create_human_answers(review, [(question, column)])
    assert L1HumanAnswer.objects.count() == 1
    assert not L2HumanAnswer.objects.exists()
