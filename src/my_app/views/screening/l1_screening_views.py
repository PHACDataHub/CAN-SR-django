from django.http import HttpResponse
from django.views import View

from my_app.models import Citation, L1ScreeningQuestion, L1ScreeningResult
from my_app.router import route
from my_app.services.l1_screening import DeferredL1ScreeningService
from my_app.views.screening.l1_components import (
    CitationRowDisplay,
    L1ScreeningComponent,
    L1ScreeningPageTemplate,
    L1ScreeningRowDetailsModal,
    badge_id,
)
from my_app.views.view_utils import MustAccessReviewMixin, url_with_same_params
from shortcuts import (
    HtpyTemplateMixin,
    ListView,
    cached_property,
    get_object_or_404,
    reverse,
)


class L1ScreeningBaseView(MustAccessReviewMixin, ListView):
    paginate_by = 10

    def get_queryset(self):
        return Citation.objects.filter(dataset__review=self.review).order_by(
            "order"
        )


@route("/reviews/<int:review_id>/screening_l1/", name="screening_l1")
class ScreeningL1PageView(L1ScreeningBaseView, HtpyTemplateMixin):
    template_component = L1ScreeningPageTemplate


@route(
    "/reviews/<int:review_id>/screening_l1/component/",
    name="screening_l1_component",
)
class ScreeningL1ComponentView(L1ScreeningBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = L1ScreeningComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        new_page_url = reverse("screening_l1", args=[self.review.id])
        response_headers = {
            "HX-Push-Url": url_with_same_params(
                self.request,
                path=new_page_url,
                page=page_obj.number,
            )
        }

        return HttpResponse(
            str(component.render()),
            headers=response_headers,
            **response_kwargs,
        )


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/",
    name="screen_l1_row",
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
            L1ScreeningQuestion.objects.filter(
                review=self.review
            ).prefetch_related("options")
        )

    def post(self, request, *args, **kwargs):
        DeferredL1ScreeningService(
            rows=[self.citation_row],
            questions=self.screening_questions,
        ).perform()

        headers = {
            "HX-Refocus": "#" + badge_id(self.citation_row),
        }

        return HttpResponse(
            str(CitationRowDisplay(self.citation_row, self.review)),
            headers=headers,
        )


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/details/",
    name="screen_l1_row_details",
)
class L1ScreeningRowDetailsView(MustAccessReviewMixin, View):
    @cached_property
    def citation_row(self):
        return get_object_or_404(
            Citation,
            pk=self.kwargs["row_pk"],
            dataset__review=self.review,
        )

    @cached_property
    def screening_columns(self):
        return list(self.citation_row.dataset.screening_columns.order_by("id"))

    @cached_property
    def screening_results(self):
        return list(
            L1ScreeningResult.objects.filter(citation=self.citation_row)
            .select_related("question", "selected_option")
            .order_by("question_id")
        )

    def get(self, *args, **kwargs):
        modal = L1ScreeningRowDetailsModal(
            citation_row=self.citation_row,
            screening_columns=self.screening_columns,
            screening_results=self.screening_results,
        )
        return HttpResponse(str(modal.render()))
