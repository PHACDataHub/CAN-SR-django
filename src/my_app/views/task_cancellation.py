from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import TemplateView

import htpy as h
from phac_aspc.rules import test_rule

from proj.htpy.base_page import BasePageTemplate
from proj.htpy.components import CsrfInput
from proj.text import tdt

from my_app.models import Review
from my_app.router import route
from my_app.services.task_cancellation import (
    cancel_all_tasks,
    cancel_review_tasks,
)
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import HtpyTemplateMixin, MustPassRuleMixin


class TaskCancellationPage(BasePageTemplate):
    def head_title(self):
        return self.context["title"]

    def content(self):
        return [
            h.h1[self.context["title"]],
            h.p[
                tdt(
                    "Tasks that have already started can finish. Pending tasks and follow-up tasks from those workflows will be canceled."
                )
            ],
            h.form(method="post")[
                CsrfInput(),
                h.button(".btn.btn-danger.me-3", type="submit")[
                    tdt("Confirm task cancellation")
                ],
                h.a(href=self.context["return_url"])[tdt("Go back")],
            ],
        ]


class TaskCancellationView(HtpyTemplateMixin, TemplateView):
    template_component = TaskCancellationPage

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            title=self.title, return_url=self.get_return_url(), **kwargs
        )


@route("tasks/cancel/", name="cancel_all_tasks")
class GlobalTaskCancellationView(MustPassRuleMixin, TaskCancellationView):
    title = tdt("Cancel tasks across all reviews")

    def check_rule(self, user):
        return test_rule("is_admin", user)

    def get_return_url(self):
        return reverse("review_list")

    def post(self, request, *args, **kwargs):
        cancel_all_tasks()
        messages.success(
            request, tdt("Task cancellation requested across all reviews.")
        )
        return redirect(self.get_return_url())


@route("reviews/<int:review_id>/tasks/cancel/", name="cancel_review_tasks")
class ReviewTaskCancellationView(MustAccessReviewMixin, TaskCancellationView):
    title = tdt("Cancel tasks for this review")

    def get_return_url(self):
        return reverse("review_detail", args=[self.kwargs["review_id"]])

    def get(self, request, *args, **kwargs):
        get_object_or_404(Review, pk=self.kwargs["review_id"])
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        review = get_object_or_404(Review, pk=self.kwargs["review_id"])
        cancel_review_tasks(review)
        messages.success(
            request, tdt("Task cancellation requested for this review.")
        )
        return redirect(self.get_return_url())
