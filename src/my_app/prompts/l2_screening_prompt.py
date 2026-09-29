import json
import math
import random
import re
from functools import cache
from typing import BinaryIO

from django.conf import settings

import pydantic

from proj.llm_client import (
    LLMResponseSchema,
    UnexpectedLLMOutputError,
    get_client,
)

from my_app.models import (
    Citation,
    DocumentFigure,
    DocumentTable,
    L2ScreeningQuestion,
    L2ScreeningQuestionOption,
    LanguageModel,
    TextExtractionResult,
)
from shortcuts import List, dataclass, logger

from .prompt_renderer import render_prompt
from .prompt_util import (
    build_figure_substring,
    build_option_definition_string,
    build_option_string,
    build_table_substring,
)
from .screening_response import (
    NONE_OF_THE_ABOVE,
    response_option_strings,
    result_model_without_fields,
    screening_options,
)


@dataclass
class L2ScreeningPromptBuilder:
    question: L2ScreeningQuestion
    options: List[L2ScreeningQuestionOption]
    citation: Citation
    text_extraction_result: TextExtractionResult
    tables: List[DocumentTable]
    figures: List[DocumentFigure]
    answer_to_critique: L2ScreeningQuestionOption | None = None

    def __post_init__(self):
        self.options = screening_options(self.options, self.answer_to_critique)

    @dataclass
    class ScreeningPromptArgs:
        question: str
        options: str
        definitions: str
        fulltext: str
        tables: str
        figures: str
        has_tables: bool
        has_figures: bool
        has_tables_or_figures: bool
        figure_image_files: List[BinaryIO]
        is_critical: bool = False
        answer_to_critique: str = ""

    def get_screening_prompt_args(
        self,
    ) -> ScreeningPromptArgs:
        sentences = self.text_extraction_result.get_sentences()

        option_info_string = build_option_definition_string(self.options)
        option_string = build_option_string(self.options)
        if self.answer_to_critique is not None:
            option_string += f"\n'{NONE_OF_THE_ABOVE}'"

        table_str = build_table_substring(self.tables)
        figure_str = build_figure_substring(self.figures)

        answer_to_critique = ""
        if self.answer_to_critique is not None:
            answer_to_critique = self.answer_to_critique.option_text
        return self.ScreeningPromptArgs(
            is_critical=self.answer_to_critique is not None,
            answer_to_critique=answer_to_critique,
            question=self.question.question_text,
            options=option_string,
            definitions=option_info_string,
            fulltext=sentences,
            tables=table_str,
            figures=figure_str,
            has_tables=bool(self.tables),
            has_figures=bool(self.figures),
            has_tables_or_figures=bool(self.tables or self.figures),
            figure_image_files=[fig.file for fig in self.figures],
        )

    @staticmethod
    def build_str(prompt_args: ScreeningPromptArgs) -> str:
        return render_prompt("l2_screening_prompt.hbs", prompt_args)


class RawL2ScreeningPromptResult(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    selected: str
    # Explanation and all evidence fields are removed for critical reviews.
    explanation: str
    confidence: pydantic.confloat(ge=0.0, le=1.0)
    evidence_sentences: List[int]
    # Removed when the corresponding source material is absent.
    evidence_tables: List[int]
    evidence_figures: List[int]


@cache
def build_raw_l2_result_model(
    has_tables: bool,
    has_figures: bool,
    is_critical: bool = False,
) -> type[pydantic.BaseModel]:
    excluded = set()
    if is_critical:
        excluded.update(
            {
                "explanation",
                "evidence_sentences",
                "evidence_tables",
                "evidence_figures",
            }
        )
    if not has_tables:
        excluded.add("evidence_tables")
    if not has_figures:
        excluded.add("evidence_figures")
    return result_model_without_fields(RawL2ScreeningPromptResult, excluded)


def build_l2_response_schema(
    options: List[L2ScreeningQuestionOption],
    has_tables: bool,
    has_figures: bool,
    answer_to_critique: L2ScreeningQuestionOption | None = None,
) -> LLMResponseSchema:
    # expected enums are run-time determined because they come from the user
    result_model = build_raw_l2_result_model(
        has_tables, has_figures, answer_to_critique is not None
    )
    schema = result_model.model_json_schema()
    schema["properties"]["selected"]["enum"] = response_option_strings(
        options, answer_to_critique
    )
    schema["properties"]["confidence"].pop("minimum")
    schema["properties"]["confidence"].pop("maximum")
    return LLMResponseSchema(name="l2_screening_result", schema=schema)


class L2ScreeningPromptResult(RawL2ScreeningPromptResult):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    selected: L2ScreeningQuestionOption | None
    explanation: str | None = None


def get_l2_screening_results(
    question: L2ScreeningQuestion,
    options: List[L2ScreeningQuestionOption],
    citation: Citation,
    text_extraction_result: TextExtractionResult,
    tables: List[DocumentTable],
    figures: List[DocumentFigure],
    model: LanguageModel,
    answer_to_critique: L2ScreeningQuestionOption | None = None,
) -> L2ScreeningPromptResult:
    if not settings.HAS_LLM:
        logger.warning("LLM is not available, using mock results.")
        return get_mock_l2_screening_results(
            question,
            options,
            citation,
            text_extraction_result,
            answer_to_critique=answer_to_critique,
        )

    options = screening_options(options, answer_to_critique)
    logger.info("LLM is available, using real LLM results for L2 screening")
    prompt_builder = L2ScreeningPromptBuilder(
        question,
        options,
        citation,
        text_extraction_result,
        tables,
        figures,
        answer_to_critique,
    )

    prompt_args = prompt_builder.get_screening_prompt_args()
    prompt = prompt_builder.build_str(prompt_args)
    images = prompt_args.figure_image_files
    response_schema = build_l2_response_schema(
        options,
        prompt_args.has_tables,
        prompt_args.has_figures,
        answer_to_critique,
    )

    llm_client = get_client()
    if images:
        raw_response = llm_client.complete_multimodal_prompt(
            prompt,
            files=images,
            model=model,
            response_schema=response_schema,
        )
    else:
        raw_response = llm_client.complete_prompt(
            prompt,
            model,
            response_schema=response_schema,
        )

    try:
        response_dict = json.loads(raw_response)
        result_model = build_raw_l2_result_model(
            prompt_args.has_tables,
            prompt_args.has_figures,
            answer_to_critique is not None,
        )
        answer = result_model.model_validate(response_dict)

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
        typed_result = L2ScreeningPromptResult(
            selected=selected_option,
            explanation=getattr(answer, "explanation", None),
            confidence=answer.confidence,
            evidence_sentences=getattr(answer, "evidence_sentences", []),
            evidence_tables=getattr(answer, "evidence_tables", []),
            evidence_figures=getattr(answer, "evidence_figures", []),
        )
    except pydantic.ValidationError as exc:
        raise UnexpectedLLMOutputError() from exc

    return typed_result


def get_mock_l2_screening_results(
    question: L2ScreeningQuestion,
    options: List[L2ScreeningQuestionOption],
    citation: Citation,
    text_extraction_result: TextExtractionResult,
    answer_to_critique: L2ScreeningQuestionOption | None = None,
) -> L2ScreeningPromptResult:
    options = screening_options(options, answer_to_critique)
    if answer_to_critique is not None:
        return L2ScreeningPromptResult(
            selected=random.choice([*options, None]),
            confidence=0.5,
            evidence_sentences=[],
            evidence_tables=[],
            evidence_figures=[],
        )

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
