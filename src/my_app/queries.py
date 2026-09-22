from dataclasses import dataclass
from typing import List

from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Choices,
    Count,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Lower, Replace, Trim

from data_fetcher import DataFetcher
from data_fetcher.extras import cache_within_request as cached_within_request
from data_fetcher.shorthand_fetcher_classes import (
    AbstractChildModelByAttrFetcher,
    PrimaryKeyFetcherFactory,
)
from phac_aspc.vanilla import group_by

from my_app.models import (
    Citation,
    FigureExtractionResult,
    L1HumanAnswer,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    L2HumanAnswer,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    LanguageModel,
    Parameter,
    ParameterAnswerAgreement,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    ParameterOption,
    Review,
    ReviewUserLink,
    ScreeningActions,
    ScreeningResultStatus,
    TextExtractionResult,
)
from shortcuts import logger

ReviewByIdFetcher = PrimaryKeyFetcherFactory.get_model_by_id_fetcher(Review)


class ReviewStage(Choices):
    L1_SCREENING = "l1_screening", "L1 Screening"
    L2_SCREENING = "l2_screening", "L2 Screening"
    PARAMETER_EXTRACTION = "parameter_extraction", "Parameter Extraction"


def normalize_parameter_value(expression):
    normalized = Coalesce(
        expression,
        Value("", output_field=TextField()),
        output_field=TextField(),
    )
    normalized = Lower(Trim(normalized), output_field=TextField())
    for whitespace in (" ", "\t", "\n", "\r"):
        normalized = Replace(
            normalized,
            Value(whitespace),
            Value(""),
            output_field=TextField(),
        )
    return normalized


def get_parameter_human_ai_agreements(review_id: int):
    ai_results = ParameterExtractionResult.objects.filter(
        citation_id=OuterRef("citation_id"),
        question_id=OuterRef("question_id"),
        status=ScreeningResultStatus.COMPLETED,
    )
    answers = (
        ParameterHumanAnswer.objects.filter(
            question__review_id=review_id,
            citation__dataset__review_id=review_id,
        )
        .annotate(
            ai_result_id=Subquery(ai_results.values("id")[:1]),
            ai_found=Subquery(
                ai_results.values("found")[:1],
                output_field=BooleanField(),
            ),
            ai_value=Subquery(
                ai_results.values("value")[:1],
                output_field=TextField(),
            ),
            ai_selected_option_id=Subquery(
                ai_results.values("selected_option_id")[:1],
                output_field=IntegerField(),
            ),
        )
        .filter(ai_result_id__isnull=False)
        .annotate(
            normalized_human_value=normalize_parameter_value(F("value")),
            normalized_ai_value=normalize_parameter_value(F("ai_value")),
        )
        .annotate(
            agreement=Case(
                When(
                    Q(found=True, ai_found=False)
                    | Q(found=False, ai_found=True),
                    then=Value(
                        ParameterAnswerAgreement.DETECTION_DISAGREEMENT
                    ),
                ),
                When(
                    found=False,
                    ai_found=False,
                    then=Value(ParameterAnswerAgreement.ABSENCE_AGREEMENT),
                ),
                When(
                    found=True,
                    ai_found=True,
                    selected_option_id__isnull=False,
                    selected_option_id=F("ai_selected_option_id"),
                    then=Value(ParameterAnswerAgreement.VALUE_AGREEMENT),
                ),
                When(
                    found=True,
                    ai_found=True,
                    selected_option_id__isnull=True,
                    ai_selected_option_id__isnull=True,
                    normalized_human_value=F("normalized_ai_value"),
                    then=Value(ParameterAnswerAgreement.VALUE_AGREEMENT),
                ),
                default=Value(ParameterAnswerAgreement.VALUE_DISAGREEMENT),
                output_field=CharField(),
            )
        )
    )
    return answers


@dataclass(frozen=True)
class ParameterAnswerAgreementMetrics:
    detection_disagreement: int = 0
    absence_agreement: int = 0
    value_agreement: int = 0
    value_disagreement: int = 0

    @property
    def total(self):
        return (
            self.detection_disagreement
            + self.absence_agreement
            + self.value_agreement
            + self.value_disagreement
        )


def get_parameter_answer_agreement_metrics(review_id: int):
    counts = {
        row["agreement"]: row["count"]
        for row in get_parameter_human_ai_agreements(review_id)
        .values("agreement")
        .annotate(count=Count("id"))
    }
    return ParameterAnswerAgreementMetrics(
        detection_disagreement=counts.get(
            ParameterAnswerAgreement.DETECTION_DISAGREEMENT, 0
        ),
        absence_agreement=counts.get(
            ParameterAnswerAgreement.ABSENCE_AGREEMENT, 0
        ),
        value_agreement=counts.get(
            ParameterAnswerAgreement.VALUE_AGREEMENT, 0
        ),
        value_disagreement=counts.get(
            ParameterAnswerAgreement.VALUE_DISAGREEMENT, 0
        ),
    )


