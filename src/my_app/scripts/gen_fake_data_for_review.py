"""Synthetic answers: runscript ... --script-args REVIEW_ID l1|l2|parameter|reset.

Each run adds criteria and updates AI results for every active criterion and
citation in the review. Human answers are appended as answer history. For an
erroneous base result, subsequent answers use its simulated intended option.
Parameters use found/absent in place of screen-in/out and have no critic model.
Reset permanently deletes all criteria and their answers for the review.
"""

import random
from datetime import timedelta

from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from django.utils.functional import cached_property

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from proj.text import tdt

from my_app.models import (
    Citation,
    L1CriticalScreeningResult,
    L1HumanAnswer,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L1ScreeningResult,
    L2CriticalScreeningResult,
    L2HumanAnswer,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
    ParameterHumanAnswer,
    ParameterOption,
    Review,
    ScreeningActions,
    ScreeningResultStatus,
)

CRITERIA = (
    "Does the study include the population of interest?",
    "Does the study evaluate the intervention of interest?",
    "Does the study report a relevant health outcome?",
    "Does the study use an eligible study design?",
    "Does the study include an appropriate comparison group?",
    "Was the study conducted in an eligible setting?",
    "Does the study meet the publication date criteria?",
    "Does the study report sufficient follow-up?",
)
PARAMETERS = (
    "Study design",
    "Population age group",
    "Intervention type",
    "Outcome category",
    "Study setting",
    "Follow-up duration category",
    "Sample size category",
    "Geographic region",
)


def human_answer_count():
    roll = random.random()
    if roll < 0.55:
        return 1
    if roll < 0.60:
        return 2
    return 0


class FakeStageData:
    def __init__(self, review):
        self.review = review

    @cached_property
    def users(self):
        return list(self.review.users.order_by("pk"))

    def advance_time(self):
        self.clock.tick(delta=timedelta(seconds=random.randint(30, 300)))

    def generate(self, clock):
        self.clock = clock
        self.generate_questions()
        questions = list(
            self.question_model.active_objects.filter(
                review=self.review
            ).prefetch_related(
                Prefetch(
                    "options", queryset=self.option_model.active_objects.all()
                )
            )
        )
        for question in questions:
            options = list(question.options.all())
            self.validate_options(question, options)
        citations = Citation.objects.filter(
            dataset__review=self.review
        ).order_by("order", "pk")
        citation_count = citations.count()
        for index, citation in enumerate(citations.iterator()):
            generate_answers = self.answer_generator(index, citation_count)
            for question in questions:
                generate_answers(
                    citation, question, list(question.options.all())
                )
        return len(questions)

    def answer_generator(self, index, citation_count):
        return self.generate_answers

    def validate_options(self, question, options):
        pass

    def human_user(self, index):
        if self.users:
            return self.users[index % len(self.users)]
        return None

    def result_defaults(self, erroneous):
        defaults = {
            "language_model": self.review.language_model,
            "status": ScreeningResultStatus.COMPLETED,
            "confidence": random.uniform(0.8, 1.0),
            "abandoned_at": None,
            "explanation": tdt("Synthetic AI answer for demonstration."),
        }
        if erroneous:
            defaults.update(
                status=ScreeningResultStatus.ABANDONED,
                confidence=None,
                abandoned_at=timezone.now(),
                explanation=tdt("Synthetic error: invalid AI response."),
            )
        return defaults


