import json
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
    LanguageModel,
    Parameter,
    TextExtractionResult,
)
from shortcuts import List, dataclass, logger

from .prompt_renderer import render_prompt
from .prompt_util import build_figure_substring, build_table_substring


@dataclass
class ParameterExtractionPromptBuilder:
    parameter: Parameter
    citation: Citation
    text_extraction_result: TextExtractionResult
    tables: List[DocumentTable]
    figures: List[DocumentFigure]

    @dataclass
    class ParameterExtractionPromptArgs:
        parameter_name: str
        parameter_description: str
        units_and_reporting_instructions: str
        calculation_instructions: str
        has_options: bool
        options: str
        fulltext: str
        tables: str
        figures: str
        figure_image_files: List[BinaryIO]

    def get_prompt_args(self) -> ParameterExtractionPromptArgs:
        sentences = self.text_extraction_result.get_sentences()

        table_str = build_table_substring(self.tables)
        figure_str = build_figure_substring(self.figures)
        has_options = self.parameter.option_type == Parameter.OptionType.SELECT
        options = ""
        if has_options:
            options = "\n".join(
                f'- "{option.name}": {option.context}'
                for option in self.parameter.options.all()
            )

        return self.ParameterExtractionPromptArgs(
            parameter_name=self.parameter.name,
            parameter_description=self.parameter.description,
            units_and_reporting_instructions=(
                self.parameter.units_and_reporting_instructions
            ),
            calculation_instructions=self.parameter.calculation_instructions,
            has_options=has_options,
            options=options,
            fulltext=sentences,
            tables=table_str,
            figures=figure_str,
            figure_image_files=[fig.file for fig in self.figures],
        )

    @staticmethod
    def build_str(prompt_args: ParameterExtractionPromptArgs) -> str:
        return render_prompt(
            "parameter_prompt.hbs",
            {
                "parameter_name": prompt_args.parameter_name,
                "parameter_description": prompt_args.parameter_description,
                "units_and_reporting_instructions": (
                    prompt_args.units_and_reporting_instructions
                ),
                "calculation_instructions": prompt_args.calculation_instructions,
                "has_options": prompt_args.has_options,
                "options": prompt_args.options,
                "fulltext": prompt_args.fulltext,
                "tables": prompt_args.tables,
                "figures": prompt_args.figures,
            },
        )


class ParameterExtractionPromptResult(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    found: bool
    value: str | None
    selected_option_id: int | None = None
    explanation: str
    evidence_sentences: List[int]
    evidence_tables: List[int]
    evidence_figures: List[int]


class RawParameterExtractionPromptResult(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    found: bool
    value: str | None
    selected_option: str | None
    explanation: str
    evidence_sentences: List[int]
    evidence_tables: List[int]
    evidence_figures: List[int]


PARAMETER_EXTRACTION_RESPONSE_SCHEMA = LLMResponseSchema(
    name="parameter_extraction_result",
    schema=RawParameterExtractionPromptResult.model_json_schema(),
)


def build_parameter_extraction_response_schema(
    parameter: Parameter,
) -> LLMResponseSchema:
    schema = RawParameterExtractionPromptResult.model_json_schema()
    if parameter.option_type == Parameter.OptionType.SELECT:
        schema["properties"]["selected_option"] = {
            "enum": [
                *parameter.options.values_list("name", flat=True),
                None,
            ],
            "type": ["string", "null"],
        }
    else:
        schema["properties"]["selected_option"] = {"type": "null"}
    return LLMResponseSchema(
        name="parameter_extraction_result",
        schema=schema,
    )


def get_parameter_extraction_results(
    citation: Citation,
    parameter: Parameter,
    text_extraction_result: TextExtractionResult,
    tables: List[DocumentTable],
    figures: List[DocumentFigure],
    model: LanguageModel,
) -> ParameterExtractionPromptResult:
    if not settings.HAS_LLM:
        logger.warning(
            "LLM not available, returning mock parameter extraction result."
        )
        return get_mock_parameter_extraction_results(
            citation, parameter, text_extraction_result, tables, figures
        )

    logger.info(
        "LLM is available, using real LLM results for parameter extraction."
    )
    prompt_builder = ParameterExtractionPromptBuilder(
        parameter, citation, text_extraction_result, tables, figures
    )
    prompt_args = prompt_builder.get_prompt_args()
    prompt = prompt_builder.build_str(prompt_args)
    images = prompt_args.figure_image_files

    llm_client = get_client()
    response_schema = build_parameter_extraction_response_schema(parameter)
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
            model=model,
            response_schema=response_schema,
        )

    try:
        response_dict = json.loads(raw_response)
        raw_result = RawParameterExtractionPromptResult(**response_dict)
        if (
            raw_result.found
            and parameter.option_type == Parameter.OptionType.SELECT
            and raw_result.selected_option is None
        ):
            raise UnexpectedLLMOutputError(
                "LLM did not select an option for a list parameter"
            )
        selected_option_id = None
        if raw_result.selected_option is not None:
            selected_option = parameter.options.filter(
                name__iexact=raw_result.selected_option
            ).first()
            if selected_option is None:
                raise UnexpectedLLMOutputError(
                    "LLM selected an unknown parameter option: "
                    f"{raw_result.selected_option}"
                )
            selected_option_id = selected_option.id
        return ParameterExtractionPromptResult(
            **raw_result.model_dump(exclude={"selected_option", "value"}),
            value=(
                None
                if parameter.option_type == Parameter.OptionType.SELECT
                else raw_result.value
            ),
            selected_option_id=selected_option_id,
        )
    except json.JSONDecodeError as exc:
        raise UnexpectedLLMOutputError(
            f"Failed to parse LLM output as JSON: {raw_response}"
        ) from exc
    except pydantic.ValidationError as exc:
        raise UnexpectedLLMOutputError(
            f"LLM output did not match expected schema: {raw_response}"
        ) from exc


def get_mock_parameter_extraction_results(
    citation: Citation,
    parameter: Parameter,
    text_extraction_result: TextExtractionResult,
    tables: List[DocumentTable],
    figures: List[DocumentFigure],
) -> ParameterExtractionPromptResult:
    sentences = text_extraction_result.get_sentences()
    if not sentences:
        return ParameterExtractionPromptResult(
            found=False,
            value=None,
            selected_option_id=None,
            explanation="No sentences available for extraction.",
            evidence_sentences=[],
            evidence_tables=[],
            evidence_figures=[],
        )

    sentence_indices = [
        int(match.group(1))
        for match in re.finditer(r"(?:^|\n\n)\[(\d+)\]", sentences)
    ]
    if sentence_indices:
        random_sentence_index = random.choice(sentence_indices)
    else:
        random_sentence_index = 0

    return ParameterExtractionPromptResult(
        found=True,
        value=(
            None
            if parameter.option_type == Parameter.OptionType.SELECT
            else f"Mock value from sentence [{random_sentence_index}]"
        ),
        selected_option_id=(
            parameter.options.values_list("id", flat=True).first()
            if parameter.option_type == Parameter.OptionType.SELECT
            else None
        ),
        explanation=f"Mock explanation based on sentence [{random_sentence_index}].",
        evidence_sentences=[random_sentence_index],
        evidence_tables=[],
        evidence_figures=[],
    )
