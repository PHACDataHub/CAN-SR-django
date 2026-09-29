import json
import random
from functools import cache

from django.conf import settings

import pydantic

from proj.llm_client import (
    LLMResponseSchema,
    UnexpectedLLMOutputError,
    get_client,
)

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    LanguageModel,
)
from shortcuts import List, dataclass, logger

from .prompt_renderer import render_prompt
from .prompt_util import build_option_definition_string, build_option_string
from .screening_response import (
    NONE_OF_THE_ABOVE,
    response_option_strings,
    result_model_without_fields,
    screening_options,
)


class L1ScreeningPromptBuilder:
    def __init__(
        self,
        question: L1ScreeningQuestion,
        options: List[L1ScreeningQuestionOption],
        citation: Citation,
        answer_to_critique: L1ScreeningQuestionOption | None = None,
    ):
        self.question = question
        self.answer_to_critique = answer_to_critique
        self.options = screening_options(options, answer_to_critique)
        self.citation = citation

    @dataclass
    class ScreeningPromptArgs:
        question: str
        citation: str
        options: str
        definitions: str

    def get_screening_prompt_args(
        self,
    ) -> ScreeningPromptArgs:
        columns_to_include = self.citation.dataset.screening_columns.all()
        citation_text = self.citation.serialize_for_prompt(columns_to_include)

        option_info_string = build_option_definition_string(self.options)
        option_string = build_option_string(self.options)
        if self.answer_to_critique is not None:
            option_string += f"\n'{NONE_OF_THE_ABOVE}'"

        return self.ScreeningPromptArgs(
            question=self.question.question_text,
            citation=citation_text,
            options=option_string,
            definitions=option_info_string,
        )

    def build_str(self):
        prompt_args = self.get_screening_prompt_args()
        answer_to_critique = ""
        if self.answer_to_critique is not None:
            answer_to_critique = self.answer_to_critique.option_text
        return render_prompt(
            "l1_screening_prompt.hbs",
            {
                "question": prompt_args.question,
                "citation": prompt_args.citation,
                "options": prompt_args.options,
                "definitions": prompt_args.definitions,
                "is_critical": self.answer_to_critique is not None,
                "answer_to_critique": answer_to_critique,
            },
        )


class RawL1ScreeningPromptResult(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    # Removed for critical reviews, which only return selected and confidence.
    explanation: str
    confidence: pydantic.confloat(ge=0.0, le=1.0)
    selected: str


@cache
def build_raw_l1_result_model(
    is_critical: bool = False,
) -> type[pydantic.BaseModel]:
    excluded = set()
    if is_critical:
        excluded.add("explanation")
    return result_model_without_fields(RawL1ScreeningPromptResult, excluded)


def build_l1_response_schema(
    options: List[L1ScreeningQuestionOption],
    answer_to_critique: L1ScreeningQuestionOption | None = None,
) -> LLMResponseSchema:
    # expected enums are run-time determined because they come from the user
    schema = build_raw_l1_result_model(
        answer_to_critique is not None
    ).model_json_schema()
    schema["properties"]["selected"]["enum"] = response_option_strings(
        options, answer_to_critique
    )
    schema["properties"]["confidence"].pop("minimum")
    schema["properties"]["confidence"].pop("maximum")
    return LLMResponseSchema(name="l1_screening_result", schema=schema)


class L1ScreeningPromptResult(RawL1ScreeningPromptResult):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    selected: L1ScreeningQuestionOption | None
    explanation: str | None = None


def get_l1_screening_results(
    question: L1ScreeningQuestion,
    options: List[L1ScreeningQuestionOption],
    citation: Citation,
    model: LanguageModel,
    answer_to_critique: L1ScreeningQuestionOption | None = None,
):
    if not settings.HAS_LLM:
        logger.warning(
            "LLM is not available, using mock results for L1 screening"
        )
        return get_mock_l1_screening_results(
            question, options, citation, answer_to_critique=answer_to_critique
        )

    options = screening_options(options, answer_to_critique)
    logger.info("LLM is available, using real LLM results for L1 screening")
    prompt_builder = L1ScreeningPromptBuilder(
        question, options, citation, answer_to_critique
    )
    prompt = prompt_builder.build_str()

    llm_client = get_client()
    raw_answer = llm_client.complete_prompt(
        prompt,
        model,
        response_schema=build_l1_response_schema(options, answer_to_critique),
    )

    try:
        json_answer = json.loads(raw_answer)
        answer = build_raw_l1_result_model(
            answer_to_critique is not None
        ).model_validate(json_answer)
    except json.JSONDecodeError as exc:
        raise UnexpectedLLMOutputError(
            f"LLM returned invalid JSON: {raw_answer}"
        ) from exc
    except pydantic.ValidationError as exc:
        raise UnexpectedLLMOutputError(
            f"LLM returned JSON that doesn't match expected schema: {json_answer}"
        ) from exc

    selected_option = next(
        (opt for opt in options if opt.option_text == answer.selected),
        None,
    )
    agrees = (
        answer_to_critique is not None and answer.selected == NONE_OF_THE_ABOVE
    )
    if agrees:
        selected_option = None
    if selected_option is None and not agrees:
        raise UnexpectedLLMOutputError(
            f"LLM returned option doesn't match available options for question {question.id}"
        )

    try:
        typed_result = L1ScreeningPromptResult(
            selected=selected_option,
            explanation=getattr(answer, "explanation", None),
            confidence=answer.confidence,
        )
    except pydantic.ValidationError as exc:
        raise UnexpectedLLMOutputError() from exc

    return typed_result


def get_mock_l1_screening_results(
    question: L1ScreeningQuestion,
    options: List[L1ScreeningQuestionOption],
    citation: Citation,
    answer_to_critique: L1ScreeningQuestionOption | None = None,
):
    options = screening_options(options, answer_to_critique)
    if answer_to_critique is not None:
        return L1ScreeningPromptResult(
            selected=random.choice([*options, None]), confidence=0.5
        )

    selected_option = random.choice(options)
    confidence = random.uniform(0.5, 1.0)
    explanation = "This is a mock explanation for why the option was selected."

    return L1ScreeningPromptResult(
        selected=selected_option,
        explanation=explanation,
        confidence=confidence,
    )
