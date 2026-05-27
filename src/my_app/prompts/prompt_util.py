from typing import List

from my_app.models import AbstractScreeningQuestion

# the sub-prompt gets used for
OPTION_DEFINITION_SUB_TEMPLATE = """
For articles that satisfy the below criteria in XML tags <{key}></{key}> we answer with "{key}":\n\n<{key}>\n{info}\n</{key}>
"""


def build_option_definition_string(options: List[AbstractScreeningQuestion]):
    return "\n".join(
        [
            OPTION_DEFINITION_SUB_TEMPLATE.format(
                key=opt.option_text, info=opt.option_value
            )
            for opt in options
        ]
    )


def build_option_string(options: List[AbstractScreeningQuestion]):
    return "\n".join(
        [f"{j}. {opt.option_text}" for j, opt in enumerate(options)]
    )
