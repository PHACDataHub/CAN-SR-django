# without explicit urls.py,
#   we need to remember to import all view modules
#   by convention, we do it here
from my_app import detail_modals

from . import (
    citation_dataset,
    citation_upload,
    review,
    screening,
    screening_criteria,
    tables,
    user_management,
)
