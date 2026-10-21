import json
from collections import defaultdict

import htpy as h
from data_fetcher import cache_within_request

from proj.htpy.components import PercentFormatter
from proj.htpy.modal_component import get_modal_size_for_current_request

from my_app.constants import DEFAULT_CONFIDENCE
from my_app.models import (
    Citation,
    CitationAIStatus,
    CitationHumanStatus,
    CitationStatus,
    DocumentFigure,
    DocumentTable,
    L1HumanAnswer,
    L1ScreeningQuestion,
    L1ScreeningResult,
    L2HumanAnswer,
    L2ScreeningQuestion,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    ScreeningResultStatus,
)
from my_app.views.screening.components import (
    CriticalAgentDefinitionItems,
    SelectedOption,
    render_answer_timestamp,
    render_selected_option,
)
from shortcuts import cached_property, reverse, tdt


class ScreeningData:
    def __init__(self, citation, stage, question_id=None):
        self.citation = citation
        self.stage = stage
        self.filters = {"citation": citation}
        if question_id is not None:
            self.filters["question_id"] = question_id

    @cached_property
    def results(self):
        model = L1ScreeningResult
        if self.stage == "l2":
            model = L2ScreeningResult
        elif self.stage == "parameters":
            model = ParameterExtractionResult
        related = ["selected_option", "language_model"]
        if self.stage != "parameters":
            related += [
                "critical_result__selected_option",
                "critical_result__language_model",
            ]
        return {
            result.question_id: result
            for result in model.objects.filter(**self.filters).select_related(
                *related
            )
        }

    @cached_property
    def human_answers(self):
        model = L1HumanAnswer
        if self.stage == "l2":
            model = L2HumanAnswer
        elif self.stage == "parameters":
            model = ParameterHumanAnswer
        grouped = defaultdict(list)
        for answer in (
            model.objects.filter(**self.filters)
            .select_related("user", "selected_option")
            .order_by("-updated_at", "-pk")
        ):
            grouped[answer.question_id].append(answer)
        return grouped


def DefinitionList(items):
    return h.dl(".row.mb-0")[
        [
            h.fragment[
                h.dt(".col-sm-4")[label],
                h.dd(".col-sm-8.text-break.detail-value")[value],
            ]
            for label, value in items
        ]
    ]


def JsonValue(value):
    if isinstance(value, (dict, list)):
        return h.pre(".text-wrap.mb-0")[
            json.dumps(value, indent=2, ensure_ascii=False)
        ]
    if value is None:
        return tdt("Not provided")
    return str(value)


def ResultMetadata(result):
    confidence = tdt("Not recorded")
    if result.confidence is not None:
        confidence = PercentFormatter(result.confidence)
    items = [
        (tdt("Status"), result.get_status_display()),
        (
            tdt("Language model"),
            str(result.language_model or tdt("Not recorded")),
        ),
        (tdt("Confidence"), confidence),
        (tdt("Created"), render_answer_timestamp(result.created_at)),
        (tdt("Updated"), render_answer_timestamp(result.updated_at)),
    ]
    if result.abandoned_at:
        items.append(
            (tdt("Abandoned"), render_answer_timestamp(result.abandoned_at))
        )
    return DefinitionList(items)


def AnswerComparison(result, answers):
    valid_answers = [
        answer for answer in answers if answer.selected_option_id is not None
    ]
    if (
        result is None
        or result.status != ScreeningResultStatus.COMPLETED
        or result.selected_option_id is None
        or not valid_answers
    ):
        return h.p(".text-muted.small")[
            tdt("AI and human answers are not yet available for comparison.")
        ]
    agrees = all(
        answer.selected_option_id == result.selected_option_id
        for answer in valid_answers
    )
    label = tdt("AI and human answers agree")
    css = ".alert.alert-success.py-2"
    if not agrees:
        label = tdt("AI and human answers disagree")
        css = ".alert.alert-warning.py-2"
    return h.div(css)[label]


