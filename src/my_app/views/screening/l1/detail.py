from proj.htpy import definition_list as DefList
from proj.htpy.components import PercentFormatter

from my_app.models import (
    Citation,
    L1ScreeningResult,
    Review,
    ScreeningResultStatus,
)
from my_app.queries import (
    L1ScreeningStatusFetcher,
    get_l1_screening_progress_stats,
)
from my_app.router import route
from my_app.views.screening.components import (
    CitationScreeningProgressNav,
    human_review_control_id,
    render_human_review_control,
)
from my_app.views.screening.l1.list import CitationRowL1StatusBadge
from my_app.views.view_utils import MustAccessReviewMixin
from shortcuts import BasePageTemplate, DetailView, HtpyTemplateMixin
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property
from shortcuts import htpy as h
from shortcuts import reverse, tdt


def l1_screening_control_id(citation_row):
    return f"l1-citation-screening-control-{citation_row.id}"


def render_l1_screening_control(citation_row, review, status_fetcher=None):
    if status_fetcher is None:
        status_fetcher = L1ScreeningStatusFetcher.get_instance()

    status = status_fetcher.get(citation_row.id)
    screen_button = None
    if status is ScreeningResultStatus.NOT_STARTED:
        screen_button = h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_post=reverse(
                "l1_citation_process_screening",
                args=[review.id, citation_row.id],
            ),
            hx_target="closest .l1-citation-screening-control",
            hx_select=f"#{l1_screening_control_id(citation_row)}",
            hx_swap="outerHTML",
            hx_disabled_elt="this",
        )[tdt("Screen this citation")]

    return h.div(
        ".l1-citation-screening-control.d-flex.flex-wrap.align-items-center.gap-2",
        id=l1_screening_control_id(citation_row),
    )[
        h.div[
            h.span(".text-muted.me-1")[tdt("L1 screening")],
            CitationRowL1StatusBadge(citation_row),
        ],
        screen_button,
    ]


def l1_human_review_control_id(result):
    return human_review_control_id("l1", result)


def render_l1_human_review_control(result: L1ScreeningResult, review: Review):
    return render_human_review_control(
        result,
        prefix="l1",
        answer_url=reverse(
            "l1_citation_human_answer", args=[review.id, result.id]
        ),
        validate_url=reverse(
            "l1_citation_validate_correct", args=[review.id, result.id]
        ),
        undo_validation_url=reverse(
            "l1_citation_undo_validation", args=[review.id, result.id]
        ),
    )


