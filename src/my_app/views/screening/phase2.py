from django import forms
from django.http import HttpResponseRedirect
from django.views.generic import DetailView, FormView

import htpy as h

from proj.util import MissingPreconditionError

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
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    BasePageTemplate,
    GenericForm,
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


class Phase2WorkflowTemplate(BasePageTemplate):
    def content(self):
        citation = self.context.get("citation")
        form = self.context["form"]
        errors = None
        if form.non_field_errors():
            errors = h.div(".alert.alert-danger", role="alert")[
                h.ul[(h.li[error] for error in form.non_field_errors())]
            ]
        description = tdt(
            "Run phase 2 for all citations whose L1 overall status is included. List filters do not change this selection."
        )
        if citation is not None:
            description = citation.title
        return h.div(".container")[
            h.h1[tdt("Phase 2 workflow")],
            h.p[description],
            h.p[
                tdt(
                    "Processes run in order: download missing PDFs, process PDFs, then L2 screening. Existing PDF extraction results are reused. L2 screening replaces previous screening results."
                )
            ],
            h.form(method="post")[
                errors,
                GenericForm(form),
                h.button(".btn.btn-primary", type="submit")[
                    tdt("Start workflow")
                ],
            ],
        ]


class Phase2WorkflowView(MustAccessReviewMixin, HtpyTemplateMixin, FormView):
    form_class = Phase2WorkflowForm
    template_component = Phase2WorkflowTemplate

    def form_valid(self, form):
        try:
            workflow = self.queue(form.cleaned_data)
        except MissingPreconditionError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return HttpResponseRedirect(self.status_url(workflow))


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


class Phase2WorkflowStatusTemplate(BasePageTemplate):
    def content(self):
        workflow = self.context["object"]
        children = []
        if isinstance(workflow, BulkWorkflowRequest):
            children = [
                h.li[
                    h.a(
                        href=reverse(
                            "phase2_citation_workflow_status",
                            args=[workflow.review_id, child.pk],
                        )
                    )[child.citation.title],
                    ": ",
                    child.get_status_display(),
                ]
                for child in workflow.citation_requests.select_related(
                    "citation"
                )
            ]
        return h.div(".container")[
            h.h1[tdt("Phase 2 workflow status")],
            h.p[workflow.get_status_display()],
            h.p[workflow.error],
            h.p[tdt("Requested at"), ": ", str(workflow.requested_at)],
            h.p[tdt("Finished at"), ": ", str(workflow.finished_at or "")],
            h.ul[children],
            h.a(".btn.btn-secondary", href=self.request.path)[
                tdt("Refresh status")
            ],
        ]


@route(
    "/reviews/<int:review_id>/phase-2/requests/<int:pk>/",
    name="phase2_bulk_workflow_status",
)
class BulkPhase2WorkflowStatusView(
    MustAccessReviewMixin, HtpyTemplateMixin, DetailView
):
    template_component = Phase2WorkflowStatusTemplate

    def get_queryset(self):
        return BulkWorkflowRequest.objects.filter(review=self.review)


@route(
    "/reviews/<int:review_id>/citations/phase-2/requests/<int:pk>/",
    name="phase2_citation_workflow_status",
)
class CitationPhase2WorkflowStatusView(
    MustAccessReviewMixin, HtpyTemplateMixin, DetailView
):
    template_component = Phase2WorkflowStatusTemplate

    def get_queryset(self):
        return Phase2CitationWorkflowRequest.objects.filter(
            citation__dataset__review=self.review
        )
