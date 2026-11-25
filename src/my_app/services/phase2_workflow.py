from functools import partial

from django.db import transaction
from django.tasks import default_task_backend
from django.utils import timezone
from django.utils.functional import cached_property

from proj.text import tdt
from proj.util import MissingPreconditionError

from my_app.models import (
    BulkWorkflowRequest,
    Citation,
    CitationStatus,
    FigureExtractionResult,
    L2ScreeningQuestion,
    PdfFromDOIRequest,
    Phase2CitationWorkflowRequest,
    TextExtractionResult,
    WorkflowStatus,
)
from my_app.services.bulk_workflow import (
    CHECK_INTERVAL,
    check_bulk_available,
    finish_request,
    screening_status,
)
from my_app.services.doi_pdf_service import DoiPdfError, QueueDoiPdfService
from my_app.services.l2_screening import EnqueueL2ScreeningService
from my_app.services.process_document import QueueProcessDocumentService
from my_app.services.service_util import (
    get_figure_extraction_result_for_citation,
    get_text_extraction_result_for_citation,
)
from my_app.services.task_cancellation import (
    current_cancellation_generation_id,
    task_was_canceled,
)


def validate_options(should_download_pdf, should_process_pdf, should_run_l2):
    if not any((should_download_pdf, should_process_pdf, should_run_l2)):
        raise MissingPreconditionError(
            tdt("Select at least one phase 2 process.")
        )
    if not default_task_backend.supports_defer:
        raise MissingPreconditionError(
            tdt("Phase 2 workflows require a deferred task backend.")
        )


def screening_questions(review_id, should_run_l2):
    if not should_run_l2:
        return []
    questions = list(
        L2ScreeningQuestion.active_objects.filter(
            review_id=review_id, disable_screening=False
        ).prefetch_related("options")
    )
    if not questions or any(
        not any(
            option.deletion_time is None for option in question.options.all()
        )
        for question in questions
    ):
        raise MissingPreconditionError(
            tdt(
                "Configure L2 questions and options before starting the workflow."
            )
        )
    return questions


class QueueCitationWorkflowService:
    def __init__(
        self,
        citation,
        *,
        requested_by=None,
        should_download_pdf=True,
        should_process_pdf=True,
        should_run_l2=True,
    ):
        self.citation = citation
        self.requested_by = requested_by
        self.options = {
            "should_download_pdf": should_download_pdf,
            "should_process_pdf": should_process_pdf,
            "should_run_l2": should_run_l2,
        }

    def perform(self):
        from my_app.tasks.phase2_workflow import check_citation_workflow

        validate_options(**self.options)
        with transaction.atomic():
            citation = Citation.objects.select_for_update().get(
                pk=self.citation.pk
            )
            if Phase2CitationWorkflowRequest.objects.filter(
                citation=citation, status=WorkflowStatus.PENDING
            ).exists():
                raise MissingPreconditionError(
                    tdt(
                        "A phase 2 workflow is already pending for this citation."
                    )
                )
            screening_questions(
                citation.dataset.review_id, self.options["should_run_l2"]
            )
            workflow = Phase2CitationWorkflowRequest.objects.create(
                citation=citation,
                requested_by=self.requested_by,
                cancellation_generation_id=current_cancellation_generation_id(),
                **self.options,
            )
            transaction.on_commit(
                partial(
                    check_citation_workflow.enqueue, request_id=workflow.pk
                )
            )
        return workflow


class QueueBulkWorkflowService:
    def __init__(
        self,
        review,
        *,
        requested_by=None,
        should_download_pdf=True,
        should_process_pdf=True,
        should_run_l2=True,
    ):
        self.review = review
        self.requested_by = requested_by
        self.options = {
            "should_download_pdf": should_download_pdf,
            "should_process_pdf": should_process_pdf,
            "should_run_l2": should_run_l2,
        }

    def perform(self):
        from my_app.tasks.bulk_workflow import check_bulk_workflow
        from my_app.tasks.phase2_workflow import check_citation_workflow

        validate_options(**self.options)
        with transaction.atomic():
            check_bulk_available(self.review, BulkWorkflowRequest.Phase.L2)
            # Serialize batch membership against citation-scoped requests too.
            citations = list(
                Citation.objects.filter(dataset__review=self.review)
                .add_l1_overall_status()
                .filter(l1_overall_status=CitationStatus.In)
                .order_by("pk")
                .select_for_update()
            )
            if Phase2CitationWorkflowRequest.objects.filter(
                citation__in=citations, status=WorkflowStatus.PENDING
            ).exists():
                raise MissingPreconditionError(
                    tdt(
                        "A selected citation already has a pending phase 2 workflow."
                    )
                )
            screening_questions(self.review.pk, self.options["should_run_l2"])
            bulk = BulkWorkflowRequest.objects.create(
                review=self.review,
                requested_by=self.requested_by,
                cancellation_generation_id=current_cancellation_generation_id(),
            )
            workflows = Phase2CitationWorkflowRequest.objects.bulk_create(
                [
                    Phase2CitationWorkflowRequest(
                        citation=citation,
                        bulk_request=bulk,
                        cancellation_generation_id=bulk.cancellation_generation_id,
                        requested_by=self.requested_by,
                        **self.options,
                    )
                    for citation in citations
                ]
            )
            for workflow in workflows:
                transaction.on_commit(
                    partial(
                        check_citation_workflow.enqueue, request_id=workflow.pk
                    )
                )
            transaction.on_commit(
                partial(check_bulk_workflow.enqueue, request_id=bulk.pk)
            )
        return bulk


