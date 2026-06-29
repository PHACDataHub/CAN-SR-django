from typing import List

from my_app.models import (
    AbstractScreeningQuestion,
    DocumentFigure,
    DocumentTable,
    TextExtractionResult,
)

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
    return "\n".join([f"'{opt.option_text}'" for opt in options])


def build_table_substring(tables: List[DocumentTable]) -> str:
    if not tables:
        return "(none)"

    entries = [_table_entry(table) for table in tables]
    return "\n\n".join(entries)


def _table_entry(table: DocumentTable) -> str:
    result = ""

    if table.caption:
        caption = f" caption: {table.caption}"
    else:
        caption = ""
    header = f"Table {table.index} {caption}"

    result = header + "\n" + table.table_markdown
    return result


def build_figure_substring(figures: List[DocumentFigure]) -> str:

    if not figures:
        return "(none)"

    figure_lines = []
    for fig in figures:
        if fig.caption:
            caption = fig.caption
        else:
            caption = "(no caption)"
        figure_lines.append(
            f"Figure [F{fig.index}] caption: {caption} (see attached image F{fig.index})"
        )

    return "\n".join(figure_lines)
