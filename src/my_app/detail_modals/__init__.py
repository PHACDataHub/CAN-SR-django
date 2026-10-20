from django.http import HttpResponse

import htpy as h
from phac_aspc.rules import test_rule

from proj.htpy.modal_component import (
    ModalComponent,
    get_modal_size_for_current_request,
)
from proj.view_util import MustPassRuleMixin

from my_app.models import Citation, L1ScreeningQuestion, L2ScreeningQuestion
from my_app.router import route
from shortcuts import View, cached_property, get_object_or_404, tdt

from .components import AnswerDetails, CitationDetails, ScreeningData


class CitationDetailAccessMixin(MustPassRuleMixin):
    @cached_property
    def citation(self):
        return get_object_or_404(
            Citation.objects.select_related("dataset__review", "document"),
            pk=self.kwargs["citation_id"],
        )

    def check_rule(self, user):
        return test_rule(
            "can_access_review", user, self.citation.dataset.review_id
        )

    def modal_response(self, title, modal_id, content):
        size = get_modal_size_for_current_request()
        return HttpResponse(
            str(
                ModalComponent(
                    title=title,
                    modal_id=modal_id,
                    size_cls=f"modal-{size} citation-detail-modal",
                    aria_labelledby=f"{modal_id}-title",
                    header=h.fragment[
                        h.h1(".modal-title.fs-5", id=f"{modal_id}-title")[
                            title
                        ],
                        h.button(
                            ".btn-close",
                            type="button",
                            data_modal_close=True,
                            aria_label=tdt("Close"),
                        ),
                    ],
                )[content]
            )
        )


@route("/citations/<int:citation_id>/details/", name="citation_detail_modal")
class CitationDetailModalView(CitationDetailAccessMixin, View):
    def get(self, request, *args, **kwargs):
        stage = request.GET.get("stage", "l1").lower()
        if stage in {"param", "parameter", "parameter_extraction"}:
            stage = "parameters"
        if stage not in {"l1", "l2", "parameters"}:
            stage = "l1"
        return self.modal_response(
            tdt("Citation details"),
            f"citation-details-{self.citation.pk}",
            CitationDetails(self.citation, stage),
        )


class AnswerDetailModalView(CitationDetailAccessMixin, View):
    question_model = None
    stage = None

    @cached_property
    def question(self):
        return get_object_or_404(
            self.question_model.objects.select_related(
                "review"
            ).prefetch_related("options"),
            pk=self.kwargs["question_id"],
            review_id=self.citation.dataset.review_id,
        )

    def get(self, request, *args, **kwargs):
        data = ScreeningData(
            self.citation, self.stage, question_id=self.question.pk
        )
        return self.modal_response(
            tdt(f"{self.stage.upper()} answer details"),
            f"{self.stage}-answer-details-{self.citation.pk}-{self.question.pk}",
            AnswerDetails(self.citation, self.question, data),
        )


@route(
    "/citations/<int:citation_id>/l1-questions/<int:question_id>/details/",
    name="l1_answer_detail_modal",
)
class L1AnswerDetailModalView(AnswerDetailModalView):
    question_model = L1ScreeningQuestion
    stage = "l1"


@route(
    "/citations/<int:citation_id>/l2-questions/<int:question_id>/details/",
    name="l2_answer_detail_modal",
)
class L2AnswerDetailModalView(AnswerDetailModalView):
    question_model = L2ScreeningQuestion
    stage = "l2"
