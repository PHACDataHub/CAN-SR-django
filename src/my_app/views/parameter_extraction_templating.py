from dataclasses import dataclass

from django.utils.text import Truncator

import htpy as h

from proj.htpy import definition_list as DefList

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
    DocumentUploadBadge,
    FigureExtractionBadge,
    PdfPanel,
    PdfViewerAssets,
    TextExtractionBadge,
    render_evidence_chips,
    render_pdf_detail_link,
    render_pdf_modal_button,
)
from my_app.views.screening.components import (
    Badge,
    CitationScreeningProgressNav,
    NotStartedBadge,
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
    text_extraction_badge = TextExtractionBadge(citation_row)
    figure_extraction_badge = FigureExtractionBadge(citation_row)

    return h.div(
        ".list-group-item.citation-item.position-relative.pb-4",
        id=f"parameter-extraction-row-{citation_row.id}",
    )[
        h.div(".d-flex.justify-content-between.align-items-start.gap-3")[
            h.div(".flex-grow-1")[
                h.div(".fw-semibold")[
                    citation_row.title or tdt("Untitled citation")
                ],
                (
                    h.div(".text-muted.small.mt-1")[citation_row.abstract]
                    if citation_row.abstract
                    else None
                ),
                h.div(".d-flex.flex-wrap.gap-2.mt-2.small")[
                    h.div[
                        h.span(".text-muted.me-1")[tdt("Document")],
                        DocumentUploadBadge(citation_row),
                    ],
                    (
                        h.div[
                            h.span(".text-muted.me-1")[tdt("Text extraction")],
                            text_extraction_badge,
                        ]
                        if text_extraction_badge is not None
                        else None
                    ),
                    (
                        h.div[
                            h.span(".text-muted.me-1")[
                                tdt("Figure extraction")
                            ],
                            figure_extraction_badge,
                        ]
                        if figure_extraction_badge is not None
                        else None
                    ),
                    h.div[
                        h.span(".text-muted.me-1")[
                            tdt("Parameter extraction")
                        ],
                        ParameterExtractionBadge(citation_row, status_fetcher),
                    ],
                ],
            ],
            h.div(".d-flex.flex-column.align-items-end.gap-2")[
                render_pdf_detail_link(
                    citation_row,
                    review,
                    "parameter_extraction_row_details",
                ),
                render_pdf_modal_button(
                    citation_row,
                    review,
                    "parameter_extraction_row_upload",
                ),
            ],
        ],
    ]


@dataclass
class ParameterExtractionComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse("parameter_extraction_component", args=[self.review.id])

    @property
    def shell_url(self):
        return reverse("parameter_extraction", args=[self.review.id])

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
            hx_trigger="click from:#refresh-button, citations-update from:body",
            hx_swap="outerHTML",
            hx_disabled_elt="#refresh-button",
        )[
            h.div(".row.g-4")[
                h.div(".col-lg-5")[self.render_progress_panel()],
                h.div(".col-lg-7")[self.render_citations_panel()],
            ]
        ]

    def render_progress_panel(self):
        if self.total_citations > 0:
            progress_percent = int(
                (self.extracted_citations / self.total_citations) * 100
            )
        else:
            progress_percent = 0

        return h.section(
            id="parameter-extraction-progress-panel",
            class_="border rounded p-3 bg-body-tertiary",
        )[
            h.h2(".h5.mb-3")[tdt("Progress")],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Total citations")],
                h.span(".fw-semibold")[str(self.total_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Uploaded documents")],
                h.span(".fw-semibold")[str(self.uploaded_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Text extracted documents")],
                h.span(".fw-semibold")[str(self.processed_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Extracted so far")],
                h.span(".fw-semibold")[str(self.extracted_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.span[tdt("Parameters")],
                h.span(".fw-semibold")[str(len(self.parameters))],
            ],
            h.div(".progress", role="progressbar")[
                h.div(
                    ".progress-bar",
                    style=f"width: {progress_percent}%",
                    aria_valuenow=str(progress_percent),
                    aria_valuemin="0",
                    aria_valuemax="100",
                )[f"{progress_percent}%"],
            ],
        ]

    def render_citations_panel(self):
        if self.page_rows:
            rows = [
                ParameterCitationRowDisplay(
                    row,
                    self.review,
                    self.status_fetcher,
                )
                for row in self.page_rows
            ]
        else:
            rows = [h.p(".text-muted.mb-0")[tdt("No citations on this page.")]]

        return h.section(".border.rounded.p-3")[
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.h2(".h5.mb-0")[tdt("Citations")],
                h.div(".text-muted.small")[
                    tdt("Page"),
                    " ",
                    str(self.page_number),
                ],
            ],
            self.render_pagination_controls(),
            h.div(".list-group")[rows],
        ]

    def render_pagination_controls(self):
        common_button_attrs = {
            "hx_target": "#parameter-extraction-component",
            "hx_swap": "outerHTML",
            "hx_disabled_elt": "this",
            "type": "button",
            "class": "btn btn-outline-primary btn-sm",
        }
        previous_button = h.button(
            hx_get=(
                self.page_url(
                    self.page_obj.previous_page_number(), self.component_url
                )
                if self.page_obj.has_previous()
                else None
            ),
            disabled=not self.page_obj.has_previous(),
            **common_button_attrs,
        )[tdt("Previous")]

        next_button = h.button(
            hx_get=(
                self.page_url(
                    self.page_obj.next_page_number(), self.component_url
                )
                if self.page_obj.has_next()
                else None
            ),
            disabled=not self.page_obj.has_next(),
            **common_button_attrs,
        )[tdt("Next")]

        return h.div(
            ".d-flex.justify-content-between.align-items-center.mb-3"
        )[
            h.div(".small.text-muted")[
                tdt("Page"),
                " ",
                str(self.page_number),
                " ",
                tdt("of"),
                " ",
                str(self.page_obj.paginator.num_pages),
            ],
            h.div(".btn-group")[
                previous_button,
                next_button,
            ],
        ]

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

        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=tdt("Parameter extraction")),
            ],
            h.h1[tdt("Parameter extraction")],
            h.div(".mb-3")[
                h.button(
                    "#refresh-button.btn.btn-outline-secondary",
                    type="button",
                )[tdt("Refresh")],
            ],
            component.render(),
        ]


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

        return [
            PdfViewerAssets(
                citation_row,
                review,
                data_id="parameter-extraction-citation-data",
                pdf_route_name="parameter_extraction_row_pdf",
                metadata_route_name="parameter_extraction_row_pdf_metadata",
            ),
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("Parameter extraction"),
                    href=reverse("parameter_extraction", args=[review.id]),
                ),
                bc.BreadcrumbItem(label=tdt("PDF extraction")),
            ],
            h.h1[tdt("Parameter PDF extraction")],
            CitationScreeningProgressNav(
                citation_row,
                review,
                detail_route_name="parameter_extraction_row_details",
                progress_stats=get_parameter_extraction_progress_stats(
                    review.id
                ),
                nav_label=tdt("Parameter extraction citation navigation"),
            ),
            h.div(".row.g-4.citation-workflow-layout")[
                h.div(".col-lg-9")[PdfPanel(citation_row),],
                h.div(".col-lg-3.citation-workflow-sidebar")[
                    h.div(".vstack.gap-4")[
                        self.render_citation_panel(citation_row),
                        self.render_results_panel(citation_row),
                    ]
                ],
            ],
        ]

    def render_citation_panel(self, citation_row: Citation):
        text_extraction_badge = (
            TextExtractionBadge(citation_row) or NotStartedBadge()
        )
        figure_extraction_badge = (
            FigureExtractionBadge(citation_row) or NotStartedBadge()
        )
        status_fetcher = ParameterExtractionStatusFetcher.get_instance()
        document = citation_row.document

        return h.section(".border.rounded.p-3.bg-body-tertiary")[
            h.h2(".h5.mb-3")[tdt("Citation")],
            h.div(
                ".fw-semibold",
                title=citation_row.title or None,
            )[
                Truncator(
                    citation_row.title or tdt("Untitled citation")
                ).chars(60)
            ],
            h.div(".vstack.gap-2.mt-3.small")[
                self.render_document_upload_control(citation_row),
                self.render_text_extraction_control(
                    citation_row,
                    text_extraction_badge,
                    figure_extraction_badge,
                ),
                render_parameter_extraction_control(
                    citation_row,
                    self.review,
                    status_fetcher,
                ),
            ],
            (
                self.render_more_details(document, status_fetcher)
                if document is not None
                else None
            ),
        ]

    def render_document_upload_control(self, citation_row):
        return h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
            h.div[
                h.span(".text-muted.me-1")[tdt("Document")],
                DocumentUploadBadge(citation_row),
            ],
            (
                render_pdf_modal_button(
                    citation_row,
                    self.review,
                    "parameter_extraction_row_upload",
                )
                if citation_row.document is None
                else None
            ),
        ]

    def render_text_extraction_control(
        self,
        citation_row,
        text_extraction_badge,
        figure_extraction_badge,
    ):
        return h.div(".d-flex.flex-wrap.align-items-center.gap-2")[
            h.div[
                h.span(".text-muted.me-1")[tdt("Text extraction")],
                text_extraction_badge,
            ],
            h.div[
                h.span(".text-muted.me-1")[tdt("Figure extraction")],
                figure_extraction_badge,
            ],
            (
                render_pdf_modal_button(
                    citation_row,
                    self.review,
                    "parameter_extraction_row_upload",
                )
                if citation_row.document is not None
                and not can_start_parameter_extraction(citation_row)
                else None
            ),
        ]

    def render_more_details(self, document, status_fetcher):
        text_extraction_result = getattr(
            document, "text_extraction_result", None
        )
        if text_extraction_result is None:
            text_extraction_status = tdt("No text extraction result yet")
        else:
            text_extraction_status = TextExtractionResult.TextExtractionStatus(
                text_extraction_result.status
            ).label

        return h.details(".mt-3")[
            h.summary[tdt("More")],
            h.div(".mt-3")[
                h.div(".small.text-muted")[document.file.name],
                h.div(".mt-2")[
                    h.strong[tdt("Text extraction status")],
                    ": ",
                    text_extraction_status,
                ],
                h.div(".d-flex.gap-2.flex-wrap")[
                    render_pdf_modal_button(
                        self.citation_row,
                        self.review,
                        "parameter_extraction_row_upload",
                    ),
                    (
                        self.render_reextract_button()
                        if status_fetcher.get(self.citation_row.id)
                        is not ScreeningResultStatus.NOT_STARTED
                        and can_start_parameter_extraction(self.citation_row)
                        else None
                    ),
                ],
            ],
        ]

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

        return h.section(".border.rounded.p-3")[
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.h2(".h5.mb-0")[tdt("Parameter extraction results")],
                h.div(".text-muted.small")[
                    tdt("Results"),
                    " ",
                    str(len(results)),
                ],
            ],
            (
                h.div(".vstack.gap-3")[
                    [self.render_result(result) for result in results]
                ]
                if results
                else h.p(".text-muted.mb-0")[tdt("No extraction results yet.")]
            ),
        ]

    def get_results(self, citation_row: Citation):
        return list(
            ParameterExtractionResult.objects.filter(citation=citation_row)
            .select_related("question", "question__category")
            .order_by("question__category_id", "question_id")
        )

    def render_result(self, result: ParameterExtractionResult):
        if result.confidence is None:
            confidence_value = tdt("None")
        else:
            confidence_value = str(result.confidence)

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
                    (tdt("Confidence"), confidence_value),
                    (tdt("Notes"), result.explanation or tdt("None")),
                    (
                        tdt("Evidence sentences"),
                        render_evidence_chips(
                            result.evidence_sentences,
                            "sentence",
                            tdt("Sentence"),
                            tdt("Evidence sentences"),
                        ),
                    ),
                    (
                        tdt("Evidence tables"),
                        render_evidence_chips(
                            result.evidence_tables,
                            "table",
                            tdt("Table"),
                            tdt("Evidence tables"),
                        ),
                    ),
                    (
                        tdt("Evidence figures"),
                        render_evidence_chips(
                            result.evidence_figures,
                            "figure",
                            tdt("Figure"),
                            tdt("Evidence figures"),
                        ),
                    ),
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