def is_l2_screening_defined(citation_id: int) -> bool:
    review_filter = {"review__citation_dataset__rows__id": citation_id}
    has_questions = L2ScreeningQuestion.active_objects.filter(
        **review_filter
    ).exists()
    has_options = L2ScreeningQuestionOption.active_objects.filter(
        question__deletion_time__isnull=True,
        question__review__citation_dataset__rows__id=citation_id,
    ).exists()
    return has_questions and has_options


def is_parameter_extraction_defined(citation_id: int) -> bool:
    return Parameter.active_objects.filter(
        review__citation_dataset__rows__id=citation_id
    ).exists()


def _has_completed_document_extraction(citation_id: int) -> bool:
    return Citation.objects.filter(
        id=citation_id,
        document__text_extraction_result__status=(
            TextExtractionResult.TextExtractionStatus.COMPLETED
        ),
        document__figure_extraction_result__status=(
            FigureExtractionResult.Status.COMPLETED
        ),
    ).exists()


def is_ready_for_l2_screening(citation_id: int) -> bool:
    return is_l2_screening_defined(
        citation_id
    ) and _has_completed_document_extraction(citation_id)


def is_ready_for_parameter_extraction(citation_id: int) -> bool:
    return is_parameter_extraction_defined(
        citation_id
    ) and _has_completed_document_extraction(citation_id)


@cached_within_request
def get_review(review_id: int):
    return ReviewByIdFetcher.get_instance().get(review_id)


def get_citations_for_stage(review_id: int, stage: ReviewStage | None = None):
    review = get_review(review_id)
    all_citations = Citation.objects.filter(dataset__review__id=review_id)

    if stage is None:
        return all_citations

    if review.disable_filtering:
        return all_citations

    if stage == ReviewStage.L1_SCREENING:
        return all_citations

    if stage == ReviewStage.L2_SCREENING:
        return all_citations.filter(
            id__in=_screened_in_citation_ids(
                review_id,
                L1ScreeningQuestion,
                L1HumanAnswer,
                L1ScreeningResult,
            )
        )

    if stage == ReviewStage.PARAMETER_EXTRACTION:
        return all_citations.filter(
            id__in=_screened_in_citation_ids(
                review_id,
                L2ScreeningQuestion,
                L2HumanAnswer,
                L2ScreeningResult,
            )
        )


@cached_within_request
def _screened_in_citation_ids(
    review_id, question_model, human_model, result_model
):
    question_ids = set(
        question_model.active_objects.filter(
            review_id=review_id, disable_screening=False
        ).values_list("id", flat=True)
    )
    if not question_ids:
        return Citation.objects.filter(
            dataset__review_id=review_id
        ).values_list("id", flat=True)

    human_answers = human_model.objects.filter(
        citation__dataset__review_id=review_id,
        question_id__in=question_ids,
    ).values_list(
        "citation_id",
        "question_id",
        "selected_option__question_id",
        "selected_option__deletion_time",
        "selected_option__screening_action",
    )
    human_pairs = set()
    passing_pairs = set()
    failing_pairs = set()
    for (
        citation_id,
        question_id,
        option_question_id,
        deleted_at,
        action,
    ) in human_answers:
        pair = (citation_id, question_id)
        human_pairs.add(pair)
        if (
            option_question_id == question_id
            and deleted_at is None
            and action == ScreeningActions.ScreenIn
        ):
            passing_pairs.add(pair)
        else:
            failing_pairs.add(pair)

    ai_answers = result_model.objects.filter(
        citation__dataset__review_id=review_id,
        question_id__in=question_ids,
        status=ScreeningResultStatus.COMPLETED,
        selected_option__deletion_time__isnull=True,
        selected_option__screening_action=ScreeningActions.ScreenIn,
    ).values_list("citation_id", "question_id", "selected_option__question_id")
    passing_pairs.update(
        (citation_id, question_id)
        for citation_id, question_id, option_question_id in ai_answers
        if option_question_id == question_id
        and (citation_id, question_id) not in human_pairs
    )
    passing_pairs.difference_update(failing_pairs)

    passed_counts = {}
    for citation_id, _ in passing_pairs:
        passed_counts[citation_id] = passed_counts.get(citation_id, 0) + 1
    return [
        citation_id
        for citation_id, count in passed_counts.items()
        if count == len(question_ids)
    ]


