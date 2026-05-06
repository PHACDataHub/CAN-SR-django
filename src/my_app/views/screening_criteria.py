from functools import cached_property

import htpy as h
from django.views.generic import TemplateView

from my_app.models import SystematicReview
from my_app.router import route
from my_app.views.view_utils import MustAccessSystematicReviewMixin
from shortcuts import BasePageTemplate, HtpyTemplateMixin, tdt
from shortcuts import breadcrumbs as bc


class ScreeningCriteriaPage(BasePageTemplate):
    def content(self):
        review = self.context["systematic_review"]

        return [
            bc.BreadcrumbTrailForSystematicReview(review)[
                bc.BreadcrumbItem(label=tdt("Screening criteria"))
            ],
            h.h1[tdt("Screening criteria")],
        ]


@route(
    "systematic-reviews/<int:pk>/screening-criteria/",
    name="screening_criteria",
)
class ScreeningCriteriaView(
    TemplateView, MustAccessSystematicReviewMixin, HtpyTemplateMixin
):
    template_component = ScreeningCriteriaPage

    @cached_property
    def systematic_review(self):
        return SystematicReview.objects.get(pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["systematic_review"] = self.systematic_review
        return context
