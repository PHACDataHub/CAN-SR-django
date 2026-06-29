from dataclasses import dataclass
from typing import List

from django.db.models import Count, Q

from data_fetcher import DataFetcher
from data_fetcher.extras import cache_within_request as cached_within_request
from phac_aspc.vanilla import group_by

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningResult,
    LanguageModel,
    Parameter,
    ParameterExtractionResult,
    Review,
    ReviewUserLink,
    ScreeningResultStatus,
)
from shortcuts import logger


@cached_within_request
def get_model_for_review(review_id):
    review_model_id = Review.objects.values_list(
        "language_model_id", flat=True
    ).get(id=review_id)
    supported_models = LanguageModel.get_supported_models()

    if review_model_id is not None:
        selected_model = supported_models.filter(id=review_model_id).first()
        if selected_model is not None:
            return selected_model

        logger.error(
            "Review id=%s has unsupported or inactive language model id=%s; falling back to the default model",
            review_id,
            review_model_id,
        )

    return supported_models.filter(is_default=True).first()


@cached_within_request
def get_accessible_reviews(user_id):
    if not user_id:
        return []

    accessible_ids = ReviewUserLink.objects.filter(
        user_id=user_id
    ).values_list("review_id", flat=True)
    return list(
        Review.objects.filter(id__in=accessible_ids).order_by(
            "-created_at", "-id"
        )
    )


class ScreeningStatusFetcher(DataFetcher):
    """
    Assumes all citations in the same dataset
    """

    QuestionModel: type
    ResultModel: type

    @classmethod
    def batch_load_dict(cls, keys: List[int]):
        if not keys:
            return {}

        review = (
            Citation.objects.filter(id=keys[0])
            .select_related("dataset__review")
            .first()
            .dataset.review
        )
        all_questions = cls.get_questions(review)

        results = cls.ResultModel.objects.filter(citation_id__in=keys)

        results_by_citation = group_by(results, lambda r: r.citation_id)

        final_results = {}
        for citation_id in keys:
            citation_results = results_by_citation.get(citation_id, [])
            final_results[citation_id] = cls.status_for_results(
                citation_results, all_questions
            )

        return final_results

    @classmethod
    def get_questions(cls, review):
        return cls.QuestionModel.objects.filter(review=review)

    @staticmethod
    def status_for_results(results, questions):
        if not results:
            return ScreeningResultStatus.NOT_STARTED

        if all(
            result.status == ScreeningResultStatus.COMPLETED
            for result in results
        ):
            return ScreeningResultStatus.COMPLETED

        if any(
            result.status == ScreeningResultStatus.ABANDONED
            for result in results
        ):
            return ScreeningResultStatus.ABANDONED

        # if any are pending, return pending
        if any(
            result.status == ScreeningResultStatus.PENDING
            for result in results
        ):
            return ScreeningResultStatus.PENDING

        raise ValueError("Unexpected combination of screening result statuses")


class L1ScreeningStatusFetcher(ScreeningStatusFetcher):
    QuestionModel = L1ScreeningQuestion
    ResultModel = L1ScreeningResult


class L2ScreeningStatusFetcher(ScreeningStatusFetcher):
    QuestionModel = L2ScreeningQuestion
    ResultModel = L2ScreeningResult


class ParameterExtractionStatusFetcher(ScreeningStatusFetcher):
    QuestionModel = Parameter
    ResultModel = ParameterExtractionResult

    @classmethod
    def get_questions(cls, review):
        return cls.QuestionModel.objects.filter(category__review=review)


@dataclass(frozen=True)
class CitationScreeningProgressStats:
    total_citations: int
    incomplete_citations: int
    completed_not_human_reviewed_citations: int
    human_reviewed_citations: int

    @property
    def human_reviewed_percent(self):
        if self.total_citations == 0:
            return 0

        return int(
            (self.human_reviewed_citations / self.total_citations) * 100
        )


@cached_within_request
def get_adjacent_citation_ids(citation_id: int):
    citation = Citation.objects.select_related("dataset").get(id=citation_id)

    previous_id = (
        Citation.objects.filter(
            dataset=citation.dataset,
            order__lt=citation.order,
        )
        .order_by("-order", "-id")
        .values_list("id", flat=True)
        .first()
    )
    next_id = (
        Citation.objects.filter(
            dataset=citation.dataset,
            order__gt=citation.order,
        )
        .order_by("order", "id")
        .values_list("id", flat=True)
        .first()
    )

    return previous_id, next_id


