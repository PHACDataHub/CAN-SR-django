import json
import math
import random
import re
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
from my_app.queries import options_for_question
from shortcuts import List, dataclass, logger

from .prompt_renderer import render_prompt
from .prompt_util import (
    build_figure_substring,
    build_option_definition_string,
    build_option_string,
    build_table_substring,
)


@dataclass
class L2ScreeningPromptBuilder:
    question: L2ScreeningQuestion
    options: List[L2ScreeningQuestionOption]
    citation: Citation
    text_extraction_result: TextExtractionResult
    tables: List[DocumentTable]
    figures: List[DocumentFigure]

    @dataclass
    class ScreeningPromptArgs:
        question: str
        options: str
        definitions: str
        fulltext: str
        tables: str
        figures: str
        figure_image_files: List[BinaryIO]

    def get_screening_prompt_args(
        self,
    ) -> ScreeningPromptArgs:
        sentences = self.text_extraction_result.get_sentences()

        option_info_string = build_option_definition_string(self.options)
        option_string = build_option_string(self.options)

        table_str = build_table_substring(self.tables)
        figure_str = build_figure_substring(self.figures)

        return self.ScreeningPromptArgs(
            question=self.question.question_text,
            options=option_string,
            definitions=option_info_string,
            fulltext=sentences,
            tables=table_str,
            figures=figure_str,
            figure_image_files=[fig.file for fig in self.figures],
        )

    @staticmethod
    def build_str(prompt_args: ScreeningPromptArgs) -> str:
        return render_prompt(
            "l2_screening_prompt.hbs",
            {
                "question": prompt_args.question,
                "options": prompt_args.options,
                "definitions": prompt_args.definitions,
                "fulltext": prompt_args.fulltext,
                "tables": prompt_args.tables,
                "figures": prompt_args.figures,
            },
        )


class RawL2ScreeningPromptResult(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    selected: str
    explanation: str
    confidence: pydantic.confloat(ge=0.0, le=1.0)
    evidence_sentences: List[int]
    evidence_tables: List[int]
    evidence_figures: List[int]


def build_l2_response_schema(
    options: List[L2ScreeningQuestionOption],
) -> LLMResponseSchema:
    # expected enums are run-time determined because they come from the user
    schema = RawL2ScreeningPromptResult.model_json_schema()
    schema["properties"]["selected"]["enum"] = [
        option.option_text for option in options
    ]
    schema["properties"]["confidence"].pop("minimum")
    schema["properties"]["confidence"].pop("maximum")
    return LLMResponseSchema(name="l2_screening_result", schema=schema)


class L2ScreeningPromptResult(RawL2ScreeningPromptResult):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)
    selected: L2ScreeningQuestionOption


def get_l2_screening_results(
    question: L2ScreeningQuestion,
    options: List[L2ScreeningQuestionOption],
    citation: Citation,
    text_extraction_result: TextExtractionResult,
    tables: List[DocumentTable],
    figures: List[DocumentFigure],
    model: LanguageModel,
) -> L2ScreeningPromptResult:
    if not settings.HAS_LLM:
        logger.warning("LLM is not available, using mock results.")
        return get_mock_l2_screening_results(
            question, options, citation, text_extraction_result
        )

    logger.info("LLM is available, using real LLM results for L2 screening")
    prompt_builder = L2ScreeningPromptBuilder(
        question, options, citation, text_extraction_result, tables, figures
    )

    prompt_args = prompt_builder.get_screening_prompt_args()
    prompt = prompt_builder.build_str(prompt_args)
    images = prompt_args.figure_image_files

    llm_client = get_client()
    if images:
        raw_response = llm_client.complete_multimodal_prompt(
            prompt,
            files=images,
            model=model,
            response_schema=build_l2_response_schema(options),
        )
    else:
        raw_response = llm_client.complete_prompt(
            prompt,
            model,
            response_schema=build_l2_response_schema(options),
        )

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
