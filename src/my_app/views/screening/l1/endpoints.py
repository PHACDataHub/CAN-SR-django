from django.http import HttpResponse
from django.views import View

import htpy as h

from my_app.models import (
    Citation,
    L1HumanAnswer,
    L1ScreeningQuestion,
    L1ScreeningResult,
)
from my_app.router import route
from my_app.services.l1_screening import EnqueueL1ScreeningService
from my_app.views.screening.human_answers import (
    HumanAnswerFormView,
    ScreeningHumanAnswerForm,
    ScreeningHumanAnswerViewMixin,
    ValidateAIAnswerView,
)
from my_app.views.screening.l1.detail import (
    render_l1_human_review_control,
    render_l1_screening_control,
)
from my_app.views.screening.l1.list import CitationRowDisplay
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import cached_property, get_object_or_404


class L1HumanAnswerForm(ScreeningHumanAnswerForm):
    class Meta:
        model = L1HumanAnswer
        fields = ScreeningHumanAnswerForm.Meta.fields
        labels = ScreeningHumanAnswerForm.Meta.labels


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/",
    name="l1_citation_process_screening",
)
class ScreenL1RowView(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        return Citation.objects.get(
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

    @cached_property
    def screening_questions(self):
        return list(
            L1ScreeningQuestion.active_objects.filter(
                review=self.review
            ).prefetch_related("options")
        )

    def post(self, request, *args, **kwargs):
        EnqueueL1ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
            overwrite_existing=True,
        ).perform()

        # render multiple components at top level,
        # client uses this view in two context
        # it will select applicable markup with hx-select
        resp_content = h.fragment[
            CitationRowDisplay(self.citation_row, self.review),
            render_l1_screening_control(self.citation_row, self.review),
        ]

        return HttpResponse(str(resp_content))


class L1CitationMixin(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        return get_object_or_404(
            Citation,
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

    @cached_property
    def screening_questions(self):
        return list(
            L1ScreeningQuestion.active_objects.filter(review=self.review)
        )


class L1HumanReviewMixin(ScreeningHumanAnswerViewMixin):
    result_model = L1ScreeningResult
    answer_model = L1HumanAnswer
    form_class = L1HumanAnswerForm
    prefix = "l1"
    route_name = "l1_citation_human_answer"
    render_control_component = staticmethod(render_l1_human_review_control)


@route(
    "/reviews/<int:review_id>/screening_l1/results/<int:result_pk>/validate/",
    name="l1_citation_validate_correct",
)
class L1ValidateCorrectView(L1HumanReviewMixin, ValidateAIAnswerView):
    pass


@route(
    "/reviews/<int:review_id>/screening_l1/results/<int:result_pk>/human-answer/",
    name="l1_citation_human_answer",
)
class L1HumanAnswerView(L1HumanReviewMixin, HumanAnswerFormView):
    pass
