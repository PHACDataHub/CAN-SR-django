from django.core.exceptions import ValidationError
from django.db import transaction

import yaml

from proj.text import tdt

from my_app.models import (
    CitationDataset,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    Parameter,
    Review,
    ScreeningActions,
)


def require_mapping(value, path):
    if not isinstance(value, dict):
        raise ValidationError(
            tdt("{path} must be a mapping.").format(path=path)
        )
    return value


def require_list(value, path):
    if not isinstance(value, list):
        raise ValidationError(tdt("{path} must be a list.").format(path=path))
    return value


def require_text(value, path, max_length=None):
    if not isinstance(value, str):
        raise ValidationError(tdt("{path} must be text.").format(path=path))
    if max_length is not None and len(value) > max_length:
        raise ValidationError(
            tdt("{path} must be at most {limit} characters.").format(
                path=path, limit=max_length
            )
        )
    return value


class CreateCriteriaFromYaml:
    def __init__(self, review, yaml_string):
        self.review = review
        self.yaml_string = yaml_string

    @transaction.atomic
    def run(self):
        Review.objects.select_for_update().get(pk=self.review.pk)
        try:
            data = yaml.safe_load(self.yaml_string)
        except yaml.YAMLError as error:
            raise ValidationError(
                tdt("Invalid YAML: {error}").format(error=error)
            ) from error
        data = require_mapping(data, tdt("YAML document"))
        for key in ("l1", "l2", "parameters"):
            require_list(data.get(key), key)

        self.replace_screening_columns(data)
        for model in (L1ScreeningQuestion, L2ScreeningQuestion, Parameter):
            model.objects.filter(review=self.review).delete()

        self.create_questions(
            data["l1"], L1ScreeningQuestion, L1ScreeningQuestionOption, "l1"
        )
        self.create_questions(
            data["l2"], L2ScreeningQuestion, L2ScreeningQuestionOption, "l2"
        )
        self.create_parameters(data["parameters"])

    def replace_screening_columns(self, data):
        citation_fields = require_mapping(
            data.get("citation_fields", {}), "citation_fields"
        )
        names = require_list(
            citation_fields.get("l1_include", []), "citation_fields.l1_include"
        )
        for name in names:
            require_text(name, "citation_fields.l1_include")
        normalized_names = {name.casefold() for name in names}
        dataset = CitationDataset.objects.filter(review=self.review).first()
        columns = []
        if dataset is not None:
            columns = [
                column
                for column in dataset.columns.all()
                if column.name.casefold() in normalized_names
            ]
        matched_names = {column.name.casefold() for column in columns}
        missing = {
            name for name in names if name.casefold() not in matched_names
        }
        if missing:
            raise ValidationError(
                tdt(
                    "Screening columns not found in this review: {columns}"
                ).format(columns=", ".join(sorted(missing)))
            )
        if dataset is not None:
            dataset.screening_columns.set(columns)

    def create_questions(self, entries, question_model, option_model, level):
        actions = {
            "include": ScreeningActions.ScreenIn,
            "exclude": ScreeningActions.ScreenOut,
        }
        for index, entry in enumerate(entries):
            path = f"{level}[{index}]"
            entry = require_mapping(entry, path)
            question = question_model.objects.create(
                review=self.review,
                question_text=require_text(
                    entry.get("question"), f"{path}.question"
                ),
            )
            options = []
            for option_index, answer in enumerate(
                require_list(entry.get("answers"), f"{path}.answers")
            ):
                answer_path = f"{path}.answers[{option_index}]"
                answer = require_mapping(answer, answer_path)
                decision = require_text(
                    answer.get("decision"), f"{answer_path}.decision"
                )
                if decision not in actions:
                    raise ValidationError(
                        tdt(
                            "{path}.decision must be include or exclude."
                        ).format(path=answer_path)
                    )
                options.append(
                    option_model.objects.create(
                        question=question,
                        option_text=require_text(
                            answer.get("label"),
                            f"{answer_path}.label",
                            max_length=255,
                        ),
                        option_value=require_text(
                            answer.get("context"), f"{answer_path}.context"
                        ),
                        screening_action=actions[decision],
                    )
                )
            if question_model is L1ScreeningQuestion:
                question.sync_to_l2()
                for option in options:
                    option.sync_to_l2()

    def create_parameters(self, entries):
        for index, entry in enumerate(entries):
            path = f"parameters[{index}]"
            entry = require_mapping(entry, path)
            if entry.get("type") != "text":
                raise ValidationError(
                    tdt("TODO: support more than text in yaml uploads")
                )
            Parameter.objects.create(
                review=self.review,
                name=require_text(
                    entry.get("name"), f"{path}.name", max_length=255
                ),
                description=require_text(
                    entry.get("description"), f"{path}.description"
                ),
                option_type=Parameter.OptionType.FREE_TEXT,
                units_and_reporting_instructions=require_text(
                    entry.get("unit_instructions", ""),
                    f"{path}.unit_instructions",
                ),
                calculation_instructions=require_text(
                    entry.get("calculation", ""), f"{path}.calculation"
                ),
            )