class FakeScreeningData(FakeStageData):
    def answer_generator(self, index, citation_count):
        if index < citation_count * 3 // 10:
            return self.generate_included_answers
        return self.generate_answers

    def generate_questions(self):
        for text in random.sample(
            CRITERIA, random.randint(*self.question_count_range)
        ):
            question = self.question_model.objects.create(
                review=self.review, question_text=tdt(text)
            )
            self.sync_question(question)
            actions = [ScreeningActions.ScreenIn, ScreeningActions.ScreenOut]
            actions.extend(
                random.choice(ScreeningActions.values)
                for _ in range(random.randint(2, 5) - 2)
            )
            for number, action in enumerate(actions, start=1):
                label = tdt("Eligible")
                if action == ScreeningActions.ScreenOut:
                    label = tdt("Ineligible")
                option = self.option_model.objects.create(
                    question=question,
                    option_text=f"{label} {number}",
                    option_value=tdt("Synthetic criterion response."),
                    screening_action=action,
                )
                self.sync_option(option)
            self.advance_time()

    def sync_question(self, question):
        pass

    def sync_option(self, option):
        pass

    def validate_options(self, question, options):
        actions = {option.screening_action for option in options}
        if not set(ScreeningActions.values).issubset(actions):
            raise CommandError(
                f"Question {question.pk} needs active screen-in and screen-out options."
            )

    def generate_included_answers(self, citation, question, options):
        selected_option = self.included_option(citation, question, options)
        defaults = self.result_defaults(erroneous=False)
        defaults.update(
            selected_option=selected_option,
            confidence=random.uniform(0.9, 0.99),
        )
        result, _ = self.result_model.objects.update_or_create(
            citation=citation, question=question, defaults=defaults
        )
        self.advance_time()
        self.critical_model.objects.update_or_create(
            initial_result=result,
            defaults={
                "language_model": self.review.language_model,
                "status": ScreeningResultStatus.COMPLETED,
                "confidence": random.uniform(0.9, 0.99),
                "selected_option": None,
                "error": "",
                "abandoned_at": None,
            },
        )
        self.advance_time()

    def included_option(self, citation, question, options):
        return random.choice(
            [
                option
                for option in options
                if option.screening_action == ScreeningActions.ScreenIn
            ]
        )

    def base_answer(self, citation, question, options):
        roll = random.random()
        action = ScreeningActions.ScreenIn
        if 0.95 <= roll < 0.98:
            action = ScreeningActions.ScreenOut
        intended_option = random.choice(
            [option for option in options if option.screening_action == action]
        )
        return intended_option, roll >= 0.98

    def generate_answers(self, citation, question, options):
        intended_option, erroneous = self.base_answer(
            citation, question, options
        )
        alternatives = [
            option
            for option in options
            if option.screening_action != intended_option.screening_action
        ]
        defaults = self.result_defaults(erroneous=erroneous)
        defaults["selected_option"] = intended_option
        if erroneous:
            defaults["selected_option"] = None
        result, _ = self.result_model.objects.update_or_create(
            citation=citation, question=question, defaults=defaults
        )
        self.advance_time()
        self.generate_critical_answer(result, alternatives)
        self.advance_time()
        for index in range(human_answer_count()):
            selected_option = intended_option
            if random.random() >= 0.80:
                selected_option = random.choice(alternatives)
            self.human_model.objects.create(
                citation=citation,
                question=question,
                user=self.human_user(index),
                selected_option=selected_option,
                notes=tdt("Synthetic human answer for demonstration."),
            )
            self.advance_time()

    def generate_critical_answer(self, result, alternatives):
        roll = random.random()
        defaults = {
            "language_model": self.review.language_model,
            "status": ScreeningResultStatus.COMPLETED,
            "confidence": random.uniform(0.8, 1.0),
            "selected_option": None,
            "error": "",
            "abandoned_at": None,
        }
        if 0.95 <= roll < 0.98:
            defaults["selected_option"] = random.choice(alternatives)
        elif roll >= 0.98:
            defaults.update(
                status=ScreeningResultStatus.ABANDONED,
                confidence=None,
                abandoned_at=timezone.now(),
                error=tdt("Synthetic error: invalid critical-agent response."),
            )
        self.critical_model.objects.update_or_create(
            initial_result=result, defaults=defaults
        )


class FakeL1Data(FakeScreeningData):
    question_count_range = (4, 6)
    question_model = L1ScreeningQuestion
    option_model = L1ScreeningQuestionOption
    result_model = L1ScreeningResult
    critical_model = L1CriticalScreeningResult
    human_model = L1HumanAnswer

    def sync_question(self, question):
        question.sync_to_l2()

    def sync_option(self, option):
        option.sync_to_l2()


