import htpy as h

from proj.htpy import definition_list as DefList
from proj.htpy.components import PercentFormatter

from my_app.models import Citation, L2ScreeningResult, ScreeningResultStatus
from my_app.queries import (
    L2ScreeningStatusFetcher,
    get_l2_screening_progress_stats,
)
from my_app.router import route
from my_app.views.pdf_components import (
    DocumentWorkflowCitationPanel,
    EvidenceDefinitionItems,
    PdfPanel,
    PdfViewerAssets,
    PdfWorkflowPageContent,
    WorkflowResultsPanel,
)
from my_app.views.screening.components import CitationScreeningProgressNav
from my_app.views.screening.document_util_components import (
    DocumentCitationDetailView,
)
from my_app.views.screening.l2.components import (
    L2ScreeningBadge,
    render_l2_human_review_control,
)
from my_app.views.screening.util import can_start_l2_screening
from shortcuts import BasePageTemplate
from shortcuts import breadcrumbs as bc
from shortcuts import reverse, tdt


def l2_screening_control_id(citation_row):
    return f"l2-pdf-screening-control-{citation_row.id}"


def render_l2_screening_control(citation_row, review, status_fetcher=None):
    if status_fetcher is None:
        status_fetcher = L2ScreeningStatusFetcher.get_instance()

    status = status_fetcher.get(citation_row.id)
    can_start = can_start_l2_screening(citation_row)
    button = None
    if status is ScreeningResultStatus.NOT_STARTED and can_start:
        button = h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "l2_citation_process_screening",
                args=[review.id, citation_row.id],
            ),
            hx_target="closest .l2-pdf-screening-control",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Screen this document")]
    return h.div(
        ".l2-pdf-screening-control.d-flex.flex-wrap.align-items-center.gap-2",
        id=l2_screening_control_id(citation_row),
    )[
        h.div[
            h.span(".text-muted.me-1")[tdt("L2 screening")],
            L2ScreeningBadge(citation_row, status_fetcher),
        ],
        button,
    ]


class L2PdfScreeningPage(BasePageTemplate):
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
            assets=PdfViewerAssets(
                citation_row,
                review,
                data_id="l2-citation-data",
                metadata_route_name="l2_citation_pdf_metadata",
            ),
            breadcrumbs=bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("L2 Screening"),
                    href=reverse("l2_citations_list", args=[review.id]),
                ),
                bc.BreadcrumbItem(label=tdt("PDF screening")),
            ],
            title=tdt("L2 PDF screening"),
            progress_navigation=CitationScreeningProgressNav(
                citation_row,
                review,
                detail_route_name="l2_citation_detail",
                progress_stats=get_l2_screening_progress_stats(review.id),
                nav_label=tdt("L2 citation navigation"),
            ),
            pdf_panel=PdfPanel(citation_row),
            citation_panel=self.render_citation_panel(citation_row),
            results_panel=self.render_results_panel(citation_row),
        )

    def render_citation_panel(self, citation_row: Citation):
        status_fetcher = L2ScreeningStatusFetcher.get_instance()
        workflow_ready = can_start_l2_screening(citation_row)
        rerun_action = None
        if (
            status_fetcher.get(citation_row.id)
            is not ScreeningResultStatus.NOT_STARTED
            and workflow_ready
        ):
            rerun_action = self.render_rescreen_button()

        return DocumentWorkflowCitationPanel(
            citation_row,
            self.review,
            workflow_control=render_l2_screening_control(
                citation_row,
                self.review,
                status_fetcher,
            ),
            workflow_ready=workflow_ready,
            rerun_action=rerun_action,
        )

    def render_rescreen_button(self):
        return h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "l2_citation_process_screening",
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target=f"#{l2_screening_control_id(self.citation_row)}",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Re-screen")]

    def render_results_panel(self, citation_row: Citation):
        results = self.get_results(citation_row)
        return WorkflowResultsPanel(
            title=tdt("L2 screening results"),
            results=results,
            empty_message=tdt("No screening results yet."),
            render_result=self.render_result,
        )

    def get_results(self, citation_row: Citation):
        return list(
            L2ScreeningResult.objects.filter(citation=citation_row)
            .select_related(
                "question",
                "selected_option",
                "human_selected_answer",
                "human_validated_by",
            )
            .order_by("question_id")
        )

    def render_result(self, result: L2ScreeningResult):

        return DefList.DL(
            [
                (tdt("Question"), result.question.question_text),
                (
                    tdt("Status"),
                    ScreeningResultStatus(result.status).label,
                ),
                (
                    tdt("Selected option"),
                    render_l2_human_review_control(result, self.review),
                ),
                (tdt("Confidence"), PercentFormatter(result.confidence)),
                (tdt("Notes"), result.explanation or tdt("None")),
                *EvidenceDefinitionItems(result),
            ]
        )


@route(
    "/reviews/<int:review_id>/screening_l2/rows/<int:row_pk>/details/",
    name="l2_citation_detail",
)
class L2PdfScreeningView(DocumentCitationDetailView):
    template_component = L2PdfScreeningPage
