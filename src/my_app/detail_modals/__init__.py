from django.http import HttpResponse

from phac_aspc.rules import test_rule

from proj.htpy.modal_component import ModalComponent
from proj.view_util import MustPassRuleMixin

from my_app.models import Citation, L1ScreeningQuestion, L2ScreeningQuestion
from my_app.router import route
from shortcuts import View, cached_property, get_object_or_404, tdt


class CitationDetailAccessMixin(MustPassRuleMixin):
    @cached_property
    def citation(self):
        return get_object_or_404(
            Citation.objects.select_related("dataset"),
            pk=self.kwargs["citation_id"],
        )

    def check_rule(self, user):
        return test_rule(
            "can_access_review", user, self.citation.dataset.review_id
        )


@route("/citations/<int:citation_id>/details/", name="citation_detail_modal")
class CitationDetailModalView(CitationDetailAccessMixin, View):
    def get(self, request, *args, **kwargs):
        return HttpResponse(
            str(
                ModalComponent(
                    title=tdt("Citation details"),
                    modal_id=f"citation-details-{self.citation.pk}",
                )[None]
            )
        )


class AnswerDetailModalView(CitationDetailAccessMixin, View):
    question_model = None
    stage = None

    @cached_property
    def question(self):
        return get_object_or_404(
            self.question_model,
            pk=self.kwargs["question_id"],
            review_id=self.citation.dataset.review_id,
        )

    def get(self, request, *args, **kwargs):
        return HttpResponse(
            str(
                ModalComponent(
                    title=tdt("Answer details"),
                    modal_id=f"{self.stage}-answer-details-{self.citation.pk}-{self.question.pk}",
                )[None]
            )
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
