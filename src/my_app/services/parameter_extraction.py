from functools import partial
from typing import List

from django.db import transaction
from django.utils import timezone

from proj.llm_client import ClientFailureError

from my_app.models import (
    Citation,
    Parameter,
    ParameterExtractionResult,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.prompts.parameter_extraction_prompt import (
    UnexpectedLLMOutputError,
    get_parameter_extraction_results,
)
from my_app.queries import get_model_for_review
from my_app.services.service_util import (
    get_figure_extraction_result_for_citation,
    get_text_extraction_result_for_citation,
)
from my_app.services.task_cancellation import (
    current_cancellation_generation_id,
)
from shortcuts import logger


class EnqueueParameterExtractionService:
    """Prepare result rows in batches and dispatch their tasks after commit."""

    def __init__(
        self,
        rows: List[Citation],
        questions: List[Parameter],
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
        citations = list(
            Citation.objects.filter(
                pk__in=[row.pk for row in self.rows]
            ).select_related(
                "document__text_extraction_result",
                "document__figure_extraction_result",
            )
        )
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
        if self.bulk_request is None:
            cancellation_generation_id = current_cancellation_generation_id()
        else:
            cancellation_generation_id = (
                self.bulk_request.cancellation_generation_id
            )
        with transaction.atomic():
            existing = ParameterExtractionResult.objects.filter(
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
            results = ParameterExtractionResult.objects.bulk_create(
                [
                    ParameterExtractionResult(
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
                    partial(
                        self.enqueue_task_for_result,
                        result.pk,
                        cancellation_generation_id,
                    )
                )
        return results

    def enqueue_task_for_result(
        self, result_id: int, cancellation_generation_id: int
    ) -> None:
        from my_app.tasks.parameter_extraction import (
            process_parameter_extraction_task,
        )

        try:
            process_parameter_extraction_task.enqueue(
                result_id=result_id,
                cancellation_generation_id=cancellation_generation_id,
            )
        except Exception:
            if self.bulk_request is None:
                raise
            ParameterExtractionResult.objects.filter(pk=result_id).update(
                status=ScreeningResultStatus.ABANDONED,
                abandoned_at=timezone.now(),
            )
            logger.exception(
                "Could not dispatch ParameterExtractionResult id=%s", result_id
            )


class ProcessParameterExtractionService:
    """
    immediately processes a single result for a citation-parameter pair,
    meant to be used in a task for background processing
    """

    NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT = 3

    def __init__(self, result_id: int):
        self.result_id = result_id

    def _mark_abandoned(
        self, result: ParameterExtractionResult, error: Exception
    ):
        result.status = ScreeningResultStatus.ABANDONED
        result.abandoned_at = timezone.now()
        result.explanation = f"Parameter extraction could not be completed: {error.__class__.__name__}"

    def _get_parameter_extraction_results_with_retries(
        self,
        question: Parameter,
        citation: Citation,
        text_extraction_result: TextExtractionResult,
        model,
    ):
        tables = list(citation.document.documenttables.all())
        figures = list(citation.document.documentfigures.all())

        for retry_num in range(self.NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT + 1):
            try:
                return get_parameter_extraction_results(
                    citation,
                    question,
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
            "Starting processing of parameter extraction for result_id=%s",
            self.result_id,
        )
        result = ParameterExtractionResult.objects.select_related(
            "question",
            "language_model",
            "citation",
            "citation__document",
            "citation__document__text_extraction_result",
            "citation__document__figure_extraction_result",
        ).get(id=self.result_id)
        question = result.question
        citation = result.citation
        text_extraction_result = get_text_extraction_result_for_citation(
            citation
        )
        get_figure_extraction_result_for_citation(citation)

        try:
            extraction_results = (
                self._get_parameter_extraction_results_with_retries(
                    question,
                    citation,
                    text_extraction_result,
                    result.language_model,
                )
            )
        except UnexpectedLLMOutputError as exc:
            logger.exception(
                "error processing parameter extraction for result_id=%s question_id=%s citation_id=%s",
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
                "API failure processing parameter extraction for result_id=%s question_id=%s citation_id=%s",
                self.result_id,
                question.id,
                citation.id,
            )
            raise
        except Exception:
            logger.exception(
                "Unexpected error processing parameter extraction for result_id=%s question_id=%s citation_id=%s",
                self.result_id,
                question.id,
                citation.id,
            )
            raise

        result.found = extraction_results.found
        result.value = extraction_results.value
        selected_option_id = getattr(
            extraction_results, "selected_option_id", None
        )
        if selected_option_id is not None:
            result.selected_option = question.options.get(
                id=selected_option_id
            )
        else:
            result.selected_option = None
        result.explanation = extraction_results.explanation
        result.evidence_sentences = extraction_results.evidence_sentences
        result.evidence_tables = extraction_results.evidence_tables
        result.evidence_figures = extraction_results.evidence_figures
        result.status = ScreeningResultStatus.COMPLETED

        with transaction.atomic():
            result.save()
