# without explicit urls.py,
#   we need to remember to import all view modules
#   by convention, we do it here
from . import (
    background_tasks,
    citation_dataset,
    citation_upload,
    documents,
    llm_demo,
    screening_criteria,
    systematic_review,
)
