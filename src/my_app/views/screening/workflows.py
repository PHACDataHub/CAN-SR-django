from itertools import groupby

from django import forms
from django.http import HttpResponseRedirect
from django.views.generic import DetailView, FormView

import htpy as h

from proj.util import MissingPreconditionError

from my_app.models import BulkWorkflowRequest
from my_app.router import route
from my_app.services.bulk_workflow import (
    QueueBulkResultsService,
    parameter_status,
    screening_status,
)
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import (
    BasePageTemplate,
    GenericForm,
    HtpyTemplateMixin,
    StandardFormMixin,
    reverse,
    tdt,
)


class BulkWorkflowForm(StandardFormMixin, forms.Form):
    pass


class WorkflowTemplate(BasePageTemplate):
    def content(self):
        phase = BulkWorkflowRequest.Phase(self.context["phase"])
        form = self.context["form"]
        errors = None
        if form.non_field_errors():
            errors = h.div(".alert.alert-danger", role="alert")[
                h.ul[(h.li[error] for error in form.non_field_errors())]
            ]
        if phase == BulkWorkflowRequest.Phase.L1:
            description = tdt(
                "Run L1 screening for all citations in this review. List filters do not change this selection."
            )
            details = tdt(
                "Each question runs initial screening followed by critical screening. Previous L1 screening results are replaced."
            )
        elif phase == BulkWorkflowRequest.Phase.PARAMETERS:
            description = tdt(
                "Run parameter extraction for all citations whose L2 overall status is included. List filters do not change this selection."
            )
            details = tdt(
                "Text and figure extraction must already be complete. One extraction runs per citation and parameter, without critical screening. Previous parameter results are replaced."
            )
        else:
            description = tdt(
                "Run phase 2 for all citations whose L1 overall status is included. List filters do not change this selection."
            )
            details = tdt(
                "Processes run in order: download missing PDFs, process PDFs, then L2 screening. Existing PDF extraction results are reused. L2 screening replaces previous screening results."
            )
        citation = self.context.get("citation")
        if citation is not None:
            description = citation.title
        return h.div(".container")[
            h.h1[tdt("{phase} workflow").format(phase=phase.label)],
            h.p[description],
            h.p[details],
            h.form(method="post")[
                errors,
                GenericForm(form),
                h.button(".btn.btn-primary", type="submit")[
                    tdt("Start workflow")
                ],
            ],
        ]


class WorkflowLaunchView(MustAccessReviewMixin, HtpyTemplateMixin, FormView):
    form_class = BulkWorkflowForm
    template_component = WorkflowTemplate

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "phase": self.phase}

    def form_valid(self, form):
        try:
            workflow = self.queue(form.cleaned_data)
        except MissingPreconditionError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return HttpResponseRedirect(self.status_url(workflow))


class BulkResultsWorkflowView(WorkflowLaunchView):
    def queue(self, options):
        return QueueBulkResultsService(
            self.review, self.phase, requested_by=self.request.user
        ).perform()


@route("/reviews/<int:review_id>/phase-1/", name="phase1_bulk_workflow")
class BulkPhase1WorkflowView(BulkResultsWorkflowView):
    phase = BulkWorkflowRequest.Phase.L1

    def status_url(self, workflow):
        return reverse(
            "phase1_bulk_workflow_status", args=[self.review.pk, workflow.pk]
        )


@route("/reviews/<int:review_id>/phase-3/", name="phase3_bulk_workflow")
class BulkPhase3WorkflowView(BulkResultsWorkflowView):
    phase = BulkWorkflowRequest.Phase.PARAMETERS

    def status_url(self, workflow):
        return reverse(
            "phase3_bulk_workflow_status", args=[self.review.pk, workflow.pk]
        )


class WorkflowStatusTemplate(BasePageTemplate):
    def members(self, workflow):
        if not isinstance(workflow, BulkWorkflowRequest):
            return []
        if workflow.phase == BulkWorkflowRequest.Phase.L2:
            return [
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
        if workflow.phase == BulkWorkflowRequest.Phase.L1:
            results = workflow.l1_results.select_related(
                "citation", "critical_result"
            )
        else:
            results = workflow.parameter_results.select_related("citation")
        members = []
        for citation_id, group in groupby(
            results.order_by("citation_id"),
            key=lambda result: result.citation_id,
        ):
            rows = list(group)
            if workflow.phase == BulkWorkflowRequest.Phase.L1:
                status = screening_status(rows)
                url = reverse(
                    "l1_citation_detail",
                    args=[workflow.review_id, citation_id],
                )
            else:
                status = parameter_status(rows)
                url = reverse(
                    "parameter_extraction_citation_detail",
                    args=[workflow.review_id, citation_id],
                )
            members.append(
                h.li[h.a(href=url)[rows[0].citation.title], ": ", status.label]
            )
        return members

    def content(self):
        workflow = self.context["object"]
        phase = BulkWorkflowRequest.Phase.L2
        if isinstance(workflow, BulkWorkflowRequest):
            phase = BulkWorkflowRequest.Phase(workflow.phase)
        return h.div(".container")[
            h.h1[tdt("{phase} workflow status").format(phase=phase.label)],
            h.p[workflow.get_status_display()],
            h.p[workflow.error],
            h.p[tdt("Requested at"), ": ", str(workflow.requested_at)],
            h.p[tdt("Finished at"), ": ", str(workflow.finished_at or "")],
            h.ul[self.members(workflow)],
            h.a(".btn.btn-secondary", href=self.request.path)[
                tdt("Refresh status")
            ],
        ]


class BulkWorkflowStatusView(
    MustAccessReviewMixin, HtpyTemplateMixin, DetailView
):
    template_component = WorkflowStatusTemplate

    def get_queryset(self):
        return BulkWorkflowRequest.objects.filter(
            review=self.review, phase=self.phase
        )


@route(
    "/reviews/<int:review_id>/phase-1/requests/<int:pk>/",
    name="phase1_bulk_workflow_status",
)
class BulkPhase1WorkflowStatusView(BulkWorkflowStatusView):
    phase = BulkWorkflowRequest.Phase.L1


@route(
    "/reviews/<int:review_id>/phase-3/requests/<int:pk>/",
    name="phase3_bulk_workflow_status",
)
class BulkPhase3WorkflowStatusView(BulkWorkflowStatusView):
    phase = BulkWorkflowRequest.Phase.PARAMETERS
