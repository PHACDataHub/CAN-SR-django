from dataclasses import dataclass

import htpy as h

from my_app.models import (
    Citation,
    CitationStatus,
    Review,
    ScreeningResultStatus,
)
from my_app.queries import (
    ParameterExtractionStatusFetcher,
    ReviewStage,
    get_parameter_extraction_progress_stats,
)
from my_app.router import route
from my_app.views.pdf_components import (
    DocumentWorkflowCitationPanel,
    DocumentWorkflowCitationRow,
    PdfPanel,
    PdfViewerAssets,
    PdfWorkflowPageContent,
    render_pdf_detail_link,
    render_pdf_modal_button,
)
from my_app.views.screening.components import (
    Badge,
    CitationScreeningProgressNav,
    PaginatedCitationPanel,
    WorkflowListPageContent,
    WorkflowProgressPanel,
)
from my_app.views.screening.document_util_components import (
    DocumentCitationListView,
)
from my_app.views.screening.question_panels import QuestionPanels
from my_app.views.screening.refresh import workflow_refresh_attrs
from my_app.views.screening.util import (
    BADGE_CLASSES,
    can_start_parameter_extraction,
)
from my_app.views.view_utils import (
    paginated_component_response,
    url_with_same_params,
)
from shortcuts import BasePageTemplate, HtpyTemplateMixin
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, reverse, tdt


def ParameterExtractionBadge(citation_row: Citation, status_fetcher):
    status = status_fetcher.get(citation_row.id)
    return Badge(
        status.label,
        BADGE_CLASSES[status],
        badge_id=f"parameter-extraction-row-status-{citation_row.id}",
    )


def parameter_extraction_control_id(citation_row):
    return f"parameter-extraction-control-{citation_row.id}"


def render_parameter_extraction_control(
    citation_row,
    review,
    status_fetcher=None,
):
    if status_fetcher is None:
        status_fetcher = ParameterExtractionStatusFetcher.get_instance()

    status = status_fetcher.get(citation_row.id)
    can_start = can_start_parameter_extraction(citation_row)
    button = None
    if status is ScreeningResultStatus.NOT_STARTED and can_start:
        button = h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "parameter_extraction_citation_process_extraction",
                args=[review.id, citation_row.id],
            ),
            hx_target="closest .parameter-extraction-control",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Extract parameters")]

    return h.div(
        ".parameter-extraction-control.d-flex.flex-wrap.align-items-center.gap-2",
        id=parameter_extraction_control_id(citation_row),
    )[
        h.div[
            h.span(".text-muted.me-1")[tdt("Parameter extraction")],
            ParameterExtractionBadge(citation_row, status_fetcher),
        ],
        button,
    ]


def ParameterCitationRowDisplay(
    citation_row: Citation,
    review: Review,
    status_fetcher,
):
    return DocumentWorkflowCitationRow(
        citation_row,
        row_id=f"parameter-extraction-row-{citation_row.id}",
        workflow_status=h.div[
            h.span(".text-muted.me-1")[tdt("Parameter extraction")],
            ParameterExtractionBadge(citation_row, status_fetcher),
        ],
        actions=[
            render_pdf_detail_link(
                citation_row,
                review,
                "parameter_extraction_citation_detail",
            ),
            render_pdf_modal_button(citation_row, review),
        ],
    )


