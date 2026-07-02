import logging
import uuid


# default logger is just "app"
logger = logging.getLogger("app")
def generate_context_id() -> str:

    return str(uuid.uuid4())

