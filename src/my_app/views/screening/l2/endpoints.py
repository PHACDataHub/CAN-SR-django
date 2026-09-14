from django.http import HttpResponse

import htpy as h

from my_app.models import L2HumanAnswer, L2ScreeningQuestion, L2ScreeningResult
from my_app.router import route
from my_app.services.l2_screening import EnqueueL2ScreeningService
from my_app.views.screening.document_util_components import (
    DocumentCitationMixin,
    PdfCitationMetadataView,
)
from my_app.views.screening.human_answers import (
    HumanAnswerFormView,
    ScreeningHumanAnswerForm,
    ScreeningHumanAnswerViewMixin,
    ValidateAIAnswerView,
)
from my_app.views.screening.l2.components import render_l2_human_review_control
from my_app.views.screening.l2.detail import render_l2_screening_control
from my_app.views.screening.util import can_start_l2_screening
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import View, cached_property


class L2HumanAnswerForm(ScreeningHumanAnswerForm):
    class Meta:
        model = L2HumanAnswer
        fields = ScreeningHumanAnswerForm.Meta.fields
        labels = ScreeningHumanAnswerForm.Meta.labels


class L2HumanReviewMixin(ScreeningHumanAnswerViewMixin):
    result_model = L2ScreeningResult
    answer_model = L2HumanAnswer
    form_class = L2HumanAnswerForm
    prefix = "l2"
    route_name = "l2_citation_human_answer"
    render_control_component = staticmethod(render_l2_human_review_control)


@route(
    "/reviews/<int:review_id>/screening_l2/results/<int:result_pk>/validate/",
    name="l2_citation_validate_correct",
)
class L2ValidateCorrectView(L2HumanReviewMixin, ValidateAIAnswerView):
    pass


@route(
    "/reviews/<int:review_id>/screening_l2/results/<int:result_pk>/human-answer/",
    name="l2_citation_human_answer",
)
class L2HumanAnswerView(L2HumanReviewMixin, HumanAnswerFormView):
    pass


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/process/",
    name="l2_citation_process_screening",
)
class L2PdfScreeningProcessView(DocumentCitationMixin):
    @cached_property
    def screening_questions(self):
        return list(L2ScreeningQuestion.objects.filter(review=self.review))

    def post(self, request, *args, **kwargs):
        if not can_start_l2_screening(self.citation_row):
            return HttpResponse(
                str(
                    render_l2_screening_control(
                        self.citation_row,
                        self.review,
                    )
                ),
                status=409,
            )

        EnqueueL2ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
            overwrite_existing=True,
        ).perform()

        return HttpResponse(
            str(render_l2_screening_control(self.citation_row, self.review))
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/pdf-metadata/",
    name="l2_citation_pdf_metadata",
)
class L2PdfCitationMetadataView(PdfCitationMetadataView):
    result_model = L2ScreeningResult
