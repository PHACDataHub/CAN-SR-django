from functools import partial
from typing import List

from django.db import transaction
from django.utils import timezone

from proj.llm_client import ClientFailureError

from my_app.models import (
    Citation,
    L2CriticalScreeningResult,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.prompts.l2_screening_prompt import (
    UnexpectedLLMOutputError,
    get_l2_screening_results,
)
from my_app.queries import get_model_for_review, options_for_question
from my_app.services.service_util import (
    get_figure_extraction_result_for_citation,
    get_text_extraction_result_for_citation,
)
from shortcuts import logger


class EnqueueL2ScreeningService:
    """
    creates the empty result objects
    to be later used by the processing task


    Loads prerequisites and existing pairs in batches, then dispatches after commit.
    """

    def __init__(
        self,
        rows: List[Citation],
        questions: List[L2ScreeningQuestion],
        overwrite_existing=False,
        workflow_request=None,
    ):
        self.rows = rows
        self.questions = [
            question for question in questions if question.is_active
        ]
        self.overwrite_existing = overwrite_existing
        self.workflow_request = workflow_request

    def enqueue_task_for_result(self, result_id: int):
        logger.info(
            "Enqueuing background L2 screening processing for result_id=%s",
            result_id,
        )
        from my_app.tasks.l2_screening import process_l2_screening_task

        try:
            process_l2_screening_task.enqueue(result_id=result_id)
        except Exception:
            if self.workflow_request is None:
                raise
            L2ScreeningResult.objects.filter(pk=result_id).update(
                status=ScreeningResultStatus.ABANDONED,
                abandoned_at=timezone.now(),
            )
            logger.exception("Could not dispatch L2 result_id=%s", result_id)

    def perform(self):
        citations = list(
            Citation.objects.filter(
                pk__in=[row.pk for row in self.rows]
            ).select_related(
                "document__text_extraction_result",
                "document__figure_extraction_result",
            )
        )
        # Validate the whole selection before deleting any existing answers.
        for citation in citations:
            get_text_extraction_result_for_citation(citation)
            get_figure_extraction_result_for_citation(citation)

        citation_ids = {citation.pk for citation in citations}
        models_by_review = {
            review_id: get_model_for_review(review_id)
            for review_id in {
                question.review_id for question in self.questions
            }
        }
        with transaction.atomic():
            existing = L2ScreeningResult.objects.filter(
                question__in=self.questions, citation_id__in=citation_ids
            )
            if self.overwrite_existing:
                existing.delete()
                existing_pairs = set()
            else:
                existing_pairs = set(
                    existing.values_list("citation_id", "question_id")
                )
            results = L2ScreeningResult.objects.bulk_create(
                [
                    L2ScreeningResult(
                        citation_id=citation_id,
                        question=question,
                        language_model=models_by_review[question.review_id],
                        status=ScreeningResultStatus.PENDING,
                        workflow_request=self.workflow_request,
                    )
                    for question in self.questions
                    for citation_id in citation_ids
                    if (citation_id, question.pk) not in existing_pairs
                ]
            )
            for result in results:
                transaction.on_commit(
                    partial(self.enqueue_task_for_result, result.pk),
                )
        return results


class ProcessL2ScreeningService:
    """
    immediately processes a single result for a citation-question pair,
    meant to be used in a task for background processing
    """

    NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT = 3

    def __init__(self, result_id: int):
        self.result_id = result_id

    def _mark_abandoned(self, result: L2ScreeningResult, error: Exception):
        result.status = ScreeningResultStatus.ABANDONED
        result.abandoned_at = timezone.now()
        result.explanation = (
            f"Screening could not be completed: {error.__class__.__name__}"
        )

    def _get_l2_screening_results_with_retries(
        self,
        question: L2ScreeningQuestion,
        citation: Citation,
        text_extraction_result: TextExtractionResult,
        model,
    ):
        options = options_for_question(L2ScreeningQuestionOption, question.id)
        tables = list(citation.document.documenttables.all())
        figures = list(citation.document.documentfigures.all())

        for retry_num in range(self.NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT + 1):
            try:
                return get_l2_screening_results(
                    question,
                    options,
                    citation,
                    text_extraction_result,
                    tables,
                    figures,
                    model,
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
            "Starting processing of L2 screening for result_id=%s",
            self.result_id,
        )
        result = L2ScreeningResult.objects.select_related(
            "question",
            "language_model",
            "citation",
            "citation__document",
            "citation__document__text_extraction_result",
            "citation__document__figure_extraction_result",
        ).get(id=self.result_id)
        L2CriticalScreeningResult.objects.filter(
            initial_result=result
        ).delete()
        question = result.question
        citation = result.citation
        text_extraction_result = get_text_extraction_result_for_citation(
            citation
        )
        get_figure_extraction_result_for_citation(citation)

        try:
            screening_results = self._get_l2_screening_results_with_retries(
                question,
                citation,
                text_extraction_result,
                result.language_model,
            )
        except UnexpectedLLMOutputError as exc:
            logger.exception(
                "error processing L2 screening for result_id=%s question_id=%s citation_id=%s",
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
                "API failure processing L2 screening for result_id=%s question_id=%s citation_id=%s",
                self.result_id,
                question.id,
                citation.id,
            )
            raise
        except Exception:
            logger.exception(
                "Unexpected error processing L2 screening for result_id=%s question_id=%s citation_id=%s",
                self.result_id,
                question.id,
                citation.id,
            )
            raise

        result.selected_option = screening_results.selected
        result.confidence = screening_results.confidence
        result.explanation = screening_results.explanation
        result.evidence_sentences = screening_results.evidence_sentences
        result.evidence_tables = screening_results.evidence_tables
        result.evidence_figures = screening_results.evidence_figures
        result.status = ScreeningResultStatus.COMPLETED

        with transaction.atomic():
            result.save()
            critical_result = L2CriticalScreeningResult.objects.create(
                initial_result=result,
                language_model=result.language_model,
            )
            from my_app.tasks.l2_screening import (
                process_l2_critical_screening_task,
            )

            transaction.on_commit(
                lambda: process_l2_critical_screening_task.enqueue(
                    result_id=critical_result.pk
                )
            )
