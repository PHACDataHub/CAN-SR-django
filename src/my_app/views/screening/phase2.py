from django import forms
from django.views.generic import DetailView

from my_app.models import (
    BulkWorkflowRequest,
    Citation,
    Phase2CitationWorkflowRequest,
)
from my_app.router import route
from my_app.services.phase2_workflow import (
    QueueBulkWorkflowService,
    QueueCitationWorkflowService,
)
from my_app.views.screening.workflows import (
    BulkWorkflowStatusView,
    WorkflowLaunchView,
    WorkflowStatusTemplate,
)
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    HtpyTemplateMixin,
    StandardFormMixin,
    cached_property,
    get_object_or_404,
    reverse,
    tdt,
)


class Phase2WorkflowForm(StandardFormMixin, forms.Form):
    should_download_pdf = forms.BooleanField(
        label=tdt(
            "Download missing PDFs using DOI (citations without attached PDFs will be skipped otherwise)"
        ),
        required=False,
        initial=True,
    )
    should_process_pdf = forms.BooleanField(
        label=tdt(
            "Process PDFs for text and figures (required for L2 screening, only leave unselected if already complete)"
        ),
        required=False,
        initial=True,
    )
    should_run_l2 = forms.BooleanField(
        label=tdt("Run L2 screening"),
        required=False,
        initial=True,
    )

    def clean(self):
        data = super().clean()
        if not any(data.values()):
            raise forms.ValidationError(
                tdt("Select at least one phase 2 process.")
            )
        return data


class Phase2WorkflowView(WorkflowLaunchView):
    phase = BulkWorkflowRequest.Phase.L2
    form_class = Phase2WorkflowForm


@route("/reviews/<int:review_id>/phase-2/", name="phase2_bulk_workflow")
class BulkPhase2WorkflowView(Phase2WorkflowView):
    def queue(self, options):
        return QueueBulkWorkflowService(
            self.review, requested_by=self.request.user, **options
        ).perform()

    def status_url(self, workflow):
        return reverse(
            "phase2_bulk_workflow_status", args=[self.review.pk, workflow.pk]
        )


@route(
    "/reviews/<int:review_id>/citations/<int:row_pk>/phase-2/",
    name="phase2_citation_workflow",
)
class CitationPhase2WorkflowView(Phase2WorkflowView):
    @cached_property
    def citation(self):
        return get_object_or_404(
            Citation, pk=self.kwargs["row_pk"], dataset__review=self.review
        )

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            "citation": self.citation,
        }

    def queue(self, options):
        return QueueCitationWorkflowService(
            self.citation, requested_by=self.request.user, **options
        ).perform()

    def status_url(self, workflow):
        return reverse(
            "phase2_citation_workflow_status",
            args=[self.review.pk, workflow.pk],
        )


@route(
    "/reviews/<int:review_id>/phase-2/requests/<int:pk>/",
    name="phase2_bulk_workflow_status",
)
class BulkPhase2WorkflowStatusView(BulkWorkflowStatusView):
    phase = BulkWorkflowRequest.Phase.L2


@route(
    "/reviews/<int:review_id>/citations/phase-2/requests/<int:pk>/",
    name="phase2_citation_workflow_status",
)
class CitationPhase2WorkflowStatusView(
    MustAccessReviewMixin, HtpyTemplateMixin, DetailView
):
    template_component = WorkflowStatusTemplate

    def get_queryset(self):
        return Phase2CitationWorkflowRequest.objects.filter(
            citation__dataset__review=self.review
        ).select_related("citation")