class CheckCitationWorkflowService:
    """One instance per check; cached locked records belong to perform's transaction."""

    Process = Phase2CitationWorkflowRequest.Process

    def __init__(self, request_id):
        self.request_id = request_id

    @cached_property
    def workflow(self):
        # Access inside perform()'s atomic block; keep the request locked until commit.
        return (
            Phase2CitationWorkflowRequest.objects.select_for_update()
            .filter(pk=self.request_id)
            .first()
        )

    @cached_property
    def citation(self):
        # The citation lock serializes task preparation with other citation operations.
        # Like workflow, this property must only be accessed inside the atomic block.
        return Citation.objects.select_for_update().get(
            pk=self.workflow.citation_id
        )

    @property
    def current_process(self):
        return self.workflow.current_process

    def perform(self):
        from my_app.tasks.phase2_workflow import check_citation_workflow

        with transaction.atomic():
            workflow = self.workflow
            if workflow is None or workflow.status != WorkflowStatus.PENDING:
                return
            if task_was_canceled(
                workflow.cancellation_generation_id,
                review_ids=[self.citation.dataset.review_id],
            ):
                finish_request(workflow, WorkflowStatus.CANCELED)
                return
            if self.current_process_finished():
                self.advance()
            if workflow.status == WorkflowStatus.PENDING:
                transaction.on_commit(
                    partial(
                        check_citation_workflow.using(
                            run_after=timezone.now() + CHECK_INTERVAL
                        ).enqueue,
                        request_id=workflow.pk,
                    )
                )

    def current_process_finished(self):
        if self.current_process == self.Process.NOT_STARTED:
            return True
        if self.current_process == self.Process.DOWNLOAD_PDF:
            return self.pdf_download_finished()
        if self.current_process == self.Process.PROCESS_PDF:
            return self.pdf_processing_finished()
        return self.screening_finished()

    def pdf_download_finished(self):
        result = PdfFromDOIRequest.objects.get(citation=self.citation)
        if result.status == result.Status.PENDING:
            return False
        if (
            result.status != result.Status.FULFILLED
            or not self.citation.document_id
        ):
            raise MissingPreconditionError(
                tdt("PDF download failed or was canceled.")
            )
        return True

    def pdf_processing_finished(self):
        text_result = TextExtractionResult.objects.get(
            document=self.citation.document
        )
        figure_result = FigureExtractionResult.objects.get(
            document=self.citation.document
        )
        text_finished = text_result.status in (
            TextExtractionResult.TextExtractionStatus.COMPLETED,
            TextExtractionResult.TextExtractionStatus.FAILED,
            TextExtractionResult.TextExtractionStatus.CANCELED,
        )
        figures_finished = figure_result.status in (
            FigureExtractionResult.Status.COMPLETED,
            FigureExtractionResult.Status.FAILED,
            FigureExtractionResult.Status.CANCELED,
        )
        if not text_finished or not figures_finished:
            return False
        if (
            text_result.status
            != TextExtractionResult.TextExtractionStatus.COMPLETED
            or figure_result.status != FigureExtractionResult.Status.COMPLETED
        ):
            raise MissingPreconditionError(tdt("PDF processing failed."))
        return True

    def screening_finished(self):
        status = screening_status(
            self.workflow.screening_results.select_related("critical_result")
        )
        if status == WorkflowStatus.PENDING:
            return False
        if status == WorkflowStatus.FAILED:
            raise MissingPreconditionError(
                tdt("L2 screening finished with abandoned results.")
            )
        return True

    def advance(self):
        workflow = self.workflow
        current = self.current_process
        if (
            current == self.Process.NOT_STARTED
            and workflow.should_download_pdf
            and not self.citation.document_id
        ):
            return self.start_pdf_download()
        if (
            current in (self.Process.NOT_STARTED, self.Process.DOWNLOAD_PDF)
            and workflow.should_process_pdf
        ):
            return self.start_pdf_processing()
        if current != self.Process.L2 and workflow.should_run_l2:
            return self.start_l2_screening()
        finish_request(workflow, WorkflowStatus.COMPLETED)

    def start_pdf_download(self):
        workflow = self.workflow
        QueueDoiPdfService(
            self.citation,
            requesting_user=workflow.requested_by,
            cancellation_generation_id=workflow.cancellation_generation_id,
        ).perform()
        workflow.current_process = self.Process.DOWNLOAD_PDF
        workflow.save(update_fields=["current_process"])

    def start_pdf_processing(self):
        if not self.citation.document_id:
            raise MissingPreconditionError(
                tdt("PDF processing requires an attached document.")
            )
        workflow = self.workflow
        QueueProcessDocumentService(
            self.citation.document, workflow_request=workflow
        ).perform()
        workflow.current_process = self.Process.PROCESS_PDF
        workflow.save(update_fields=["current_process"])

    def start_l2_screening(self):
        workflow = self.workflow
        questions = screening_questions(self.citation.dataset.review_id, True)
        EnqueueL2ScreeningService(
            rows=[self.citation],
            questions=questions,
            overwrite_existing=True,
            workflow_request=workflow,
        ).perform()
        workflow.current_process = self.Process.L2
        workflow.save(update_fields=["current_process"])


def check_citation_workflow_result(request_id):
    try:
        CheckCitationWorkflowService(request_id).perform()
    except Exception as exc:
        with transaction.atomic():
            workflow = (
                Phase2CitationWorkflowRequest.objects.select_for_update()
                .filter(pk=request_id, status=WorkflowStatus.PENDING)
                .first()
            )
            if workflow is not None:
                error = tdt("Workflow preparation or execution failed.")
                if isinstance(exc, (MissingPreconditionError, DoiPdfError)):
                    error = str(exc)
                finish_request(workflow, WorkflowStatus.FAILED, error)
        if not isinstance(exc, (MissingPreconditionError, DoiPdfError)):
            raise
