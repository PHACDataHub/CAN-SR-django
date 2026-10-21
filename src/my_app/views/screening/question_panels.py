from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Q

import htpy as h

from proj.htpy import definition_list as DefList
from proj.htpy.components import PercentFormatter

from my_app.constants import DEFAULT_CONFIDENCE
from my_app.models import (
    L1HumanAnswer,
    L1ScreeningQuestion,
    L1ScreeningResult,
    L2HumanAnswer,
    L2ScreeningQuestion,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    ScreeningActions,
    ScreeningResultStatus,
)
from my_app.views.pdf_components import EvidenceDefinitionItems
from my_app.views.screening.components import (
    CriticalAgentDefinitionItems,
    SelectedOption,
)
from shortcuts import cached_property, reverse, tdt

STAGE_MODELS = {
    "l1": (L1ScreeningQuestion, L1ScreeningResult, L1HumanAnswer),
    "l2": (L2ScreeningQuestion, L2ScreeningResult, L2HumanAnswer),
    "parameters": (Parameter, ParameterExtractionResult, ParameterHumanAnswer),
}


def question_panel_id(stage, citation_id, question_id):
    return f"{stage}-question-panel-{citation_id}-{question_id}"


class QuestionPanels:
    def __init__(self, citation, review, user, stage):
        self.citation = citation
        self.review = review
        self.user = user
        self.stage = stage
        self.question_model, self.result_model, self.answer_model = (
            STAGE_MODELS[stage]
        )

    @cached_property
    def questions(self):
        answered_question_ids = self.results.keys() | self.answers.keys()
        return list(
            self.question_model.objects.filter(review=self.review)
            .filter(
                Q(deletion_time__isnull=True) | Q(pk__in=answered_question_ids)
            )
            .order_by("pk")
        )

    @cached_property
    def results(self):
        related = ["selected_option"]
        if self.stage != "parameters":
            related += ["critical_result__selected_option"]
        return {
            result.question_id: result
            for result in self.result_model.objects.filter(
                citation=self.citation, question__review=self.review
            ).select_related(*related)
        }

    @cached_property
    def answers(self):
        grouped = defaultdict(list)
        for answer in (
            self.answer_model.objects.filter(
                citation=self.citation, question__review=self.review
            )
            .select_related("selected_option", "user")
            .order_by("-updated_at", "-pk")
        ):
            grouped[answer.question_id].append(answer)
        return grouped

    def panel(self, question):
        return QuestionPanel(
            citation=self.citation,
            question=question,
            review=self.review,
            user=self.user,
            stage=self.stage,
            result=self.results.get(question.pk),
            answers=self.answers.get(question.pk, []),
        )

    def render(self, title):
        return h.section(".border.rounded.p-3")[
            h.div(".row.align-items-center.mb-3")[
                h.h2(".col.h5.mb-0")[title],
                h.div(".col-auto.small.text-muted")[
                    tdt("Questions"), ": ", str(len(self.questions))
                ],
            ],
            (
                h.div(".vstack.gap-3")[
                    [
                        self.panel(question).render()
                        for question in self.questions
                    ]
                ]
                if self.questions
                else h.p(".text-muted.mb-0")[tdt("No questions configured.")]
            ),
        ]