def StageDetailLink(citation, stage):
    args = [citation.dataset.review_id, citation.pk]
    if stage == "l1":
        url = reverse("l1_citation_detail", args=args)
        label = tdt("Open L1 citation page")
    elif stage == "l2":
        url = reverse("l2_citation_detail", args=args)
        label = tdt("Open L2 citation page")
    else:
        url = reverse("parameter_extraction_citation_detail", args=args)
        label = tdt("Open parameter extraction citation page")
    return h.a(
        ".btn.btn-outline-secondary.btn-sm",
        href=url,
        target="_blank",
        rel="noopener noreferrer",
    )[
        label,
        " ",
        h.svg(
            xmlns="http://www.w3.org/2000/svg",
            viewBox="0 0 24 24",
            width="16",
            height="16",
            fill="none",
            stroke="currentColor",
            stroke_width="2",
            aria_hidden="true",
            focusable="false",
        )[
            h.path(
                d="M15 3h6v6M10 14 21 3M21 14v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h6"
            ),
        ],
        h.span(".visually-hidden")[tdt("(opens in a new tab)")],
    ]


def HumanAnswers(answers, *, parameter=False, screening_disabled=False):
    if not answers:
        return h.p(".text-muted")[tdt("No human answers yet.")]
    return [
        h.article(".border.rounded.p-3.mb-3")[
            h.h3(".h6")[AuthorName(answer)],
            (
                ParameterValue(answer)
                if parameter
                else SelectedOption(
                    answer.selected_option,
                    screening_disabled=screening_disabled,
                )
            ),
            DefinitionList(
                [
                    (tdt("Notes"), answer.notes or tdt("No notes")),
                    (
                        tdt("Created"),
                        render_answer_timestamp(answer.created_at),
                    ),
                    (
                        tdt("Updated"),
                        render_answer_timestamp(answer.updated_at),
                    ),
                ]
            ),
        ]
        for answer in answers
    ]


def AuthorName(answer):
    if answer.user is None:
        return tdt("Unknown user")
    return answer.user.get_full_name() or answer.user.get_username()


def CriticalDetails(result, *, screening_disabled=False):
    critical = getattr(result, "critical_result", None)
    if critical is None:
        return h.p(".text-muted")[tdt("No critical agent review yet.")]
    return h.fragment[
        DefinitionList(CriticalAgentDefinitionItems(result)),
        ResultMetadata(critical),
        (
            SelectedOption(
                critical.selected_option, screening_disabled=screening_disabled
            )
            if critical.selected_option_id
            else None
        ),
        (
            h.p(".text-danger.detail-value", role="alert")[critical.error]
            if critical.error
            else None
        ),
    ]


@cache_within_request
def get_evidence_sources(citation):
    extraction = getattr(citation.document, "text_extraction_result", None)
    sentences = []
    if extraction is not None:
        sentences = extraction.get_sentence_list()
    tables = {}
    figures = {}
    if citation.document_id:
        tables = {
            item.index: item
            for item in DocumentTable.objects.filter(
                document_id=citation.document_id,
            )
        }
        figures = {
            item.index: item
            for item in DocumentFigure.objects.filter(
                document_id=citation.document_id,
            )
        }
    return sentences, tables, figures


def EvidenceDetails(result, citation):
    sentences, tables, figures = get_evidence_sources(citation)
    return DefinitionList(
        [
            (
                tdt("Evidence sentences"),
                EvidenceReferences(result.evidence_sentences, sentences),
            ),
            (
                tdt("Evidence tables"),
                EvidenceArtifacts(result.evidence_tables, tables),
            ),
            (
                tdt("Evidence figures"),
                EvidenceArtifacts(result.evidence_figures, figures),
            ),
        ]
    )


def EvidenceReferences(indices, sentences):
    if not indices:
        return tdt("None recorded")
    return h.ul(".ps-3.mb-0")[
        [
            h.li[
                str(index),
                ": ",
                (
                    sentences[index]
                    if type(index) is int and 0 <= index < len(sentences)
                    else tdt("Source text unavailable")
                ),
            ]
            for index in indices
        ]
    ]


def EvidenceArtifacts(indices, artifacts):
    if not indices:
        return tdt("None recorded")
    return h.ul(".ps-3.mb-0")[
        [
            h.li[
                str(index),
                ": ",
                ArtifactDetails(artifacts.get(index)),
            ]
            for index in indices
        ]
    ]


def ArtifactDetails(artifact):
    if artifact is None:
        return tdt("Source unavailable")
    return h.fragment[
        h.p[artifact.caption],
        h.p[artifact.description],
        h.pre(".text-wrap")[getattr(artifact, "table_markdown", "")],
        (
            h.img(
                ".img-fluid",
                src=artifact.file.url,
                alt=artifact.caption or tdt("Evidence figure"),
            )
            if getattr(artifact, "file", None)
            else None
        ),
    ]


