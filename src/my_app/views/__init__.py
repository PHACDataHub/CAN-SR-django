# without explicit urls.py,
#   we need to remember to import all view modules
#   by convention, we do it here
from . import (
    background_tasks_demo,
    citation_dataset,
    citation_upload,
    parameter_extraction_views,
    review,
    screening,
    screening_criteria,
)
