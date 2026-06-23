from dataclasses import dataclass

from proj.htpy import definition_list as DefList

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningResult,
    Review,
    ScreeningResultStatus,
)
from my_app.queries import (
    L1ScreeningStatusFetcher,
    get_l1_screening_progress_stats,
)
from my_app.views.screening.components import (
    CitationScreeningProgressNav,
    human_review_control_id,
    render_human_review_control,
)
from my_app.views.screening.util import BADGE_CLASSES, get_page_number
from my_app.views.view_utils import url_with_same_params
from shortcuts import BasePageTemplate
from shortcuts import breadcrumbs as bc
from shortcuts import cached_property, get_request
from shortcuts import htpy as h
from shortcuts import reverse, tdt


def CitationRowDisplay(citation_row: Citation, review: Review):
    request = get_request()
    details_url = reverse(
        "screen_l1_row_details", args=[review.id, citation_row.id]
    )

    fetcher = L1ScreeningStatusFetcher.get_instance()
    status = fetcher.get(citation_row.id)

    if status is ScreeningResultStatus.NOT_STARTED:
        screen_action_url = url_with_same_params(
            request,
            path=reverse(
                "screen_l1_row",
                args=[review.id, citation_row.id],
            ),
            page=get_page_number(),
        )
        button_markup = (
            h.button(
                ".btn.btn-outline-primary.btn-sm",
                type="button",
                hx_post=screen_action_url,
                hx_target="closest .citation-item",
                hx_swap="innerHTML",
                hx_disabled_elt="this",
            )[tdt("Screen this row")],
        )
    else:
        button_markup = h.button(
            ".btn.btn-outline-secondary.btn-sm.btn-disabled.disabled",
            type="button",
            disabled=True,
        )[tdt("Screening")]

    row_id = f"l1-screening-row-{citation_row.id}"

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
            ],
            h.div(".d-flex.flex-column.align-items-end.gap-2")[
                CitationRowL1StatusBadge(citation_row), button_markup
            ],
        ],
        h.a(
            ".btn.btn-outline-secondary.btn-sm.position-absolute.bottom-0.end-0.me-3.mb-2",
            href=details_url,
        )[tdt("View more")],
    ]


def badge_id(citation_row):
    return f"l1-screening-row-status-{citation_row.id}"


def CitationRowL1StatusBadge(citation_row):
    fetcher = L1ScreeningStatusFetcher.get_instance()
    status = fetcher.get(citation_row.id)
    return h.div(
        id=badge_id(citation_row),
        tabindex="-1",
        class_=f"badge rounded-pill {BADGE_CLASSES[status]}",
    )[status.label]


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
                "screen_l1_row_process",
                args=[review.id, citation_row.id],
            ),
            hx_target="closest .l1-citation-screening-control",
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


@dataclass
class L1ScreeningComponent:
    review: Review
    page_obj: object
    request: object

    @property
    def component_url(self):
        return reverse("screening_l1_component", args=[self.review.id])

    @property
    def shell_url(self):
        return reverse("screening_l1", args=[self.review.id])

    @property
    def page_number(self):
        return self.page_obj.number

    @cached_property
    def citation_rows(self):
        return Citation.objects.filter(dataset__review=self.review).order_by(
            "order"
        )

    @cached_property
    def page_rows(self):
        return list(self.page_obj.object_list)

    @cached_property
    def page_row_ids(self):
        return [row.id for row in self.page_rows]

    @cached_property
    def screening_questions(self):
        return list(
            L1ScreeningQuestion.objects.filter(
                review=self.review
            ).prefetch_related("options")
        )

    @cached_property
    def total_citations(self):
        return self.citation_rows.count()

    @cached_property
    def screened_citations(self):
        return (
            L1ScreeningResult.objects.filter(
                citation__dataset__review=self.review
            )
            .values_list("citation_id", flat=True)
            .distinct()
            .count()
        )

    @cached_property
    def status_fetcher(self):
        fetcher = L1ScreeningStatusFetcher.get_instance()
        fetcher.prefetch_keys(self.page_row_ids)
        return fetcher

    def render(self):
        return h.div(
            id="l1-screening-component",
            hx_target="this",
            hx_get=self.page_url(self.page_number, self.component_url),
            hx_trigger="click from:#refresh-button",
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
            id="l1-screening-progress-panel",
            class_="border rounded p-3 bg-body-tertiary",
        )[
            h.h2(".h5.mb-3")[tdt("Progress")],
            h.div(".d-flex.justify-content-between.align-items-center.mb-2")[
                h.span[tdt("Total citations")],
                h.span(".fw-semibold")[str(self.total_citations)],
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
                CitationRowDisplay(row, self.review) for row in self.page_rows
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
            "hx_target": "#l1-screening-component",
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


class L1ScreeningPageTemplate(BasePageTemplate):
    def content(self):
        review = self.context["review"]
        page_obj = self.context["page_obj"]
        component = L1ScreeningComponent(
            review=review,
            page_obj=page_obj,
            request=self.request,
        )

        return [
            bc.BreadcrumbTrailForReview(review)[
                bc.BreadcrumbItem(label=tdt("L1 Screening")),
            ],
            h.h1[tdt("L1 Screening")],
            h.div(".mb-3")[
                h.button(
                    "#refresh-button.btn.btn-outline-secondary",
                    type="button",
                )[tdt("Refresh")],
            ],
            component.render(),
        ]


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
                    href=reverse("screening_l1", args=[review.id]),
                ),
                bc.BreadcrumbItem(label=tdt("Citation screening")),
            ],
            h.h1[tdt("L1 citation screening")],
            CitationScreeningProgressNav(
                self.citation_row,
                review,
                detail_route_name="screen_l1_row_details",
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
                    "screen_l1_row_process",
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
        if result.confidence is None:
            confidence_value = tdt("None")
        else:
            confidence_value = str(result.confidence)

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
                (tdt("Confidence"), confidence_value),
                (tdt("Notes"), result.explanation or tdt("None")),
            ]
        )


def l1_human_review_control_id(result):
    return human_review_control_id("l1", result)


def render_l1_human_review_control(result: L1ScreeningResult, review: Review):
    return render_human_review_control(
        result,
        prefix="l1",
        answer_url=reverse(
            "screen_l1_human_answer", args=[review.id, result.id]
        ),
        validate_url=reverse(
            "screen_l1_validate_correct", args=[review.id, result.id]
        ),
        undo_validation_url=reverse(
            "screen_l1_undo_validation", args=[review.id, result.id]
        ),
    )
