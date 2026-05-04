# without explicit urls.py,
#   we need to remember to import all view modules
#   by convention, we do it here
from . import (
    background_tasks,
    llm_demo,
    modal_demo,
    project_crud,
    systematic_review,
)
from .documents import *
