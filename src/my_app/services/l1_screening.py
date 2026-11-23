from functools import partial
from typing import List

from django.db import transaction
from django.utils import timezone

from proj.llm_client import ClientFailureError

from my_app.models import (
    Citation,
    L1CriticalScreeningResult,
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


class EnqueueL1ScreeningService:
    """Prepare result rows in batches and dispatch their tasks after commit."""

    def __init__(
        self,
        rows: List[Citation],
        questions: List[L1ScreeningQuestion],
        overwrite_existing=False,
        bulk_request=None,
    ):
        self.rows = rows
        self.questions = [
            question for question in questions if question.is_active
        ]
        self.overwrite_existing = overwrite_existing
        self.bulk_request = bulk_request

    def perform(self):
        citation_ids = {row.pk for row in self.rows}
        models_by_review = {
            review_id: get_model_for_review(review_id)
            for review_id in {
                question.review_id for question in self.questions
            }
        }
        with transaction.atomic():
            existing = L1ScreeningResult.objects.filter(
                question__in=self.questions,
                citation_id__in=citation_ids,
            )
            if self.overwrite_existing:
                existing.delete()
                existing_pairs = set()
            else:
                existing_pairs = set(
                    existing.values_list("citation_id", "question_id")
                )
            results = L1ScreeningResult.objects.bulk_create(
                [
                    L1ScreeningResult(
                        citation_id=citation_id,
                        question=question,
                        language_model=models_by_review[question.review_id],
                        status=ScreeningResultStatus.PENDING,
                        bulk_request=self.bulk_request,
                    )
                    for question in self.questions
                    for citation_id in citation_ids
                    if (citation_id, question.pk) not in existing_pairs
                ]
            )
            for result in results:
                transaction.on_commit(
                    partial(self.enqueue_task_for_result, result.pk)
                )
        return results

    def enqueue_task_for_result(self, result_id):
        from my_app.tasks.l1_screening import process_l1_screening_task

        try:
            process_l1_screening_task.enqueue(result_id=result_id)
        except Exception:
            if self.bulk_request is None:
                raise
            L1ScreeningResult.objects.filter(pk=result_id).update(
                status=ScreeningResultStatus.ABANDONED,
                abandoned_at=timezone.now(),
            )
            logger.exception(
                "Could not dispatch L1ScreeningResult id=%s", result_id
            )


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

        # we must also reset any existing critical screening results
        # for this initial result
        L1CriticalScreeningResult.objects.filter(
            initial_result=result
        ).delete()
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
            critical_result = L1CriticalScreeningResult.objects.create(
                initial_result=result,
                language_model=result.language_model,
            )
            from my_app.tasks.l1_screening import (
                process_l1_critical_screening_task,
            )

            transaction.on_commit(
                lambda: process_l1_critical_screening_task.enqueue(
                    result_id=critical_result.pk
                )
            )
