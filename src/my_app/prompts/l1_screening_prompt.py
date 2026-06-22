import json
import random

from django.conf import settings

import pydantic

from proj.llm_client import UnexpectedLLMOutputError, get_client

from my_app.models import (
    Citation,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    LanguageModel,
)
from shortcuts import List, dataclass, logger

from .prompt_util import build_option_definition_string, build_option_string

PROMPT_JSON_TEMPLATE = """
You are a highly critical, helpful scientific evaluator completing an academic review. Your job is to screen a citation and decide whether to 
include or exclude it according to a single question and a fixed set of options.

Answer the question "{question}" for the following citation:

{citation}

The available options (exact text) are:
{options}

Additional guidance to consider:
{definitions}

Output requirement:
Respond with a JSON object containing these keys:
- "selected": the exact option string you selected (must match one of the options above; if none fits, pick the closest option and report a low confidence score)
- "explanation": a concise explanation (1-4 sentences) of why you selected that option
- "confidence": a floating number between 0 and 1 (inclusive) representing your estimated confidence for the selected option

JSON object format:
{{
  "selected": "Include", 
  "explanation": "The study meets the inclusion criteria because ...", 
  "confidence": 0.72
}}

Keep the response strictly as a JSON object that matches the schema above. Do not wrap the response in Markdown code fences or add language tags (e.g., ```json). Return only raw JSON starting with {{ and ending with }}.
"""


class L1ScreeningPromptBuilder:
    def __init__(
        self,
        question: L1ScreeningQuestion,
        options: List[L1ScreeningQuestionOption],
        citation: Citation,
    ):
        self.question = question
        self.options = options
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

        return self.ScreeningPromptArgs(
            question=self.question.question_text,
            citation=citation_text,
            options=option_string,
            definitions=option_info_string,
        )

    def build_str(self):
        prompt_args = self.get_screening_prompt_args()
        return PROMPT_JSON_TEMPLATE.format(
            question=prompt_args.question,
            citation=prompt_args.citation,
            options=prompt_args.options,
            definitions=prompt_args.definitions,
        )


class RawL1ScreeningPromptResult(pydantic.BaseModel):
    explanation: str
    confidence: pydantic.confloat(ge=0.0, le=1.0)
    selected: str


class L1ScreeningPromptResult(RawL1ScreeningPromptResult):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    selected: L1ScreeningQuestionOption


def get_l1_screening_results(
    question: L1ScreeningQuestion,
    options: List[L1ScreeningQuestionOption],
    citation: Citation,
    model: LanguageModel,
):
    if not settings.HAS_LLM:
        logger.warning(
            "LLM is not available, using mock results for L1 screening"
        )
        return get_mock_l1_screening_results(question, options, citation)

    logger.info("LLM is available, using real LLM results for L1 screening")
    prompt_builder = L1ScreeningPromptBuilder(question, options, citation)
    prompt = prompt_builder.build_str()

    llm_client = get_client()
    raw_answer = llm_client.complete_prompt(prompt, model)

    try:
        json_answer = json.loads(raw_answer)
        answer = RawL1ScreeningPromptResult(**json_answer)
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
    if selected_option is None:
        raise UnexpectedLLMOutputError(
            f"LLM returned option doesn't match available options for question {question.id}"
        )

    try:
        typed_result = L1ScreeningPromptResult(
            selected=selected_option,
            explanation=answer.explanation,
            confidence=answer.confidence,
        )
    except pydantic.ValidationError as exc:
        raise UnexpectedLLMOutputError() from exc

    return typed_result


def get_mock_l1_screening_results(
    question: L1ScreeningQuestion,
    options: List[L1ScreeningQuestionOption],
    citation: Citation,
):

    selected_option = random.choice(options)
    confidence = random.uniform(0.5, 1.0)
    explanation = "This is a mock explanation for why the option was selected."

    return L1ScreeningPromptResult(
        selected=selected_option,
        explanation=explanation,
        confidence=confidence,
    )