@cached_within_request
def get_model_for_review(review_id: int):
    language_model_id = get_review(review_id).language_model_id
    supported_models = LanguageModel.get_supported_models()

    if language_model_id is not None:
        selected_model = supported_models.filter(id=language_model_id).first()
        if selected_model is not None:
            return selected_model

        logger.error(
            "Review id=%s has unsupported or inactive language model id=%s; falling back to the default model",
            review_id,
            language_model_id,
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
        return cls.QuestionModel.objects.filter(review=review)


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
def get_adjacent_citation_ids(
    citation_id: int, stage: ReviewStage | None = None
):
    citation = Citation.objects.select_related("dataset").get(id=citation_id)
    citations = get_citations_for_stage(citation.dataset.review_id, stage)

    previous_id = (
        citations.filter(
            dataset=citation.dataset,
        )
        .filter(
            Q(order__lt=citation.order)
            | Q(order=citation.order, id__lt=citation.id)
        )
        .order_by("-order", "-id")
        .values_list("id", flat=True)
        .first()
    )
    next_id = (
        citations.filter(
            dataset=citation.dataset,
        )
        .filter(
            Q(order__gt=citation.order)
            | Q(order=citation.order, id__gt=citation.id)
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
    human_answer_relation_name: str,
    stage: ReviewStage,
):
    question_count = question_model.active_objects.filter(
        review_id=review_id
    ).count()
    citations = get_citations_for_stage(review_id, stage)
    total_citations = citations.count()

    if question_count == 0:
        return CitationScreeningProgressStats(
            total_citations=total_citations,
            incomplete_citations=total_citations,
            completed_not_human_reviewed_citations=0,
            human_reviewed_citations=0,
        )

    status_field = f"{result_relation_name}__status"
    rows = citations.annotate(
        result_count=Count(
            result_relation_name,
            filter=Q(
                **{
                    f"{result_relation_name}__question__deletion_time__isnull": True
                }
            ),
            distinct=True,
        ),
        completed_count=Count(
            result_relation_name,
            filter=Q(
                **{
                    status_field: ScreeningResultStatus.COMPLETED,
                    f"{result_relation_name}__question__deletion_time__isnull": True,
                }
            ),
            distinct=True,
        ),
        human_reviewed_count=Count(
            f"{human_answer_relation_name}__question",
            filter=Q(
                **{
                    f"{human_answer_relation_name}__question__deletion_time__isnull": True
                }
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
        "l1humananswer",
        ReviewStage.L1_SCREENING,
    )


@cached_within_request
def get_l2_screening_progress_stats(review_id: int):
    return _get_screening_progress_stats(
        review_id,
        L2ScreeningQuestion,
        "l2screeningresult",
        "l2humananswer",
        ReviewStage.L2_SCREENING,
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
    parameter_count = Parameter.active_objects.filter(
        review_id=review_id
    ).count()
    citations = get_citations_for_stage(
        review_id, ReviewStage.PARAMETER_EXTRACTION
    )
    total_citations = citations.count()

    if parameter_count == 0:
        return CitationParameterExtractionProgressStats(
            total_citations=total_citations,
            incomplete_citations=total_citations,
            completed_not_human_reviewed_citations=0,
            human_reviewed_citations=0,
        )

    rows = citations.annotate(
        result_count=Count(
            "parameterextractionresult",
            filter=Q(
                parameterextractionresult__question__deletion_time__isnull=True
            ),
            distinct=True,
        ),
        completed_count=Count(
            "parameterextractionresult",
            filter=Q(
                parameterextractionresult__status=ScreeningResultStatus.COMPLETED,
                parameterextractionresult__question__deletion_time__isnull=True,
            ),
            distinct=True,
        ),
        human_reviewed_count=Count(
            "parameterhumananswer__question",
            filter=Q(
                parameterhumananswer__question__deletion_time__isnull=True
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
    return list(option_class.active_objects.filter(question_id=question_id))


class NonDeletedAbstractChildModelByAttrFetcher(
    AbstractChildModelByAttrFetcher
):
    """
    fetch children by parent_id, then filter out deleted ones
    """

    model = None  # override this part
    attr = None  # override this part

    @classmethod
    def batch_load(cls, attr_values):

        including_deleted = super().batch_load(attr_values)
        final_results = []
        for children in including_deleted:
            without_deleted = [
                child
                for child in children
                if getattr(child, "deletion_time", None) is None
            ]
            final_results.append(without_deleted)

        return final_results


class ActiveL1OptionsByParentFetcher(
    NonDeletedAbstractChildModelByAttrFetcher
):
    model = L1ScreeningQuestionOption
    attr = "question_id"


class ActiveL2OptionsByParentFetcher(
    NonDeletedAbstractChildModelByAttrFetcher
):
    model = L2ScreeningQuestionOption
    attr = "question_id"


class ActiveParameterOptionByParentFetcher(
    NonDeletedAbstractChildModelByAttrFetcher
):
    model = ParameterOption
    attr = "parameter_id"