def _get_screening_progress_stats(
    review_id: int,
    question_model: type,
    result_relation_name: str,
):
    question_count = question_model.objects.filter(review_id=review_id).count()
    citations = Citation.objects.filter(dataset__review_id=review_id)
    total_citations = citations.count()

    if question_count == 0:
        return CitationScreeningProgressStats(
            total_citations=total_citations,
            incomplete_citations=total_citations,
            completed_not_human_reviewed_citations=0,
            human_reviewed_citations=0,
        )

    status_field = f"{result_relation_name}__status"
    human_validated_field = f"{result_relation_name}__human_validated_by"
    human_answered_field = f"{result_relation_name}__human_selected_answer"

    rows = citations.annotate(
        result_count=Count(result_relation_name, distinct=True),
        completed_count=Count(
            result_relation_name,
            filter=Q(**{status_field: ScreeningResultStatus.COMPLETED}),
            distinct=True,
        ),
        human_reviewed_count=Count(
            result_relation_name,
            filter=(
                Q(**{status_field: ScreeningResultStatus.COMPLETED})
                & (
                    Q(**{f"{human_validated_field}__isnull": False})
                    | Q(**{f"{human_answered_field}__isnull": False})
                )
            ),
            distinct=True,
        ),
    ).values("result_count", "completed_count", "human_reviewed_count")

    completed_not_human_reviewed_citations = 0
    human_reviewed_citations = 0
    for row in rows:
        is_complete = (
            row["result_count"] >= question_count
            and row["completed_count"] >= question_count
        )
        if not is_complete:
            continue

        if row["human_reviewed_count"] >= question_count:
            human_reviewed_citations += 1
        else:
            completed_not_human_reviewed_citations += 1

    incomplete_citations = (
        total_citations
        - completed_not_human_reviewed_citations
        - human_reviewed_citations
    )

    return CitationScreeningProgressStats(
        total_citations=total_citations,
        incomplete_citations=incomplete_citations,
        completed_not_human_reviewed_citations=completed_not_human_reviewed_citations,
        human_reviewed_citations=human_reviewed_citations,
    )


@cached_within_request
def get_l1_screening_progress_stats(review_id: int):
    return _get_screening_progress_stats(
        review_id,
        L1ScreeningQuestion,
        "l1screeningresult",
    )


@cached_within_request
def get_l2_screening_progress_stats(review_id: int):
    return _get_screening_progress_stats(
        review_id,
        L2ScreeningQuestion,
        "l2screeningresult",
    )


@dataclass(frozen=True)
class CitationParameterExtractionProgressStats:
    total_citations: int
    incomplete_citations: int
    completed_not_human_reviewed_citations: int
    human_reviewed_citations: int

    @property
    def completed_citations(self):
        return (
            self.completed_not_human_reviewed_citations
            + self.human_reviewed_citations
        )

    @property
    def completed_percent(self):
        if self.total_citations == 0:
            return 0

        return int((self.completed_citations / self.total_citations) * 100)

    @property
    def human_reviewed_percent(self):
        if self.total_citations == 0:
            return 0

        return int(
            (self.human_reviewed_citations / self.total_citations) * 100
        )


@cached_within_request
def get_parameter_extraction_progress_stats(review_id: int):
    parameter_count = Parameter.objects.filter(
        category__review_id=review_id
    ).count()
    citations = Citation.objects.filter(dataset__review_id=review_id)
    total_citations = citations.count()

    if parameter_count == 0:
        return CitationParameterExtractionProgressStats(
            total_citations=total_citations,
            incomplete_citations=total_citations,
            completed_not_human_reviewed_citations=0,
            human_reviewed_citations=0,
        )

    rows = citations.annotate(
        result_count=Count("parameterextractionresult", distinct=True),
        completed_count=Count(
            "parameterextractionresult",
            filter=Q(
                parameterextractionresult__status=ScreeningResultStatus.COMPLETED
            ),
            distinct=True,
        ),
        human_reviewed_count=Count(
            "parameterextractionresult",
            filter=(
                Q(
                    parameterextractionresult__status=ScreeningResultStatus.COMPLETED
                )
                & Q(parameterextractionresult__human_found__isnull=False)
            ),
            distinct=True,
        ),
    ).values("result_count", "completed_count", "human_reviewed_count")

    completed_not_human_reviewed_citations = 0
    human_reviewed_citations = 0
    for row in rows:
        is_complete = (
            row["result_count"] >= parameter_count
            and row["completed_count"] >= parameter_count
        )
        if not is_complete:
            continue

        if row["human_reviewed_count"] >= parameter_count:
            human_reviewed_citations += 1
        else:
            completed_not_human_reviewed_citations += 1

    incomplete_citations = (
        total_citations
        - completed_not_human_reviewed_citations
        - human_reviewed_citations
    )

    return CitationParameterExtractionProgressStats(
        total_citations=total_citations,
        incomplete_citations=incomplete_citations,
        completed_not_human_reviewed_citations=completed_not_human_reviewed_citations,
        human_reviewed_citations=human_reviewed_citations,
    )


@cached_within_request
def options_for_question(option_class: type, question_id: int):
    return list(option_class.objects.filter(question_id=question_id))
