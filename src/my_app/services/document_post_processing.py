from proj.models import TaskGroup

from my_app.models import (
    Citation,
    L2ScreeningQuestion,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
)
from my_app.services.l2_screening import DeferredL2ScreeningService
from my_app.services.parameter_extraction import (
    DeferredParameterExtractionService,
)


class RequestedDocumentPostProcessingService:
    def __init__(
        self,
        *,
        task_group_id,
        citation_id,
        should_run_l2_screening,
        should_run_parameter_extraction,
    ):
        self.task_group = TaskGroup.objects.get(id=task_group_id)
        self.citation = Citation.objects.select_related("dataset__review").get(
            id=citation_id
        )
        self.should_run_l2_screening = should_run_l2_screening
        self.should_run_parameter_extraction = should_run_parameter_extraction

    def perform(self):
        if not self.task_group.is_latest_with_key():
            return

        if self.should_run_l2_screening:
            self.enqueue_l2_screening()
        if self.should_run_parameter_extraction:
            self.enqueue_parameter_extraction()

    def enqueue_l2_screening(self):
        has_newer_results = L2ScreeningResult.objects.filter(
            citation=self.citation,
            created_at__gt=self.task_group.created_at,
        ).exists()
        if has_newer_results:
            return

        questions = list(
            L2ScreeningQuestion.objects.filter(
                review=self.citation.dataset.review
            )
        )
        DeferredL2ScreeningService(
            rows=[self.citation],
            questions=questions,
            overwrite_existing=True,
        ).perform()

    def enqueue_parameter_extraction(self):
        has_newer_results = ParameterExtractionResult.objects.filter(
            citation=self.citation,
            created_at__gt=self.task_group.created_at,
        ).exists()
        if has_newer_results:
            return

        parameters = list(
            Parameter.objects.filter(
                category__review=self.citation.dataset.review
            )
        )
        DeferredParameterExtractionService(
            rows=[self.citation],
            questions=parameters,
            overwrite_existing=True,
        ).perform()
