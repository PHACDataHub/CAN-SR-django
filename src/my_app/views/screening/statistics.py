from django.http import HttpResponse
from django.views import View

import htpy as h

from proj.htpy.components import PercentFormatter
from proj.htpy.modal_component import ModalComponent
from proj.text import tdt

from my_app.models import L1ScreeningQuestion, L2ScreeningQuestion
from my_app.queries import (
    ReviewStage,
    get_citations_for_stage,
    get_screening_answer_metrics,
)
from my_app.router import route
from my_app.views.view_utils import MustAccessReviewMixin


def ConfusionMatrixCell(label, count):
    return h.td(".text-center")[
        h.div(".small")[label],
        h.div(".fw-semibold")[str(count)],
    ]


def ScreeningConfusionMatrix(metric):
    return h.table(".table.table-sm.table-bordered.align-middle.mb-0")[
        h.caption(".caption-top.text-body")[tdt("Confusion matrix")],
        h.thead[
            h.tr[
                h.th(scope="col")[tdt("AI / Human")],
                h.th(".text-center", scope="col")[tdt("Human screened in")],
                h.th(".text-center", scope="col")[tdt("Human screened out")],
            ]
        ],
        h.tbody[
            h.tr[
                h.th(scope="row")[tdt("AI screened in")],
                ConfusionMatrixCell(
                    tdt("True positives"), metric.true_positives
                ),
                ConfusionMatrixCell(
                    tdt("False negatives"), metric.false_negatives
                ),
            ],
            h.tr[
                h.th(scope="row")[tdt("AI screened out")],
                ConfusionMatrixCell(
                    tdt("False positives"), metric.false_positives
                ),
                ConfusionMatrixCell(
                    tdt("True negatives"), metric.true_negatives
                ),
            ],
        ],
    ]


def ScreeningMetricRate(value):
    if value is None:
        return tdt("Not available")
    return PercentFormatter(value, places=1)


def ScreeningMetricDetails(metric):
    counts = [
        (tdt("Paired answers"), str(metric.observations)),
        (tdt("Exact agreements"), str(metric.exact_agreements)),
        (tdt("Missing answer pairs"), str(metric.missing)),
    ]
    rates = [
        (tdt("Accuracy (exact agreement)"), metric.accuracy),
        (tdt("Precision"), metric.precision),
        (tdt("Recall"), metric.recall),
        (tdt("F1 score"), metric.f1),
        (tdt("Negative predictive value"), metric.npv),
    ]
    values = counts + [
        (label, ScreeningMetricRate(value)) for label, value in rates
    ]
    return h.dl(".row.mb-0")[
        [
            h.div(".col-sm-6.mb-2")[
                h.dt(".small")[label],
                h.dd(".mb-0")[value],
            ]
            for label, value in values
        ]
    ]


def ScreeningMetricSummary(metric):
    return h.div(".row.g-3")[
        h.div(".col-lg-5")[ScreeningConfusionMatrix(metric)],
        h.div(".col-lg-7")[ScreeningMetricDetails(metric)],
    ]


def ScreeningStatisticsModal(review, stage, question_model, title):
    questions = question_model.active_objects.filter(
        review=review, disable_screening=False
    ).order_by("id")
    by_question, overall = get_screening_answer_metrics(
        review.id,
        stage,
        citations=get_citations_for_stage(review.id, stage),
    )
    question_sections = [
        h.section(".border-top.pt-3.mt-3", data_question_id=question.id)[
            h.h3(".h5")[question.question_text],
            ScreeningMetricSummary(by_question[question.id]),
        ]
        for question in questions
    ]
    if not question_sections:
        question_sections = h.p(".text-muted")[tdt("No screening questions.")]

    return ModalComponent(
        title=title,
        size_cls="modal-xl screening-metrics-modal",
        close_button_text=tdt("Close"),
        aria_labelledby="screening-statistics-title",
        header=h.fragment[
            h.h1("#screening-statistics-title.modal-title.fs-5")[title],
            h.button(
                ".btn-close",
                type="button",
                data_modal_close=True,
                aria_label=tdt("Close"),
            ),
        ],
    )[
        h.p(".text-muted.small")[
            tdt(
                "Statistics compare completed AI answers with human answers. "
                "Review totals combine answer pairs across all enabled screening questions. "
                "Missing pairs have no eligible AI answer or human answer."
            )
        ],
        h.section[
            h.h2(".h4")[tdt("Review overall")],
            ScreeningMetricSummary(overall),
        ],
        h.h2(".h4.mt-4")[tdt("By question")],
        question_sections,
    ]


class ScreeningStatisticsView(MustAccessReviewMixin, View):
    stage = None
    question_model = None
    title = None

    def get(self, request, *args, **kwargs):
        return HttpResponse(
            str(
                ScreeningStatisticsModal(
                    self.review, self.stage, self.question_model, self.title
                )
            )
        )


@route(
    "/reviews/<int:review_id>/screening_l1/statistics/",
    name="l1_screening_statistics",
)
class L1ScreeningStatisticsView(ScreeningStatisticsView):
    stage = ReviewStage.L1_SCREENING
    question_model = L1ScreeningQuestion
    title = tdt("L1 screening statistics")


@route(
    "/reviews/<int:review_id>/screening_l2/statistics/",
    name="l2_screening_statistics",
)
class L2ScreeningStatisticsView(ScreeningStatisticsView):
    stage = ReviewStage.L2_SCREENING
    question_model = L2ScreeningQuestion
    title = tdt("L2 screening statistics")
