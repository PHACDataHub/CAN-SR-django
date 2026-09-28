from django.utils import timezone

from proj.llm_client import UnexpectedLLMOutputError

from my_app.models import (
    L1CriticalScreeningResult,
    L1ScreeningQuestionOption,
    L2CriticalScreeningResult,
    L2ScreeningQuestionOption,
    ScreeningResultStatus,
)
from my_app.prompts.l1_screening_prompt import get_l1_screening_results
from my_app.prompts.l2_screening_prompt import get_l2_screening_results
from my_app.queries import options_for_question
from my_app.services.service_util import (
    get_text_extraction_result_for_citation,
)


class ProcessCriticalScreeningService:
    NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT = 3

    def __init__(self, result_id):
        self.result_id = result_id

    def perform(self):
        result = (
            self.result_model.objects.select_related(
                "initial_result__question",
                "initial_result__citation",
                "initial_result__selected_option",
                "language_model",
            )
            .filter(pk=self.result_id)
            .first()
        )
        # Re-screens delete the previous review, including any queued work.
        if result is None or result.status != ScreeningResultStatus.PENDING:
            return
        initial = result.initial_result
        if (
            initial.status != ScreeningResultStatus.COMPLETED
            or initial.selected_option_id is None
        ):
            return
        for attempt in range(self.NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT + 1):
            try:
                answer = self.get_answer(result)
                break
            except UnexpectedLLMOutputError as exc:
                if attempt == self.NUM_RETRIES_ON_UNEXPECTED_LLM_OUTPUT:
                    self.result_model.objects.filter(pk=result.pk).update(
                        status=ScreeningResultStatus.ABANDONED,
                        abandoned_at=timezone.now(),
                        updated_at=timezone.now(),
                        error=f"Critical screening could not be completed: {exc.__class__.__name__}",
                    )
                    return
        # An in-flight critical task must not recreate a result deleted by a re-screen.
        self.result_model.objects.filter(pk=result.pk).update(
            selected_option=answer.selected,
            confidence=answer.confidence,
            status=ScreeningResultStatus.COMPLETED,
            updated_at=timezone.now(),
        )


class ProcessL1CriticalScreeningService(ProcessCriticalScreeningService):
    result_model = L1CriticalScreeningResult

    def get_answer(self, result):
        initial = result.initial_result
        return get_l1_screening_results(
            initial.question,
            options_for_question(
                L1ScreeningQuestionOption, initial.question_id
            ),
            initial.citation,
            result.language_model,
            answer_to_critique=initial.selected_option,
        )


class ProcessL2CriticalScreeningService(ProcessCriticalScreeningService):
    result_model = L2CriticalScreeningResult

    def get_answer(self, result):
        initial = result.initial_result
        citation = initial.citation
        return get_l2_screening_results(
            initial.question,
            options_for_question(
                L2ScreeningQuestionOption, initial.question_id
            ),
            citation,
            get_text_extraction_result_for_citation(citation),
            list(citation.document.documenttables.all()),
            list(citation.document.documentfigures.all()),
            result.language_model,
            answer_to_critique=initial.selected_option,
        )
