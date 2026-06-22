from typing import List

from django.db import transaction
from django.utils import timezone

from proj.llm_client import ClientFailureError

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    ScreeningResultStatus,
)
from my_app.prompts.l1_screening_prompt import (
    UnexpectedLLMOutputError,
    get_l1_screening_results,
)
from my_app.queries import get_model_for_review, options_for_question
from shortcuts import logger


class L1ScreeningService:
    """
    creates the empty result objects
    to be later used by the processing task


    will make N+1 queries (N=questions, not citations)
    ideally questions are not very numerous
    """

    def __init__(
        self,
        rows: List[Citation],
        questions: List[L1ScreeningQuestion],
        overwrite_existing=False,
    ):
        self.rows = rows
        self.questions = questions
        self.overwrite_existing = overwrite_existing

    def perform(self):

        citation_ids = {row.id for row in self.rows}

        if self.overwrite_existing:
            # all or nothing, may want to configure alternatives, but will be complicated
            L1ScreeningResult.objects.filter(
                question__in=self.questions,
                citation_id__in=citation_ids,
            ).delete()

        for question in self.questions:
            model = get_model_for_review(question.review_id)
            existing_results = L1ScreeningResult.objects.filter(
                question=question,
                citation_id__in=citation_ids,
            )
            # exclude existing citation-question pairs from processing
            citations_with_existing_results = {
                result.citation_id for result in existing_results
            }

            citations_to_process = [
                citation_id
                for citation_id in citation_ids
                if citation_id not in citations_with_existing_results
            ]

            for citation_id in citations_to_process:
                result = L1ScreeningResult.objects.create(
                    citation_id=citation_id,
                    question_id=question.id,
                    language_model=model,
                    status=ScreeningResultStatus.PENDING,
                )

                self.process_screening(result.id)

    def process_screening(self, result_id: int):
        raise NotImplementedError


class ImmediateL1ScreeningService(L1ScreeningService):
    """
    This will be very slow if used on many questions/citations,
    1 LLM query per citation-question pair,
    and we wait for the response before moving on to the next pair
    """

    def process_screening(self, result_id: int):
        logger.info(
            "Immediately processing L1 screening for result_id=%s",
            result_id,
        )

        ProcessL1ScreeningService(result_id=result_id).perform()


class DeferredL1ScreeningService(L1ScreeningService):
    def process_screening(self, result_id: int):
        logger.info(
            "Enqueuing background L1 screening processing for result_id=%s",
            result_id,
        )
        from my_app.tasks.l1_screening import process_l1_screening_task

        process_l1_screening_task.enqueue(result_id=result_id)


class ProcessL1ScreeningService:
    """
    immediately processes a single result for a citation-question pair,
    meant to be used in a task for background processing
    """

    NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT = 3

    def __init__(self, result_id: int):
        self.result_id = result_id

    def _mark_abandoned(self, result: L1ScreeningResult, error: Exception):
        result.status = ScreeningResultStatus.ABANDONED
        result.abandoned_at = timezone.now()
        result.explanation = (
            f"Screening could not be completed: {error.__class__.__name__}"
        )

    def _get_l1_screening_results_with_retries(
        self,
        question: L1ScreeningQuestion,
        citation: Citation,
        model,
    ):

        options = options_for_question(L1ScreeningQuestionOption, question.id)

        for retry_num in range(self.NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT + 1):
            try:
                return get_l1_screening_results(
                    question, options, citation, model
                )
            except UnexpectedLLMOutputError:
                if retry_num == self.NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT:
                    raise
                logger.warning(
                    "Retrying retry_num=%s after unexpected LLM output for result_id=%s question_id=%s citation_id=%s, retrying...",
                    retry_num,
                    self.result_id,
                    question.id,
                    citation.id,
                )

    def perform(self):
        logger.info(
            "Starting processing of L1 screening for result_id=%s",
            self.result_id,
        )
        result = L1ScreeningResult.objects.select_related(
            "question", "citation", "language_model"
        ).get(id=self.result_id)
        question = result.question
        citation = result.citation

        try:
            screening_results = self._get_l1_screening_results_with_retries(
                question,
                citation,
                result.language_model,
            )
        except UnexpectedLLMOutputError as exc:
            logger.exception(
                "error processing L1 screening for result_id=%s question_id=%s citation_id=%s",
                self.result_id,
                question.id,
                citation.id,
            )
            self._mark_abandoned(result, exc)
            with transaction.atomic():
                result.save()
            return
        except ClientFailureError:
            logger.exception(
                "API failure processing L1 screening for result_id=%s question_id=%s citation_id=%s",
                self.result_id,
                question.id,
                citation.id,
            )
            # this is likely a transient error, so we want to retry
            raise
        except Exception:
            logger.exception(
                "Unexpected error processing L1 screening for result_id=%s question_id=%s citation_id=%s",
                self.result_id,
                question.id,
                citation.id,
            )
            raise

        result.selected_option = screening_results.selected
        result.confidence = screening_results.confidence
        result.explanation = screening_results.explanation
        result.status = ScreeningResultStatus.COMPLETED

        with transaction.atomic():
            result.save()
