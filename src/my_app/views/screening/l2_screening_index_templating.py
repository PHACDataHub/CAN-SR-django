from dataclasses import dataclass

import htpy as h

from proj.htpy.util import polling_attrs

from my_app.models import (
    Citation,
    L2ScreeningQuestion,
    L2ScreeningResult,
    Review,
    TextExtractionResult,
)
from my_app.queries import L2ScreeningStatusFetcher
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
from my_app.views.screening.l2_common_components import L2ScreeningBadge
from my_app.views.view_utils import url_with_same_params
from shortcuts import BasePageTemplate, cached_property, reverse, tdt


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
            Citation.objects.filter(dataset__review=self.review)
            .select_related("document", "document__text_extraction_result")
            .order_by("order")
        )

    @cached_property
    def page_rows(self):
        return list(self.page_obj.object_list)

    @cached_property
    def page_row_ids(self):
        return [row.id for row in self.page_rows]

    @cached_property
    def screening_questions(self):
        return list(L2ScreeningQuestion.objects.filter(review=self.review))

    @cached_property
    def total_citations(self):
        return self.citation_rows.count()

    @cached_property
    def uploaded_citations(self):
        return (
            Citation.objects.filter(
                dataset__review=self.review,
                document__isnull=False,
            )
            .values_list("id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def processed_citations(self):
        return (
            Citation.objects.filter(
                dataset__review=self.review,
                document__text_extraction_result__status=TextExtractionResult.TextExtractionStatus.COMPLETED,
            )
            .values_list("id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def screened_citations(self):
        return (
            L2ScreeningResult.objects.filter(
                citation__dataset__review=self.review
            )
            .values_list("citation_id", flat=True)
            .distinct()
            .count()
        )

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
                (tdt("Uploaded documents"), self.uploaded_citations),
                (tdt("Text extracted documents"), self.processed_citations),
                (tdt("Screened so far"), self.screened_citations),
                (tdt("Screening questions"), len(self.screening_questions)),
            ],
            completed=self.screened_citations,
            total=self.total_citations,
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
            component.render(),
        )
