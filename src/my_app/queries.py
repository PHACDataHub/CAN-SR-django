from typing import List

from data_fetcher import DataFetcher
from data_fetcher.extras import cache_within_request as cached_within_request
from phac_aspc.vanilla import group_by

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningResult,
    Review,
    ReviewUserLink,
    ScreeningResultStatus,
)


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
        all_questions = cls.QuestionModel.objects.filter(review=review)

        results = cls.ResultModel.objects.filter(citation_id__in=keys)

        results_by_citation = group_by(results, lambda r: r.citation_id)

        final_results = {}
        for citation_id in keys:
            citation_results = results_by_citation.get(citation_id, [])
            final_results[citation_id] = cls.status_for_results(
                citation_results, all_questions
            )

        return final_results

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


@cached_within_request
def options_for_question(option_class: type, question_id: int):
    return list(option_class.objects.filter(question_id=question_id))
