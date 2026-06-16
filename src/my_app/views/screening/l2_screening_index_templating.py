from dataclasses import dataclass

import htpy as h

from my_app.models import (
    Citation,
    L2ScreeningQuestion,
    L2ScreeningResult,
    Review,
    TextExtractionResult,
)
from my_app.queries import L2ScreeningStatusFetcher
from my_app.views.screening.l2_common_components import (
    DocumentUploadBadge,
    FigureExtractionBadge,
    L2ScreeningBadge,
    TextExtractionBadge,
    render_l2_pdf_detail_link,
    render_l2_pdf_modal_button,
)
from my_app.views.view_utils import url_with_same_params
from shortcuts import BasePageTemplate
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, reverse, tdt


def CitationRowDisplay(citation_row: Citation, review: Review, status_fetcher):
    row_id = f"l2-screening-row-{citation_row.id}"

    text_extraction_badge = TextExtractionBadge(citation_row)
    figure_extraction_badge = FigureExtractionBadge(citation_row)

    return h.div(
        ".list-group-item.citation-item.position-relative.pb-4",
        id=row_id,
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
                        h.span(".text-muted.me-1")[tdt("L2 screening")],
                        L2ScreeningBadge(citation_row, status_fetcher),
                    ],
                ],
            ],
            h.div(".d-flex.flex-column.align-items-end.gap-2")[
                render_l2_pdf_detail_link(citation_row, review),
                render_l2_pdf_modal_button(citation_row, review),
            ],
        ],
    ]


@dataclass
class L2ScreeningComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse("screening_l2_component", args=[self.review.id])

    @property
    def shell_url(self):
        return reverse("screening_l2", args=[self.review.id])

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
                (self.screened_citations / self.total_citations) * 100
            )
        else:
            progress_percent = 0

        return h.section(
            id="l2-screening-progress-panel",
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
                h.span[tdt("Screened so far")],
                h.span(".fw-semibold")[str(self.screened_citations)],
            ],
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.span[tdt("Screening questions")],
                h.span(".fw-semibold")[str(len(self.screening_questions))],
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
                CitationRowDisplay(row, self.review, self.status_fetcher)
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
            "hx_target": "#l2-screening-component",
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


class L2ScreeningPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["review"]
        page_obj = self.context["page_obj"]
        component = L2ScreeningComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=tdt("L2 Screening")),
            ],
            h.h1[tdt("L2 Screening")],
            h.div(".mb-3")[
                h.button(
                    "#refresh-button.btn.btn-outline-secondary",
                    type="button",
                )[tdt("Refresh")],
            ],
            component.render(),
        ]
