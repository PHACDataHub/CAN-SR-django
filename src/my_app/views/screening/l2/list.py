from dataclasses import dataclass

import htpy as h

from proj.htpy.util import polling_attrs

from my_app.models import Citation, CitationStatus, L2ScreeningQuestion, Review
from my_app.queries import (
    L2ScreeningStatusFetcher,
    ReviewStage,
    get_citations_for_stage,
    get_screening_status_counts,
)
from my_app.router import route
from my_app.views.pdf_components import (
    DocumentWorkflowCitationRow,
    render_pdf_detail_link,
    render_pdf_modal_button,
)
from my_app.views.screening.components import (
    PaginatedCitationPanel,
    WorkflowListPageContent,
    WorkflowProgressPanel,
)
from my_app.views.screening.document_util_components import (
    DocumentCitationListView,
)
from my_app.views.screening.filters import (
    ScreeningFilterMixin,
    ScreeningFilters,
)
from my_app.views.screening.l2.components import L2ScreeningBadge
from my_app.views.view_utils import (
    paginated_component_response,
    url_with_same_params,
)
from shortcuts import (
    BasePageTemplate,
    HtpyTemplateMixin,
    cached_property,
    reverse,
    tdt,
)


def CitationRowDisplay(citation_row: Citation, review: Review, status_fetcher):
    return DocumentWorkflowCitationRow(
        citation_row,
        row_id=f"l2-screening-row-{citation_row.id}",
        workflow_status=h.div[
            h.span(".text-muted.me-1")[tdt("L2 screening")],
            L2ScreeningBadge(citation_row, status_fetcher),
        ],
        actions=[
            render_pdf_detail_link(
                citation_row,
                review,
                "l2_citation_detail",
            ),
            render_pdf_modal_button(citation_row, review),
        ],
    )


@dataclass
class L2ScreeningComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse("l2_citations_list_partial", args=[self.review.id])

    @property
    def page_number(self):
        return self.page_obj.number

    @cached_property
    def citation_rows(self):
        return (
            get_citations_for_stage(self.review.id, ReviewStage.L2_SCREENING)
            .select_related("document", "document__text_extraction_result")
            .order_by("order", "id")
        )

    @cached_property
    def page_rows(self):
        return list(self.page_obj.object_list)

    @cached_property
    def page_row_ids(self):
        return [row.id for row in self.page_rows]

    @cached_property
    def screening_question_count(self):
        return L2ScreeningQuestion.active_objects.filter(
            review=self.review, disable_screening=False
        ).count()

    @cached_property
    def total_citations(self):
        return Citation.objects.filter(dataset__review=self.review).count()

    @cached_property
    def status_fetcher(self):
        fetcher = L2ScreeningStatusFetcher.get_instance()
        fetcher.prefetch_keys(self.page_row_ids)
        return fetcher

    def render(self):
        return h.div(
            id="l2-screening-component",
            hx_target="this",
            hx_get=self.page_url(self.page_number, self.component_url),
            hx_swap="morph:outerHTML",
            hx_disabled_elt="#refresh-button",
            **polling_attrs(
                "click from:#refresh-button, citations-update from:body"
            ),
        )[
            h.div(".row.g-4")[
                h.div(".col-lg-5")[self.render_progress_panel()],
                h.div(".col-lg-7")[self.render_citations_panel()],
            ]
        ]

    def render_progress_panel(self):
        return WorkflowProgressPanel(
            "l2-screening-progress-panel",
            metrics=[
                (tdt("Total citations"), self.total_citations),
                (
                    tdt("Screened-in citations from L1"),
                    Citation.objects.filter(dataset__review=self.review)
                    .add_l1_overall_status()
                    .filter(l1_overall_status=CitationStatus.In)
                    .count(),
                ),
                (tdt("Screening questions"), self.screening_question_count),
            ],
            status_counts=get_screening_status_counts(
                self.citation_rows, "l2"
            ),
            statistics_url=reverse(
                "l2_screening_statistics", args=[self.review.id]
            ),
        )

    def render_citations_panel(self):
        rows = [
            CitationRowDisplay(row, self.review, self.status_fetcher)
            for row in self.page_rows
        ]
        return PaginatedCitationPanel(
            component_id="l2-screening-component",
            component_url=self.component_url,
            page_obj=self.page_obj,
            request=self.request,
            rows=rows,
        )

    def page_url(self, page_number, path):
        return url_with_same_params(
            self.request,
            path=path,
            page=page_number,
        )


class L2ScreeningPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["review"]
        page_obj = self.context["page_obj"]
        component = L2ScreeningComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return WorkflowListPageContent(
            review,
            tdt("L2 Screening"),
            [
                ScreeningFilters(
                    self.context["filter_form"],
                    reverse("l2_citations_list", args=[review.id]),
                ),
                component.render(),
            ],
        )


class L2ScreeningBaseView(ScreeningFilterMixin, DocumentCitationListView):
    stage = ReviewStage.L2_SCREENING
    screening_stage = "l2"


@route("/reviews/<int:review_id>/screening_l2/", name="l2_citations_list")
class ScreeningL2PageView(L2ScreeningBaseView, HtpyTemplateMixin):
    template_component = L2ScreeningPageTemplate


@route(
    "/reviews/<int:review_id>/screening_l2/component/",
    name="l2_citations_list_partial",
)
class ScreeningL2ComponentView(L2ScreeningBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = L2ScreeningComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        return paginated_component_response(
            self.request,
            page_obj,
            component.render(),
            reverse("l2_citations_list", args=[self.review.id]),
            **response_kwargs,
        )