def AIAnswer(result, citation, *, parameter=False, screening_disabled=False):
    if result is None:
        return h.p(".text-muted")[tdt("No AI answer yet.")]
    notice = None
    if result.status == ScreeningResultStatus.PENDING:
        notice = h.p(".alert.alert-info.py-2", role="status")[
            tdt("AI answer is pending.")
        ]
    elif result.status == ScreeningResultStatus.ABANDONED:
        notice = h.p(".alert.alert-danger.py-2", role="alert")[
            tdt("AI screening could not be completed.")
        ]
    return h.fragment[
        notice,
        (
            ParameterValue(result)
            if parameter
            else SelectedOption(
                result.selected_option, screening_disabled=screening_disabled
            )
        ),
        h.p(".detail-value.mt-2")[
            result.explanation or tdt("No explanation recorded.")
        ],
        ResultMetadata(result),
        (
            EvidenceDetails(result, citation)
            if hasattr(result, "evidence_sentences")
            else None
        ),
    ]


def AnswerDetails(citation, question, data):
    result = data.results.get(question.pk)
    answers = data.human_answers.get(question.pk, [])
    threshold = question.confidence
    if threshold is None:
        threshold = question.review.confidence
    if threshold is None:
        threshold = DEFAULT_CONFIDENCE
    return h.div[
        h.h2(".h5")[citation.title or tdt("Untitled citation")],
        h.p(".small.text-muted")[tdt("Citation ID"), ": ", str(citation.pk)],
        CitationModalButton(citation, question, data.stage),
        h.p[StageDetailLink(citation, data.stage)],
        h.h2(".h5")[question.question_text],
        DefinitionList(
            [
                (
                    tdt("Screening enabled"),
                    tdt("No") if question.disable_screening else tdt("Yes"),
                ),
                (
                    tdt("Deleted question"),
                    tdt("Yes") if question.deletion_time else tdt("No"),
                ),
                (tdt("Confidence threshold"), PercentFormatter(threshold)),
            ]
        ),
        h.details(".border.rounded.p-3.mb-3")[
            h.summary[tdt("Answer options and definitions")],
            [
                h.div(".mt-3")[
                    render_selected_option(option),
                    h.p(".small")[option.get_screening_action_display()],
                    (
                        h.p(".text-muted")[tdt("Deleted option")]
                        if option.deletion_time
                        else None
                    ),
                ]
                for option in question.options.all()
            ],
        ],
        AnswerComparison(result, answers),
        h.section(".border.rounded.p-3.mb-3")[
            h.h2(".h5")[tdt("AI answer")],
            AIAnswer(
                result, citation, screening_disabled=question.disable_screening
            ),
        ],
        h.section(".border.rounded.p-3.mb-3")[
            h.h2(".h5")[tdt("Critical agent review")],
            CriticalDetails(
                result, screening_disabled=question.disable_screening
            ),
        ],
        h.section[
            h.h2(".h5")[tdt("Human answers"), " (", str(len(answers)), ")"],
            h.p(".small.text-muted")[
                tdt(
                    "Newest answers are shown first. The latest answer determines the human screening status."
                )
            ],
            HumanAnswers(
                answers, screening_disabled=question.disable_screening
            ),
        ],
        h.div(
            id=f"answer-citation-modal-slot-{data.stage}-{citation.pk}-{question.pk}",
            data_modal_slot=True,
        ),
    ]


def CitationModalButton(citation, question, stage):
    if get_modal_size_for_current_request() != "xl":
        return None
    url = reverse("citation_detail_modal", args=[citation.pk])
    return h.button(
        ".btn.btn-outline-primary.btn-sm.mb-3",
        type="button",
        hx_get=f"{url}?stage={stage}&size=lg",
        hx_target=f"#answer-citation-modal-slot-{stage}-{citation.pk}-{question.pk}",
        hx_swap="innerHTML",
    )[tdt("Citation details")]


