from my_app.models import (
    CitationDatasetRow,
    L1ScreeningQuestion,
    L1ScreeningQuestionOption,
    ParameterQuestion,
)
from shortcuts import List, dataclass

# the sub-prompt gets used for
KEY_INFO_SUB_PROMPT_TEMPLATE = """
For articles that satisfy the below criteria in XML tags <{key}></{key}> we answer with "{key}":\n\n<{key}>\n{info}\n</{key}>
"""

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
        self, question: L1ScreeningQuestion, citation: CitationDatasetRow
    ):
        self.question = question
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
        options = L1ScreeningQuestionOption.objects.filter(
            question=self.question
        )
        columns_to_include = self.citation.dataset.screening_columns.all()
        citation_text = self.citation.serialize_for_prompt(columns_to_include)

        option_info_subprompt = "\n".join(
            [
                KEY_INFO_SUB_PROMPT_TEMPLATE.format(
                    key=opt.option_text, info=opt.option_value
                )
                for opt in options
            ]
        )

        return self.ScreeningPromptArgs(
            question=self.question.question_text,
            citation=citation_text,
            options="\n".join(
                [f"{j}. {opt.option_text}" for j, opt in enumerate(options)]
            ),
            definitions=option_info_subprompt,
        )

    def build_str(self):
        prompt_args = self.get_screening_prompt_args()
        return PROMPT_JSON_TEMPLATE.format(
            question=prompt_args.question,
            citation=prompt_args.citation,
            options=prompt_args.options,
            definitions=prompt_args.definitions,
        )
