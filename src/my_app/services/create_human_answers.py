from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from proj.text import tdt

from my_app.models import (
    Citation,
    CitationDatasetColumn,
    L1HumanAnswer,
    L1ScreeningQuestion,
    L2HumanAnswer,
    L2ScreeningQuestion,
)


def normalize_answer(value):
    if value is None:
        return ""
    return "".join(str(value).split()).casefold()


def option_lookup(question):
    lookup = {}
    for option in question.options.all():
        if option.deletion_time is not None:
            continue
        key = normalize_answer(option.option_text)
        if not key or key in lookup:
            raise ValidationError(
                tdt("Question has empty or ambiguous option labels: %s")
                % question.question_text
            )
        lookup[key] = option.pk
    return lookup


def load_questions(review):
    return {
        (model, question.pk): question
        for model in (L1ScreeningQuestion, L2ScreeningQuestion)
        for question in model.active_objects.filter(
            review=review
        ).prefetch_related("options")
    }


def prepare_selections(question, column, citations):
    lookup = option_lookup(question)
    raw_values = {
        citation.pk: citation.data.get(column.name) for citation in citations
    }
    normalized = {
        citation_id: normalize_answer(value)
        for citation_id, value in raw_values.items()
    }
    unmatched = {
        repr(str(raw_values[citation_id]))
        for citation_id, value in normalized.items()
        if value and value not in lookup
    }
    if unmatched:
        raise ValidationError(
            tdt("Question '%s', column '%s': unmatched values: %s")
            % (
                question.question_text,
                column.name,
                ", ".join(sorted(unmatched)),
            )
        )
    return {
        citation_id: lookup.get(value)
        for citation_id, value in normalized.items()
    }


def prepare_mirror_selections(mirror, selections):
    mirror_options = {
        option.l1_option_id: option.pk
        for option in mirror.options.all()
        if option.deletion_time is None and option.l1_option_id is not None
    }
    if any(
        option_id is not None and option_id not in mirror_options
        for option_id in selections.values()
    ):
        raise ValidationError(
            tdt("Missing active mirrored options for question: %s")
            % mirror.question_text
        )
    return {
        citation_id: mirror_options.get(option_id)
        for citation_id, option_id in selections.items()
    }


@transaction.atomic
def create_human_answers(review, mappings):
    """Backfill (question, dataset column) mappings, including L2 mirrors."""
    mappings = list(mappings)
    if not mappings:
        return
    questions = load_questions(review)
    mirrors = {
        question.l1_question_id: question
        for (model, _), question in questions.items()
        if model is L2ScreeningQuestion and question.l1_question_id is not None
    }
    columns = {
        column.pk: column
        for column in CitationDatasetColumn.objects.filter(
            dataset__review=review
        )
    }
    citations = list(
        Citation.objects.filter(dataset__review=review).only("id", "data")
    )
    plans = defaultdict(dict)
    errors = []
    for supplied_question, supplied_column in mappings:
        question = questions.get(
            (type(supplied_question), supplied_question.pk)
        )
        column = columns.get(supplied_column.pk)
        if question is None or column is None:
            raise ValidationError(
                tdt("Question or column does not belong to this review.")
            )
        if (
            isinstance(question, L2ScreeningQuestion)
            and question.l1_question_id
        ):
            raise ValidationError(
                tdt("Mirrored L2 questions must be mapped through L1.")
            )
        try:
            selections = prepare_selections(question, column, citations)
            answer_model = L1HumanAnswer
            if isinstance(question, L2ScreeningQuestion):
                answer_model = L2HumanAnswer
            plans[answer_model][question.pk] = selections
            if (
                isinstance(question, L1ScreeningQuestion)
                and question.pk in mirrors
            ):
                mirror = mirrors[question.pk]
                plans[L2HumanAnswer][mirror.pk] = prepare_mirror_selections(
                    mirror, selections
                )
        except ValidationError as error:
            errors.extend(error.messages)
    if errors:
        raise ValidationError(errors)
    for model, question_selections in plans.items():
        write_answers(model, question_selections, review)


def write_answers(model, question_selections, review):
    existing = list(
        model.objects.filter(
            user__isnull=True,
            question_id__in=question_selections,
            citation__dataset__review=review,
        )
    )
    keys = {(answer.question_id, answer.citation_id) for answer in existing}
    now = timezone.now()
    for answer in existing:
        answer.selected_option_id = question_selections[answer.question_id][
            answer.citation_id
        ]
        answer.updated_at = now
    model.objects.bulk_update(
        existing, ["selected_option", "updated_at"], batch_size=500
    )
    model.objects.bulk_create(
        [
            model(
                question_id=question_id,
                citation_id=citation_id,
                selected_option_id=option_id,
                user=None,
            )
            for question_id, selections in question_selections.items()
            for citation_id, option_id in selections.items()
            if option_id is not None and (question_id, citation_id) not in keys
        ],
        batch_size=500,
    )