def AnswerModalButton(citation, question, stage):
    if get_modal_size_for_current_request() != "xl":
        return None
    if stage == "l1":
        url = reverse(
            "l1_answer_detail_modal", args=[citation.pk, question.pk]
        )
    else:
        url = reverse(
            "l2_answer_detail_modal", args=[citation.pk, question.pk]
        )
    return h.button(
        ".btn.btn-outline-primary.btn-sm",
        id=f"citation-{citation.pk}-{stage}-question-{question.pk}",
        type="button",
        hx_get=f"{url}?size=lg",
        hx_target=f"#citation-answer-modal-slot-{citation.pk}",
        hx_swap="innerHTML",
        aria_label=f"{tdt('Answer details')}: {question.question_text}",
    )[tdt("Answer details")]


def ScreeningSection(citation, stage, expanded):
    model = L1ScreeningQuestion
    if stage == "l2":
        model = L2ScreeningQuestion
    questions = list(
        model.objects.filter(review_id=citation.dataset.review_id).order_by(
            "pk"
        )
    )
    data = ScreeningData(citation, stage)
    return h.details(
        ".border.rounded.p-3.mb-3", open=expanded, data_detail_stage=stage
    )[
        h.summary(".fw-semibold")[
            tdt(f"{stage.upper()} screening"), " (", str(len(questions)), ")"
        ],
        h.div(".mt-3")[
            h.p[StageDetailLink(citation, stage)],
            [
                QuestionSummary(citation, question, stage, data)
                for question in questions
            ]
            or h.p[tdt("No screening questions.")],
        ],
    ]


def QuestionSummary(citation, question, stage, data):
    result = data.results.get(question.pk)
    answers = data.human_answers.get(question.pk, [])
    ai_status = tdt("Not started")
    if result is not None:
        ai_status = result.get_status_display()
    human_status = tdt("Unanswered")
    if answers:
        human_status = SelectedOption(
            answers[0].selected_option,
            screening_disabled=question.disable_screening,
        )
    return h.article(".border-top.py-3")[
        h.h3(".h6")[question.question_text],
        (
            h.p(".text-muted.small")[tdt("Deleted question")]
            if question.deletion_time
            else None
        ),
        (
            h.p(".text-muted.small")[tdt("Screening disabled")]
            if question.disable_screening
            else None
        ),
        DefinitionList(
            [
                (tdt("AI status"), ai_status),
                (tdt("Latest human answer"), human_status),
                (tdt("Human answers"), str(len(answers))),
            ]
        ),
        AnswerComparison(result, answers),
        AnswerModalButton(citation, question, stage),
    ]


def ParameterValue(answer):
    if not answer.found:
        return h.p[tdt("Not found")]
    return DefinitionList(
        [
            (tdt("Found"), tdt("Yes")),
            (tdt("Value"), answer.value or tdt("No value recorded")),
            (
                tdt("Selected option"),
                str(answer.selected_option or tdt("None")),
            ),
        ]
    )


def ParametersSection(citation, expanded):
    parameters = list(
        Parameter.objects.filter(
            review_id=citation.dataset.review_id
        ).order_by("pk")
    )
    data = ScreeningData(citation, "parameters")
    completed = sum(
        result.status == ScreeningResultStatus.COMPLETED
        for result in data.results.values()
    )
    return h.details(
        ".border.rounded.p-3.mb-3",
        open=expanded,
        data_detail_stage="parameters",
    )[
        h.summary(".fw-semibold")[
            tdt("Parameters"),
            " (",
            str(len(parameters)),
            ")",
            h.span(".small.fw-normal.ms-2")[
                tdt("AI extraction completed"),
                ": ",
                str(completed),
                " / ",
                str(len(parameters)),
            ],
        ],
        h.p(".mt-3")[
            tdt("Parameters with human answers"),
            ": ",
            str(len(data.human_answers)),
            " / ",
            str(len(parameters)),
        ],
        h.p[StageDetailLink(citation, "parameters")],
        [
            h.details(".border-top.py-3")[
                h.summary[parameter.name],
                h.p(".mt-3.detail-value")[parameter.description],
                DefinitionList(
                    [
                        (
                            tdt("Answer type"),
                            parameter.get_option_type_display(),
                        ),
                        (
                            tdt("Units and reporting instructions"),
                            parameter.units_and_reporting_instructions,
                        ),
                        (
                            tdt("Calculation instructions"),
                            parameter.calculation_instructions,
                        ),
                    ]
                ),
                (
                    h.p[tdt("Deleted parameter")]
                    if parameter.deletion_time
                    else None
                ),
                h.h3(".h6")[tdt("AI answer")],
                AIAnswer(
                    data.results.get(parameter.pk), citation, parameter=True
                ),
                h.h3(".h6")[tdt("Human answers")],
                HumanAnswers(
                    data.human_answers.get(parameter.pk, []), parameter=True
                ),
            ]
            for parameter in parameters
        ]
        or h.p[tdt("No parameters.")],
    ]


