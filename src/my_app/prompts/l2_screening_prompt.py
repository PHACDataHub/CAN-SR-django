import json
import math
import random
import re

from django.conf import settings

import pydantic

from proj.llm_client import UnexpectedLLMOutputError, get_client

from my_app.models import (
    Citation,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    TextExtractionResult,
)
from my_app.queries import options_for_question
from shortcuts import List, dataclass, logger

from .prompt_util import build_option_definition_string, build_option_string

PROMPT_JSON_TEMPLATE = """
You are assisting with a scientific full-text screening task. Evaluate the question "{question}" against the paper content provided as numbered sentences (e.g., "[0] ...", "[1] ...").

Context:
- Options (choose exactly one of these strings):
{options}

- Additional guidance:
{definitions}

- Full text (numbered sentences):
{fulltext}

- Tables (numbered):
{tables}

- Figures (numbered; captions correspond to images provided alongside this message):
{figures}

Respond with a JSON object containing these keys:
- "selected": the exact option string you selected (must match one of the options above; if none fits, pick the closest option and report a low confidence score)
- "explanation": a concise explanation (1-4 sentences) of why you selected that option
- "confidence": a floating number between 0 and 1 (inclusive) representing your estimated confidence for the selected option
- "evidence_sentences": an array of integers indicating the sentence indices you used as evidence (e.g. [2, 5]). If there is low confidence, return an empty array [].
- "evidence_tables": an array of integers indicating the table numbers you used (e.g. [1, 3]) or [] if none.
- "evidence_figures": an array of integers indicating the figure numbers you used (e.g. [2]) or [] if none.
- If a table or figure is referenced, ensure the explanation references the table/figure number and what was extracted from it.

JSON object format:
{{
  "selected": "<one of the provided options>",
  "explanation": "<1-4 sentences explaining the choice>",
  "confidence": <float 0..1>,
  "evidence_sentences": [<indices of sentences used as evidence>],
  "evidence_tables": [<table numbers used>],
  "evidence_figures": [<figure numbers used>]
}}

Notes:
- Keep the response strictly as a JSON object that matches the schema above.
- Do not wrap the response in Markdown code fences or add language tags (e.g., ```json). Return only raw JSON.
- Use sentence indices from the numbered full text for "evidence_sentences"
- Use table numbers from the Tables section for "evidence_tables"
- Use figure numbers from the Figures section for "evidence_figures"
"""


class L2ScreeningPromptBuilder:
    def __init__(
        self,
        question: L2ScreeningQuestion,
        options: List[L2ScreeningQuestionOption],
        citation: Citation,
        text_extraction_result: TextExtractionResult,
    ):
        self.question = question
        self.options = options
        self.citation = citation
        self.text_extraction_result = text_extraction_result

    @dataclass
    class ScreeningPromptArgs:
        question: str
        options: str
        definitions: str
        fulltext: str
        tables: str
        figures: str

    def get_screening_prompt_args(
        self,
    ) -> ScreeningPromptArgs:
        sentences = self.text_extraction_result.get_sentences()

        option_info_string = build_option_definition_string(self.options)
        option_string = build_option_string(self.options)

        return self.ScreeningPromptArgs(
            question=self.question.question_text,
            options=option_string,
            definitions=option_info_string,
            fulltext=sentences,
            tables="(none)",
            figures="(none)",
        )

    def build_str(self):
        prompt_args = self.get_screening_prompt_args()
        return PROMPT_JSON_TEMPLATE.format(
            question=prompt_args.question,
            options=prompt_args.options,
            definitions=prompt_args.definitions,
            fulltext=prompt_args.fulltext,
            tables=prompt_args.tables,
            figures=prompt_args.figures,
        )


class RawL2ScreeningPromptResult(pydantic.BaseModel):
    selected: str
    explanation: str
    confidence: pydantic.confloat(ge=0.0, le=1.0)
    evidence_sentences: List[int]
    evidence_tables: List[int]
    evidence_figures: List[int]


class L2ScreeningPromptResult(RawL2ScreeningPromptResult):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    selected: L2ScreeningQuestionOption


def get_l2_screening_results(
    question: L2ScreeningQuestion,
    options: List[L2ScreeningQuestionOption],
    citation: Citation,
    text_extraction_result: TextExtractionResult,
) -> L2ScreeningPromptResult:
    if not settings.HAS_LLM:
        logger.warning("LLM is not available, using mock results.")
        return get_mock_l2_screening_results(
            question, options, citation, text_extraction_result
        )

    logger.info("LLM is available, using real LLM results for L2 screening")
    prompt_builder = L2ScreeningPromptBuilder(
        question, options, citation, text_extraction_result
    )
    prompt = prompt_builder.build_str()

    llm_client = get_client()
    raw_response = llm_client.complete_prompt(prompt)

    try:
        response_dict = json.loads(raw_response)
        answer = RawL2ScreeningPromptResult(**response_dict)

    except json.JSONDecodeError as exc:
        raise UnexpectedLLMOutputError(
            f"LLM returned invalid JSON: {raw_response}"
        ) from exc
    except pydantic.ValidationError as exc:
        raise UnexpectedLLMOutputError(
            f"LLM returned JSON that doesn't match expected schema: {response_dict}"
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
        typed_result = L2ScreeningPromptResult(
            selected=selected_option,
            explanation=answer.explanation,
            confidence=answer.confidence,
            evidence_sentences=answer.evidence_sentences,
            evidence_tables=answer.evidence_tables,
            evidence_figures=answer.evidence_figures,
        )
    except pydantic.ValidationError as exc:
        raise UnexpectedLLMOutputError() from exc

    return typed_result


def get_mock_l2_screening_results(
    question: L2ScreeningQuestion,
    options: List[L2ScreeningQuestionOption],
    citation: Citation,
    text_extraction_result: TextExtractionResult,
) -> L2ScreeningPromptResult:
    selected_option = random.choice(options)

    fulltext = text_extraction_result.get_sentences()
    explanation = "This is a mock explanation for why the option was selected."

    # find sentences using regex for [0], [1], etc. and extract the indices

    sentence_indices = []
    for match in re.finditer(r"\n\n\[(\d+)\]", fulltext):
        sentence_indices.append(int(match.group(1)))

    if sentence_indices:
        max_chosen = math.ceil(len(sentence_indices) / 10)
        sentence_count = random.randint(1, max_chosen)
        chosen_sentences = random.choices(sentence_indices, k=sentence_count)
    else:
        chosen_sentences = []

    chosen_sentences = sorted(set(chosen_sentences))

    return L2ScreeningPromptResult(
        selected=selected_option,
        explanation=explanation,
        confidence=0.5,
        evidence_sentences=chosen_sentences,
        evidence_tables=[],
        evidence_figures=[],
    )
