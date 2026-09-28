from functools import cache
from pathlib import Path
from typing import Any

from pybars import Compiler


@cache
def _compile_prompt(template_name: str):
    template_path = Path(__file__).with_name(template_name)
    return Compiler().compile(template_path.read_text())


def render_prompt(template_name: str, context: dict[str, Any] | Any) -> str:
    return _compile_prompt(template_name)(context)