def CitationDetails(citation, stage):
    statuses = Citation.objects.filter(pk=citation.pk)
    for level in ("l1", "l2"):
        for kind in ("ai", "human", "overall"):
            statuses = getattr(statuses, f"add_{level}_{kind}_status")()
    status = statuses.get()
    priority = set(
        citation.dataset.screening_columns.values_list("name", flat=True)
    )
    fields = sorted(
        citation.data.items(),
        key=lambda item: (item[0] not in priority, item[0]),
    )
    return h.div[
        h.h2(".h4")[citation.title or tdt("Untitled citation")],
        h.p(".small.text-muted")[tdt("Citation ID"), ": ", str(citation.pk)],
        h.h2(".h5")[tdt("Abstract")],
        h.p(".detail-value")[
            citation.abstract or tdt("No abstract available.")
        ],
        h.div(".table-responsive.mb-3")[
            h.table(".table.table-sm")[
                h.caption(".caption-top")[tdt("Screening status")],
                h.thead[
                    h.tr[
                        [
                            h.th(scope="col")[label]
                            for label in (
                                tdt("Stage"),
                                tdt("AI"),
                                tdt("Human"),
                                tdt("Overall"),
                            )
                        ]
                    ]
                ],
                h.tbody[
                    [
                        h.tr[
                            h.th(scope="row")[level.upper()],
                            h.td[
                                CitationAIStatus(
                                    getattr(status, f"{level}_ai_status")
                                ).label
                            ],
                            h.td[
                                CitationHumanStatus(
                                    getattr(status, f"{level}_human_status")
                                ).label
                            ],
                            h.td[
                                CitationStatus(
                                    getattr(status, f"{level}_overall_status")
                                ).label
                            ],
                        ]
                        for level in ("l1", "l2")
                    ]
                ],
            ]
        ],
        h.details(".border.rounded.p-3.mb-3")[
            h.summary(".fw-semibold")[tdt("Citation fields")],
            h.p(".small.text-muted.mt-2")[
                tdt("Fields used in L1 screening appear first.")
            ],
            (
                DefinitionList(
                    [
                        (
                            name,
                            h.fragment[
                                (
                                    h.span(".badge.text-bg-secondary.me-2")[
                                        tdt("L1 field")
                                    ]
                                    if name in priority
                                    else None
                                ),
                                JsonValue(value),
                            ],
                        )
                        for name, value in fields
                    ]
                )
                if fields
                else h.p[tdt("No additional fields.")]
            ),
        ],
        ScreeningSection(citation, "l1", stage == "l1"),
        ScreeningSection(citation, "l2", stage == "l2"),
        ParametersSection(citation, stage == "parameters"),
        h.div(
            id=f"citation-answer-modal-slot-{citation.pk}",
            data_modal_slot=True,
        ),
        h.p[
            tdt("Linked document"),
            ": ",
            str(citation.document or tdt("No document uploaded")),
        ],
    ]


def ParameterAnswerDetails(citation, question, data):
    answers = data.human_answers.get(question.pk, [])
    return h.div[
        h.h2(".h5")[citation.title or tdt("Untitled citation")],
        CitationModalButton(citation, question, data.stage),
        h.p[StageDetailLink(citation, data.stage)],
        h.h2(".h5")[question.name],
        h.p[question.description],
        DefinitionList(
            [
                (tdt("Answer type"), question.get_option_type_display()),
                (
                    tdt("Units and reporting instructions"),
                    question.units_and_reporting_instructions,
                ),
                (
                    tdt("Calculation instructions"),
                    question.calculation_instructions,
                ),
            ]
        ),
        h.h2(".h5")[tdt("AI answer")],
        AIAnswer(data.results.get(question.pk), citation, parameter=True),
        h.h2(".h5")[tdt("Human answers")],
        HumanAnswers(answers, parameter=True),
        h.div(
            id=f"answer-citation-modal-slot-{data.stage}-{citation.pk}-{question.pk}",
            data_modal_slot=True,
        ),
    ]