@dataclass
class ParameterExtractionComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse(
            "parameter_extraction_citations_list_partial",
            args=[self.review.id],
        )

    @property
    def page_number(self):
        return self.page_obj.number

    @cached_property
    def page_rows(self):
        return list(self.page_obj.object_list)

    @cached_property
    def page_row_ids(self):
        return [row.id for row in self.page_rows]

    @cached_property
    def citation_rows(self):
        return Citation.objects.filter(dataset__review=self.review)

    @cached_property
    def status_fetcher(self):
        fetcher = ParameterExtractionStatusFetcher.get_instance()
        fetcher.prefetch_keys(self.page_row_ids)
        return fetcher

    def render(self):
        return h.div(
            id="parameter-extraction-component",
            hx_swap="morph:outerHTML",
            **workflow_refresh_attrs(
                self.page_url(self.page_number, self.component_url),
                citations_update=True,
            ),
        )[
            h.div(".row.g-4", hx_sync="body:replace")[
                h.div(".col-lg-5")[self.render_progress_panel()],
                h.div(".col-lg-7")[self.render_citations_panel()],
            ]
        ]

    def render_progress_panel(self):
        return WorkflowProgressPanel(
            "parameter-extraction-progress-panel",
            metrics=[
                (tdt("Total citations"), self.citation_rows.count()),
                (
                    tdt("Screened-in citations from L1"),
                    self.citation_rows.add_l1_overall_status()
                    .filter(l1_overall_status=CitationStatus.In)
                    .count(),
                ),
                (
                    tdt("Screened-in citations from L2"),
                    self.citation_rows.add_l2_overall_status()
                    .filter(l2_overall_status=CitationStatus.In)
                    .count(),
                ),
            ],
        )

    def render_citations_panel(self):
        rows = [
            ParameterCitationRowDisplay(
                row,
                self.review,
                self.status_fetcher,
            )
            for row in self.page_rows
        ]
        return PaginatedCitationPanel(
            component_id="parameter-extraction-component",
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


class ParameterExtractionPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["review"]
        page_obj = self.context["page_obj"]
        component = ParameterExtractionComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return WorkflowListPageContent(
            review,
            tdt("Parameter extraction"),
            component.render(),
        )


class ParameterExtractionPdfPage(BasePageTemplate):
    @property
    def citation_row(self) -> Citation:
        return self.context["object"]

    @property
    def review(self):
        return self.context["review"]

    def content(self):
        review = self.review
        citation_row = self.citation_row

        return PdfWorkflowPageContent(
            refresh_url=self.request.get_full_path(),
            assets=PdfViewerAssets(
                citation_row,
                review,
                data_id="parameter-extraction-citation-data",
                metadata_route_name="parameter_extraction_citation_pdf_metadata",
            ),
            breadcrumbs=bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("Parameter extraction"),
                    href=reverse(
                        "parameter_extraction_citations_list", args=[review.id]
                    ),
                ),
                bc.BreadcrumbItem(label=tdt("PDF extraction")),
            ],
            title=tdt("Parameter PDF extraction"),
            progress_navigation=CitationScreeningProgressNav(
                self.citation_row,
                self.review,
                stage=ReviewStage.PARAMETER_EXTRACTION,
                detail_route_name="parameter_extraction_citation_detail",
                progress_stats=get_parameter_extraction_progress_stats(
                    self.review.id
                ),
                nav_label=tdt("Parameter extraction citation navigation"),
            ),
            pdf_panel=PdfPanel(citation_row),
            citation_panel=self.render_citation_panel(citation_row),
            results_panel=self.render_results_panel(citation_row),
        )

    def render_citation_panel(self, citation_row: Citation):
        status_fetcher = ParameterExtractionStatusFetcher.get_instance()
        workflow_ready = can_start_parameter_extraction(citation_row)
        rerun_action = None
        if (
            status_fetcher.get(citation_row.id)
            is not ScreeningResultStatus.NOT_STARTED
            and workflow_ready
        ):
            rerun_action = self.render_reextract_button()

        return DocumentWorkflowCitationPanel(
            citation_row,
            self.review,
            workflow_control=render_parameter_extraction_control(
                citation_row,
                self.review,
                status_fetcher,
            ),
            workflow_ready=workflow_ready,
            rerun_action=rerun_action,
        )

    def render_reextract_button(self):
        return h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "parameter_extraction_citation_process_extraction",
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target=f"#{parameter_extraction_control_id(self.citation_row)}",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Re-extract")]

    def render_results_panel(self, citation_row):
        return QuestionPanels(
            citation_row, self.review, self.request.user, "parameters"
        ).render(tdt("Parameter extraction results"))


class ParameterExtractionBaseView(DocumentCitationListView):
    stage = ReviewStage.PARAMETER_EXTRACTION


@route(
    "/reviews/<int:review_id>/parameter_extraction/",
    name="parameter_extraction_citations_list",
)
class ParameterExtractionPageView(
    ParameterExtractionBaseView,
    HtpyTemplateMixin,
):
    template_component = ParameterExtractionPageTemplate


@route(
    "/reviews/<int:review_id>/parameter_extraction/component/",
    name="parameter_extraction_citations_list_partial",
)
class ParameterExtractionComponentView(ParameterExtractionBaseView):
    def render_to_response(self, context, **response_kwargs):
        page_obj = context["page_obj"]
        component = ParameterExtractionComponent(
            review=self.review,
            page_obj=page_obj,
            request=self.request,
        )

        return paginated_component_response(
            self.request,
            page_obj,
            component.render(),
            reverse(
                "parameter_extraction_citations_list", args=[self.review.id]
            ),
            **response_kwargs,
        )