class FakeL2Data(FakeScreeningData):
    question_count_range = (2, 5)
    question_model = L2ScreeningQuestion
    option_model = L2ScreeningQuestionOption
    result_model = L2ScreeningResult
    critical_model = L2CriticalScreeningResult
    human_model = L2HumanAnswer

    @cached_property
    def l1_answers(self):
        return {
            (citation_id, question_id): option_id
            for citation_id, question_id, option_id in L1ScreeningResult.objects.filter(
                question__review=self.review,
                status=ScreeningResultStatus.COMPLETED,
                selected_option__deletion_time__isnull=True,
            ).values_list(
                "citation_id", "question_id", "selected_option_id"
            )
        }

    def mirrored_option(self, citation, question, options):
        if question.l1_question_id is None:
            return None
        option_id = self.l1_answers.get((citation.pk, question.l1_question_id))
        if option_id is None:
            return None
        return next(
            (option for option in options if option.l1_option_id == option_id),
            None,
        )

    def included_option(self, citation, question, options):
        option = self.mirrored_option(citation, question, options)
        if (
            option is not None
            and option.screening_action == ScreeningActions.ScreenIn
        ):
            return option
        return super().included_option(citation, question, options)

    def base_answer(self, citation, question, options):
        option = self.mirrored_option(citation, question, options)
        if option is None:
            return super().base_answer(citation, question, options)
        if random.random() < 0.99:
            return option, False
        return (
            random.choice(
                [other for other in options if other.pk != option.pk]
            ),
            False,
        )


class FakeParameterData(FakeStageData):
    question_model = Parameter
    option_model = ParameterOption

    def generate_questions(self):
        for name in random.sample(PARAMETERS, random.randint(4, 8)):
            parameter = Parameter.objects.create(
                review=self.review,
                name=tdt(name),
                description=tdt(
                    "Extract the reported category from the study."
                ),
                option_type=Parameter.OptionType.SELECT,
            )
            for number in range(1, random.randint(2, 5) + 1):
                ParameterOption.objects.create(
                    parameter=parameter,
                    name=f"{tdt('Category')} {number}",
                    context=tdt("Synthetic parameter category."),
                )
            self.advance_time()

    def validate_options(self, question, options):
        if question.option_type == Parameter.OptionType.SELECT and not options:
            raise CommandError(
                f"Parameter {question.pk} needs active options."
            )

    def answer(self, question, options, found):
        answer = {"found": found, "selected_option": None, "value": None}
        if found:
            answer["value"] = tdt("Synthetic extracted value")
            if question.option_type == Parameter.OptionType.SELECT:
                answer["selected_option"] = random.choice(options)
                answer["value"] = answer["selected_option"].name
        return answer

    def generate_answers(self, citation, question, options):
        roll = random.random()
        intended_answer = self.answer(question, options, found=roll < 0.90)
        defaults = self.result_defaults(erroneous=roll >= 0.98)
        defaults.update(intended_answer)
        ParameterExtractionResult.objects.update_or_create(
            citation=citation, question=question, defaults=defaults
        )
        self.advance_time()
        for index in range(human_answer_count()):
            answer = intended_answer
            if random.random() >= 0.80:
                answer = self.answer(
                    question, options, found=not intended_answer["found"]
                )
            ParameterHumanAnswer.objects.create(
                citation=citation,
                question=question,
                user=self.human_user(index),
                notes=tdt("Synthetic human answer for demonstration."),
                **answer,
            )
            self.advance_time()


@transaction.atomic
def run(*args):
    if len(args) != 2:
        raise CommandError(
            "Expected two arguments: REVIEW_ID l1|l2|parameter|reset"
        )
    review_id, stage = args
    generators = {
        "l1": FakeL1Data,
        "l2": FakeL2Data,
        "parameter": FakeParameterData,
    }
    stage = stage.lower()
    if stage == "param":
        stage = "parameter"
    if stage not in generators and stage != "reset":
        raise CommandError("Stage must be l1, l2, parameter, or reset.")
    try:
        review = Review.objects.get(pk=int(review_id))
    except (ValueError, TypeError, Review.DoesNotExist) as exc:
        raise CommandError(f"Review {review_id!r} does not exist.") from exc
    if stage == "reset":
        review.l1_screening_questions.all().delete()
        review.l2_screening_questions.all().delete()
        review.parameters.all().delete()
        print(f"Deleted all criteria and answers for review {review.pk}.")
        return
    with freeze_time(timezone.now() - relativedelta(months=1)) as clock:
        count = generators[stage](review).generate(clock)
    print(
        f"Generated {stage} fake data for review {review.pk} ({count} criteria)."
    )