@dataclass
class QuestionPanel:
    citation: object
    question: object
    review: object
    user: object
    stage: str
    result: object = None
    answers: list = field(default_factory=list)

    @property
    def panel_id(self):
        return question_panel_id(
            self.stage, self.citation.pk, self.question.pk
        )

    @property
    def parameter(self):
        return self.stage == "parameters"

    def valid_answer(self, answer):
        if self.question.deletion_time is not None:
            return False
        if self.parameter:
            if not answer.found:
                return True
            option = answer.selected_option
            if option is None:
                return (
                    self.question.option_type == Parameter.OptionType.FREE_TEXT
                )
            return (
                option.parameter_id == self.question.pk
                and option.deletion_time is None
            )
        option = answer.selected_option
        return (
            option is not None
            and option.question_id == self.question.pk
            and option.deletion_time is None
        )

    @property
    def human(self):
        if self.answers and self.valid_answer(self.answers[0]):
            return self.answers[0]
        return None

    @property
    def ai(self):
        if (
            self.result is not None
            and self.result.status == ScreeningResultStatus.COMPLETED
            and self.valid_answer(self.result)
        ):
            return self.result
        return None

    @property
    def selected(self):
        if self.human is not None:
            return self.human
        return self.ai

    @property
    def critical(self):
        return getattr(self.result, "critical_result", None)

    @property
    def critical_disagrees(self):
        return (
            self.critical is not None
            and self.critical.status == ScreeningResultStatus.COMPLETED
            and self.critical.selected_option_id is not None
        )

    def answer_key(self, answer):
        if not self.parameter:
            return answer.selected_option_id
        if not answer.found:
            return (False,)
        if self.question.option_type == Parameter.OptionType.SELECT:
            return (True, answer.selected_option_id)
        return (True, "".join((answer.value or "").lower().split()))

    @property
    def controversial(self):
        keys = {
            self.answer_key(answer)
            for answer in self.answers
            if self.valid_answer(answer)
        }
        if self.ai is not None:
            keys.add(self.answer_key(self.ai))
        return len(keys) > 1

    @property
    def has_errors(self):
        return (
            self.result is not None
            and self.result.status == ScreeningResultStatus.ABANDONED
        ) or (
            self.critical is not None
            and (
                self.critical.status == ScreeningResultStatus.ABANDONED
                or bool(self.critical.error)
            )
        )

    @property
    def confident_ai(self):
        threshold = getattr(self.question, "confidence", None)
        if threshold is None:
            threshold = self.review.confidence
        if threshold is None:
            threshold = DEFAULT_CONFIDENCE
        if (
            self.ai is None
            or self.ai.confidence is None
            or self.ai.confidence < threshold
        ):
            return False
        if self.parameter:
            return True
        return (
            self.critical is not None
            and self.critical.status == ScreeningResultStatus.COMPLETED
            and self.critical.selected_option_id is None
            and self.critical.confidence is not None
            and self.critical.confidence >= threshold
        )

    @property
    def status(self):
        if self.question.deletion_time is not None:
            return tdt("Deleted question")
        if self.controversial:
            return tdt("Controversial")
        if not self.parameter and self.question.disable_screening:
            return tdt("Screening disabled")
        if self.human is not None or self.confident_ai:
            if self.parameter:
                return tdt("Completed")
            if (
                self.selected.selected_option.screening_action
                == ScreeningActions.ScreenOut
            ):
                return tdt("Excluded")
            return tdt("Included")
        if (
            self.result is not None
            and self.result.status == ScreeningResultStatus.COMPLETED
        ):
            return tdt("Needs human review")
        if self.critical_disagrees:
            return tdt("Needs human review")
        if self.has_errors:
            return tdt("Error")
        if (
            self.result is not None
            and self.result.status == ScreeningResultStatus.PENDING
        ):
            return tdt("Pending")
        return tdt("Unanswered")

    @property
    def answer_url(self):
        args = [self.review.pk, self.citation.pk, self.question.pk]
        if self.stage == "l1":
            return reverse("l1_question_human_answer", args=args)
        if self.stage == "l2":
            return reverse("l2_question_human_answer", args=args)
        return reverse("parameter_question_human_answer", args=args)

    @property
    def detail_url(self):
        args = [self.citation.pk, self.question.pk]
        if self.stage == "l1":
            return reverse("l1_answer_detail_modal", args=args)
        if self.stage == "l2":
            return reverse("l2_answer_detail_modal", args=args)
        return reverse("parameter_answer_detail_modal", args=args)

    def modal_button(self, label, url, **attrs):
        return h.button(
            ".btn.btn-outline-primary.btn-sm",
            type="button",
            hx_get=url,
            hx_target="#modal-slot",
            hx_swap="innerHTML",
            **attrs,
        )[label]

    def render_answer(self):
        if self.selected is None:
            return h.span(".text-muted")[tdt("No answer yet")]
        source = tdt("AI")
        if self.human is not None:
            source = tdt("Human")
        value = (
            SelectedOption(
                self.selected.selected_option,
                screening_disabled=self.question.disable_screening,
            )
            if not self.parameter
            else ParameterAnswerValue(self.selected)
        )
        return h.div[
            h.span(".badge.text-bg-secondary.mb-1")[source],
            value,
        ]

    def render_controls(self):
        if self.question.deletion_time is not None:
            return None
        current = next(
            (
                answer
                for answer in self.answers
                if answer.user_id == self.user.pk
            ),
            None,
        )
        label = tdt("Add your answer")
        if current is not None:
            label = tdt("Edit your answer")
        validate = None
        if self.ai is not None and not self.answers:
            args = [self.review.pk, self.result.pk]
            if self.stage == "l1":
                url = reverse("l1_citation_validate_correct", args=args)
            elif self.stage == "l2":
                url = reverse("l2_citation_validate_correct", args=args)
            else:
                url = reverse(
                    "parameter_extraction_citation_validate_ai_answer",
                    args=args,
                )
            validate = h.button(
                ".btn.btn-outline-success.btn-sm",
                id=f"{self.stage}-validate-answer-{self.result.pk}",
                type="button",
                hx_post=url,
                hx_target=f"#{self.panel_id}",
                hx_swap="morph:outerHTML",
            )[tdt("Validate AI answer")]
        return h.div(".row.g-2.mt-1")[
            h.div(".col-auto")[self.modal_button(label, self.answer_url)],
            h.div(".col-auto")[validate] if validate else None,
        ]

    def historical_answer_items(self):
        answers = []
        if self.result is not None:
            answers.append((tdt("Historical AI answer"), self.result))
        answers += [
            (
                h.span[
                    tdt("Historical human answer"),
                    " — ",
                    (
                        answer.user.get_username()
                        if answer.user
                        else tdt("Unknown user")
                    ),
                ],
                answer,
            )
            for answer in self.answers
        ]
        return [
            (label, self.render_historical_answer(answer))
            for label, answer in answers
            if self.question.deletion_time is not None
            or (
                answer.selected_option is not None
                and answer.selected_option.deletion_time is not None
            )
        ]

    def render_historical_answer(self, answer):
        if self.parameter:
            value = ParameterAnswerValue(answer)
        else:
            value = SelectedOption(
                answer.selected_option,
                screening_disabled=self.question.disable_screening,
            )
        return h.div[
            h.span(".badge.text-bg-secondary.mb-1")[tdt("Historical answer")],
            (
                h.div(".small.text-muted")[tdt("Deleted option")]
                if answer.selected_option is not None
                and answer.selected_option.deletion_time is not None
                else None
            ),
            value,
        ]

    def render_more(self):
        items = [(tdt("Confidence"), tdt("Not recorded"))]
        if self.result is not None:
            confidence = tdt("Not recorded")
            if self.result.confidence is not None:
                confidence = PercentFormatter(self.result.confidence)
            items = [
                (tdt("Confidence"), confidence),
                (tdt("AI status"), self.result.get_status_display()),
            ]
            if self.result.explanation:
                items.append((tdt("AI explanation"), self.result.explanation))
            if not self.parameter:
                items += CriticalAgentDefinitionItems(self.result)
            if self.critical is not None and self.critical.error:
                items.append(
                    (tdt("Critical agent error"), self.critical.error)
                )
            if hasattr(self.result, "evidence_sentences"):
                evidence_items = EvidenceDefinitionItems(
                    self.result,
                    getattr(
                        self.citation.document, "text_extraction_result", None
                    ),
                )
                items += [
                    item
                    for field_name, item in zip(
                        (
                            "evidence_sentences",
                            "evidence_tables",
                            "evidence_figures",
                        ),
                        evidence_items,
                    )
                    if getattr(self.result, field_name)
                ]
        if self.human is not None and self.human.notes:
            items.append((tdt("Human notes"), self.human.notes))
        items += self.historical_answer_items()
        items.append(
            (
                tdt("See more details"),
                self.modal_button(tdt("Answer details"), self.detail_url),
            )
        )
        expansion_reasons = []
        if self.controversial:
            expansion_reasons.append("controversial")
        if self.critical_disagrees:
            expansion_reasons.append("critical-disagreement")
        if self.has_errors:
            expansion_reasons.append("error")
        return h.details(
            open=bool(expansion_reasons),
            data_auto_expand=" ".join(expansion_reasons),
        )[
            h.summary[tdt("More information")],
            DefList.DL(items),
        ]

    def render(self):
        return h.section(
            ".question-panel",
            id=self.panel_id,
            data_question_id=str(self.question.pk),
            data_stage=self.stage,
        )[
            DefList.DL(
                [
                    (tdt("Question"), self.question.title),
                    (tdt("Status"), self.status),
                    (tdt("Answer"), self.render_answer()),
                ]
            ),
            self.render_controls(),
            self.render_more(),
        ]


def ParameterAnswerValue(answer):
    if not answer.found:
        return h.span[tdt("Not found")]
    if answer.selected_option is not None:
        return h.span[answer.selected_option.name]
    return h.span[answer.value or tdt("No value recorded")]
