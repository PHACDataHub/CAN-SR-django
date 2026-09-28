import json
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
        has_tables: bool
        has_figures: bool
        has_tables_or_figures: bool
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
                for option in self.parameter.options.filter(
                    deletion_time__isnull=True
                )
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
            has_tables=bool(self.tables),
            has_figures=bool(self.figures),
            has_tables_or_figures=bool(self.tables or self.figures),
            figure_image_files=[fig.file for fig in self.figures],
        )

    @staticmethod
    def build_str(prompt_args: ParameterExtractionPromptArgs) -> str:
        return render_prompt(
            "parameter_prompt.hbs",
            prompt_args,
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
    explanation: str
    evidence_sentences: List[int]


@cache
def build_raw_parameter_result_model(
    has_options: bool,
    has_tables: bool,
    has_figures: bool,
) -> type[RawParameterExtractionPromptResult]:
    if has_options:
        fields = {"selected_option": (str | None, ...)}
    else:
        fields = {"value": (str | None, ...)}
    if has_tables:
        fields["evidence_tables"] = (List[int], ...)
    if has_figures:
        fields["evidence_figures"] = (List[int], ...)
    return pydantic.create_model(
        "ContextualRawParameterExtractionPromptResult",
        __base__=RawParameterExtractionPromptResult,
        **fields,
    )


def build_parameter_extraction_response_schema(
    parameter: Parameter,
    has_tables: bool,
    has_figures: bool,
) -> LLMResponseSchema:
    has_options = parameter.option_type == Parameter.OptionType.SELECT
    result_model = build_raw_parameter_result_model(
        has_options,
        has_tables,
        has_figures,
    )
    schema = result_model.model_json_schema()
    if has_options:
        schema["properties"]["selected_option"] = {
            "enum": [
                *parameter.options.values_list("name", flat=True),
                None,
            ],
            "type": ["string", "null"],
        }
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
    response_schema = build_parameter_extraction_response_schema(
        parameter,
        prompt_args.has_tables,
        prompt_args.has_figures,
    )
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
        result_model = build_raw_parameter_result_model(
            prompt_args.has_options,
            prompt_args.has_tables,
            prompt_args.has_figures,
        )
        raw_result = result_model(**response_dict)
        selected_option_name = getattr(raw_result, "selected_option", None)
        extracted_value = getattr(raw_result, "value", None)
        if (
            raw_result.found
            and parameter.option_type == Parameter.OptionType.SELECT
            and selected_option_name is None
        ):
            raise UnexpectedLLMOutputError(
                "LLM did not select an option for a list parameter"
            )
        selected_option_id = None
        if selected_option_name is not None:
            selected_option = parameter.options.filter(
                name__iexact=selected_option_name
            ).first()
            if selected_option is None:
                raise UnexpectedLLMOutputError(
                    "LLM selected an unknown parameter option: "
                    f"{selected_option_name}"
                )
            selected_option_id = selected_option.id
        return ParameterExtractionPromptResult(
            **raw_result.model_dump(
                exclude={
                    "selected_option",
                    "value",
                    "evidence_tables",
                    "evidence_figures",
                }
            ),
            value=extracted_value,
            selected_option_id=selected_option_id,
            evidence_tables=getattr(raw_result, "evidence_tables", []),
            evidence_figures=getattr(raw_result, "evidence_figures", []),
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