class L1CitationScreeningPage(BasePageTemplate):
    @property
    def citation_row(self) -> Citation:
        return self.context["object"]

    @property
    def review(self):
        return self.context["review"]

    @cached_property
    def screening_columns(self):
        return list(self.citation_row.dataset.screening_columns.order_by("id"))

    @cached_property
    def screening_results(self):
        return list(
            L1ScreeningResult.objects.filter(citation=self.citation_row)
            .select_related(
                "question",
                "selected_option",
                "human_selected_answer",
                "human_validated_by",
            )
            .order_by("question_id")
        )

    @cached_property
    def included_field_names(self):
        return [column.name for column in self.screening_columns]

    @cached_property
    def other_field_pairs(self):
        return [
            (key, DefList.render_dl_value(value))
            for key, value in self.citation_row.data.items()
            if key not in self.included_field_names
        ]

    def content(self):
        review = self.review

        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(
                    label=tdt("L1 Screening"),
                    href=reverse("l1_citations_list", args=[review.id]),
                ),
                bc.BreadcrumbItem(label=tdt("Citation screening")),
            ],
            h.h1[tdt("L1 citation screening")],
            CitationScreeningProgressNav(
                self.citation_row,
                review,
                detail_route_name="l1_citation_detail",
                progress_stats=get_l1_screening_progress_stats(review.id),
                nav_label=tdt("L1 citation navigation"),
            ),
            h.div(".row.g-4")[
                h.div(".col-lg-8")[self.render_citation_panel()],
                h.div(".col-lg-4")[
                    h.div(".vstack.gap-4")[
                        self.render_screening_panel(),
                        self.render_results_panel(),
                    ]
                ],
            ],
        ]

    def render_citation_panel(self):
        citation_row = self.citation_row
        return h.section(".border.rounded.p-3")[
            h.h2(".h5.mb-3")[tdt("Citation")],
            h.div(".vstack.gap-4")[
                h.div[
                    h.div(".small.text-muted.mb-1")[tdt("Title")],
                    h.div(".fs-5.fw-semibold")[
                        citation_row.title or tdt("Untitled citation")
                    ],
                ],
                h.div[
                    h.div(".small.text-muted.mb-1")[tdt("Abstract")],
                    h.p(".mb-0")[
                        citation_row.abstract or tdt("No abstract available.")
                    ],
                ],
                self.render_included_fields(),
                self.render_other_fields(),
            ],
        ]

    def render_included_fields(self):
        if not self.screening_columns:
            return None

        return h.div[
            h.h3(".h6.mb-2")[tdt("Included fields")],
            DefList.DL(
                [
                    (
                        column.name,
                        DefList.render_dl_value(
                            self.citation_row.data.get(column.name)
                        ),
                    )
                    for column in self.screening_columns
                ]
            ),
        ]

    def render_other_fields(self):
        if not self.other_field_pairs:
            return None

        return h.details[
            h.summary[tdt("Other fields")],
            h.div(".mt-3")[DefList.DL(self.other_field_pairs)],
        ]

    def render_screening_panel(self):
        status_fetcher = L1ScreeningStatusFetcher.get_instance()
        status = status_fetcher.get(self.citation_row.id)

        return h.section(".border.rounded.p-3.bg-body-tertiary")[
            h.h2(".h5.mb-3")[tdt("Screening")],
            h.div(".vstack.gap-3")[
                render_l1_screening_control(
                    self.citation_row,
                    self.review,
                    status_fetcher,
                ),
                (
                    self.render_rescreen_button()
                    if status is not ScreeningResultStatus.NOT_STARTED
                    else None
                ),
            ],
        ]

    def render_rescreen_button(self):
        return h.div[
            h.button(
                ".btn.btn-outline-primary.btn-sm",
                type="button",
                hx_post=reverse(
                    "l1_citation_process_screening",
                    args=[self.review.id, self.citation_row.id],
                ),
                hx_target=f"#{l1_screening_control_id(self.citation_row)}",
                hx_swap="outerHTML",
                hx_disabled_elt="this",
            )[tdt("Re-screen")]
        ]

    def render_results_panel(self):
        results = self.screening_results

        return h.section(".border.rounded.p-3")[
            h.div(".d-flex.justify-content-between.align-items-center.mb-3")[
                h.h2(".h5.mb-0")[tdt("L1 screening results")],
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
                else h.p(".text-muted.mb-0")[tdt("No screening results yet.")]
            ),
        ]

    def render_result(self, result: L1ScreeningResult):

        return DefList.DL(
            [
                (tdt("Question"), result.question.question_text),
                (
                    tdt("Status"),
                    ScreeningResultStatus(result.status).label,
                ),
                (
                    tdt("Selected option"),
                    render_l1_human_review_control(result, self.review),
                ),
                (tdt("Confidence"), PercentFormatter(result.confidence)),
                (tdt("Notes"), result.explanation or tdt("None")),
            ]
        )


@route(
    "/reviews/<int:review_id>/screening_l1/rows/<int:row_pk>/details/",
    name="l1_citation_detail",
)
class L1CitationScreeningView(
    MustAccessReviewMixin, DetailView, HtpyTemplateMixin
):
    model = Citation
    pk_url_kwarg = "row_pk"
    template_component = L1CitationScreeningPage

    def get_queryset(self):
        return (
            Citation.objects.filter(dataset__review=self.review)
            .select_related("dataset")
            .prefetch_related("dataset__screening_columns")
            .order_by("order")
        )
