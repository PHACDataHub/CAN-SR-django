import json
import random
import re
from typing import BinaryIO

from django.conf import settings

import pydantic

from proj.llm_client import UnexpectedLLMOutputError, get_client

from my_app.models import (
    Citation,
    DocumentFigure,
    DocumentTable,
    LanguageModel,
    Parameter,
    TextExtractionResult,
)
from shortcuts import List, dataclass, logger

from .prompt_util import build_figure_substring, build_table_substring

PROMPT_JSON_TEMPLATE = """
You are an expert information extractor for scientific full-text articles. You will be given:
- A short description of a parameter to extract (what the parameter is and how it is defined).
- The full text of a paper with each sentence numbered like: [0] First sentence. [1] Second sentence. etc.
- Optionally, numbered tables (as markdown) and numbered figure captions (with the corresponding figure images provided alongside this message).

Task (STRICT):
Return a single valid JSON object and nothing else. The JSON MUST contain the following keys:
- "found": a boolean (true/false) indicating whether the parameter was located or could be confidently derived.
- "value": the extracted value as a string (or null if not found).
- "explanation": a concise explanation (1-4 sentences) describing why this value was chosen or how it was derived.
- "evidence_sentences": an array of integers indicating the sentence indices you used as evidence (e.g. [2, 5]). If there are no supporting sentences, return an empty array.
- "evidence_tables": an array of integers indicating table numbers used (e.g. [1, 2]) or [].
- "evidence_figures": an array of integers indicating figure numbers used (e.g. [3]) or [].

Requirements:
- If the parameter is explicitly present, return the value exactly as found (preserve units/format) and list the sentence indices.
- If the parameter must be computed or approximated, include the computed value and explain the computation in "explanation", and list the sentences used for calculation.
- If the parameter is not present and cannot be deduced, set "found": false, "value": null, "explanation": briefly state why not found, and "evidence_sentences": [].
- If a calculation is defined for the parameter, with a description of variables to be computed, find those variables and walk through the computation in the explanation.
- Do NOT include any extra keys, XML, or human commentary. The output must be parseable by json.loads.
- If a table or figure is referenced, ensure the explanation references the table/figure number and what was extracted from it.

Example valid output:
{{"found": true, "value": "5 mg/kg", "explanation": "The Methods section explicitly lists a dose of 5 mg/kg in sentence [12].", "evidence_sentences": [12], "evidence_tables": [], "evidence_figures": []}}

Do not output anything besides the JSON object.
- Parameter name: {parameter_name}

- Parameter description: {parameter_description}

- Full text (numbered sentences):
{fulltext}

- Tables (numbered):
{tables}


Figures (numbered; captions correspond to images provided alongside this message):
{figures}
"""


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
        fulltext: str
        tables: str
        figures: str
        figure_image_files: List[BinaryIO]

    def get_prompt_args(self) -> ParameterExtractionPromptArgs:
        sentences = self.text_extraction_result.get_sentences()

        table_str = build_table_substring(self.tables)
        figure_str = build_figure_substring(self.figures)

        return self.ParameterExtractionPromptArgs(
            parameter_name=self.parameter.name,
            parameter_description=self.parameter.description,
            fulltext=sentences,
            tables=table_str,
            figures=figure_str,
            figure_image_files=[fig.file for fig in self.figures],
        )

    @staticmethod
    def build_str(prompt_args: ParameterExtractionPromptArgs) -> str:
        return PROMPT_JSON_TEMPLATE.format(
            parameter_name=prompt_args.parameter_name,
            parameter_description=prompt_args.parameter_description,
            fulltext=prompt_args.fulltext,
            tables=prompt_args.tables,
            figures=prompt_args.figures,
        )


class ParameterExtractionPromptResult(pydantic.BaseModel):
    found: bool
    value: str | None
    explanation: str
    evidence_sentences: List[int]
    evidence_tables: List[int]
    evidence_figures: List[int]


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
    if images:
        raw_response = llm_client.complete_multimodal_prompt(
            prompt, files=images, model=model
        )
    else:
        raw_response = llm_client.complete_prompt(prompt, model=model)

    try:
        response_dict = json.loads(raw_response)
        return ParameterExtractionPromptResult(**response_dict)
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
        value=f"Mock value from sentence [{random_sentence_index}]",
        explanation=f"Mock explanation based on sentence [{random_sentence_index}].",
        evidence_sentences=[random_sentence_index],
        evidence_tables=[],
        evidence_figures=[],
    )
