from dataclasses import dataclass

import htpy as h

from proj.htpy import definition_list as DefList
from proj.htpy.components import PercentFormatter
from proj.htpy.util import polling_attrs

from my_app.models import (
    Citation,
    Parameter,
    ParameterExtractionResult,
    Review,
    ScreeningResultStatus,
    TextExtractionResult,
)
from my_app.queries import (
    ParameterExtractionStatusFetcher,
    get_parameter_extraction_progress_stats,
)
from my_app.views.pdf_components import (
    DocumentWorkflowCitationPanel,
    DocumentWorkflowCitationRow,
    EvidenceDefinitionItems,
    PdfPanel,
    PdfViewerAssets,
    PdfWorkflowPageContent,
    WorkflowResultsPanel,
    render_pdf_detail_link,
    render_pdf_modal_button,
)
from my_app.views.screening.components import (
    Badge,
    CitationScreeningProgressNav,
    PaginatedCitationPanel,
    WorkflowListPageContent,
    WorkflowProgressPanel,
    human_review_control_id,
)
from my_app.views.screening.util import (
    BADGE_CLASSES,
    can_start_parameter_extraction,
)
from my_app.views.view_utils import url_with_same_params
from shortcuts import BasePageTemplate
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


def parameter_extraction_human_review_control_id(result):
    return human_review_control_id("parameter-extraction", result)


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
                "parameter_extraction_row_process",
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
                "parameter_extraction_row_details",
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
        return reverse("parameter_extraction_component", args=[self.review.id])

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
    def parameters(self):
        return list(
            Parameter.objects.filter(category__review=self.review)
            .select_related("category")
            .order_by("category_id", "id")
        )

    @cached_property
    def total_citations(self):
        return Citation.objects.filter(dataset__review=self.review).count()

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
    def extracted_citations(self):
        return (
            ParameterExtractionResult.objects.filter(
                citation__dataset__review=self.review
            )
            .values_list("citation_id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def status_fetcher(self):
        fetcher = ParameterExtractionStatusFetcher.get_instance()
        fetcher.prefetch_keys(self.page_row_ids)
        return fetcher

    def render(self):
        return h.div(
            id="parameter-extraction-component",
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
            "parameter-extraction-progress-panel",
            metrics=[
                (tdt("Total citations"), self.total_citations),
                (tdt("Uploaded documents"), self.uploaded_citations),
                (tdt("Text extracted documents"), self.processed_citations),
                (tdt("Extracted so far"), self.extracted_citations),
                (tdt("Parameters"), len(self.parameters)),
            ],
            completed=self.extracted_citations,
            total=self.total_citations,
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
            assets=PdfViewerAssets(
                citation_row,
                review,
                data_id="parameter-extraction-citation-data",
                metadata_route_name="parameter_extraction_row_pdf_metadata",
            ),
            breadcrumbs=bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("Parameter extraction"),
                    href=reverse("parameter_extraction", args=[review.id]),
                ),
                bc.BreadcrumbItem(label=tdt("PDF extraction")),
            ],
            title=tdt("Parameter PDF extraction"),
            progress_navigation=CitationScreeningProgressNav(
                citation_row,
                review,
                detail_route_name="parameter_extraction_row_details",
                progress_stats=get_parameter_extraction_progress_stats(
                    review.id
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
                "parameter_extraction_row_process",
                args=[self.review.id, self.citation_row.id],
            ),
            hx_target=f"#{parameter_extraction_control_id(self.citation_row)}",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Re-extract")]

    def render_results_panel(self, citation_row: Citation):
        results = self.get_results(citation_row)
        return WorkflowResultsPanel(
            title=tdt("Parameter extraction results"),
            results=results,
            empty_message=tdt("No extraction results yet."),
            render_result=self.render_result,
        )

    def get_results(self, citation_row: Citation):
        return list(
            ParameterExtractionResult.objects.filter(citation=citation_row)
            .select_related("question", "question__category")
            .order_by("question__category_id", "question_id")
        )

    def render_result(self, result: ParameterExtractionResult):
        if result.found:
            found_value = tdt("Yes")
        else:
            found_value = tdt("No")

        return h.div(".vstack.gap-3")[
            DefList.DL(
                [
                    (tdt("Parameter"), result.question.name),
                    (tdt("Category"), result.question.category.name),
                    (
                        tdt("Status"),
                        ScreeningResultStatus(result.status).label,
                    ),
                    (tdt("Found"), found_value),
                    (tdt("Value"), result.value or tdt("None")),
                    (tdt("Confidence"), PercentFormatter(result.confidence)),
                    (tdt("Notes"), result.explanation or tdt("None")),
                    *EvidenceDefinitionItems(result),
                ]
            ),
            self.render_human_review_control(result),
        ]

    def render_human_review_control(self, result: ParameterExtractionResult):
        control_id = parameter_extraction_human_review_control_id(result)
        human_answer_url = reverse(
            "parameter_extraction_human_answer",
            args=[self.review.id, result.id],
        )

        if result.human_found is None:
            return h.div(".border-top.pt-2", id=control_id)[
                h.h3[tdt("Validation")],
                h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
                    h.span(".badge.text-bg-warning")[
                        tdt("Needs human review")
                    ],
                    h.button(
                        ".btn.btn-outline-success.btn-sm",
                        type="button",
                        hx_post=reverse(
                            "parameter_extraction_validate_ai_answer",
                            args=[self.review.id, result.id],
                        ),
                        hx_target=f"#{control_id}",
                        hx_swap="outerHTML",
                    )[tdt("Validate AI answer")],
                    h.button(
                        ".btn.btn-outline-primary.btn-sm",
                        type="button",
                        hx_get=human_answer_url,
                        hx_target="#modal-slot",
                        hx_swap="innerHTML",
                    )[tdt("Modify human values")],
                ],
            ]

        if result.human_found:
            human_found_value = tdt("Yes")
        else:
            human_found_value = tdt("No")

        return h.div(".border-top.pt-2", id=control_id)[
            h.div(".d-flex.flex-wrap.align-items-center.gap-2.mb-2")[
                h.span(".badge.text-bg-info")[tdt("Human entered")],
                h.button(
                    ".btn.btn-outline-secondary.btn-sm",
                    type="button",
                    hx_get=human_answer_url,
                    hx_target="#modal-slot",
                    hx_swap="innerHTML",
                )[tdt("Edit")],
            ],
            DefList.DL(
                [
                    (tdt("Human found"), human_found_value),
                    (tdt("Human value"), result.human_value or tdt("None")),
                ]
            ),
        ]
