"""
Covers L1 and L2 screening, not full-text

"""

from typing import List

from django.db import transaction
from django.tasks import task

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.models import (
    CitationDatasetRow,
    L1ScreeningQuestion,
    L1ScreeningResult,
    ScreeningResultStatus,
    SystematicReview,
)
from my_app.prompts.screening_prompt import get_l1_screening_results


class L1ScreeningService:
    """
    creates the empty result objects
    to be later used by the processing task


    will make N+1 queries (N=questions, not citations)
    ideally questions are not very numerous
    """

    def __init__(
        self,
        rows: List[CitationDatasetRow],
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
        ProcessL1ScreeningService(result_id=result_id).perform()


class DeferredL1ScreeningService(L1ScreeningService):
    def process_screening(self, result_id: int):
        from my_app.tasks.ai_screening import process_l1_screening_task

        process_l1_screening_task.enqueue(result_id=result_id)


class ProcessL1ScreeningService:
    """
    immediately processes a single result for a citation-question pair,
    meant to be used in a task for background processing
    """

    def __init__(self, result_id: int):
        self.result_id = result_id

    def perform(self):
        result = L1ScreeningResult.objects.select_related(
            "question", "citation"
        ).get(id=self.result_id)
        question = result.question
        citation = result.citation

        try:
            screening_results = get_l1_screening_results(question, citation)
            result.selected_option = screening_results.selected
            result.confidence = screening_results.confidence
            result.explanation = screening_results.explanation
            result.status = ScreeningResultStatus.COMPLETED
        except Exception:
            # TODO: better error handling, logging,
            # depending on the error, the result should bail
            # if it's a task, it can re-enqueue itself, otherwise retry?
            # increment some sort of circuit-breaker threshold?
            result.status = ScreeningResultStatus.ABANDONED

        result.save()
