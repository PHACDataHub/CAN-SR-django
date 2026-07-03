import logging
import uuid

import structlog
from data_fetcher.util import get_request
from phac_aspc.django.helpers.logging import configure_logging
from phac_aspc.django.settings.logging_env import get_logging_env_value

# default logger is just "app"
logger = logging.getLogger("app")


def generate_context_id() -> str:

    return str(uuid.uuid4())


class ContextFilter(logging.Filter):
    def filter(self, record) -> bool:
        request = get_request()
        if not request:
            return True

        context_id = getattr(request, "context_id", None)
        if context_id:
            record.context_id = context_id
            if isinstance(record.msg, dict):
                record.msg["context_id"] = context_id

        return True


class ContextIdRenderer:
    def __init__(self, renderer):
        self.renderer = renderer

    def __call__(self, wrapped_logger, name, event_dict):
        context_id = event_dict.pop("context_id", None)
        if context_id:
            event = event_dict["event"]
            event_dict["event"] = f"[context_id={context_id}] {event}"

        return self.renderer(wrapped_logger, name, event_dict)


class PlainConsoleRenderer:
    def __call__(self, wrapped_logger, name, event_dict):
        level = event_dict["level"].upper()
        logger_name = event_dict["logger"]
        return f"{level}:{logger_name}:{event_dict['event']}"


def configure_project_logging(is_local_dev=False):
    helper_logging_is_configured = (
        configure_logging.is_phac_helper_logging_configuration_being_used
    )
    if not helper_logging_is_configured:
        formatter_key = "context_id_formatter"
        renderer = structlog.processors.JSONRenderer()
        if is_local_dev:
            renderer = PlainConsoleRenderer()
        elif get_logging_env_value("PRETTY_FORMAT_CONSOLE_LOGS"):
            renderer = structlog.dev.ConsoleRenderer()

        configure_logging.configure_uniform_std_lib_and_structlog_logging(
            lowest_level_to_log=get_logging_env_value("LOWEST_LEVEL"),
            mute_console_handler=get_logging_env_value("MUTE_CONSOLE_HANDLER"),
            console_handler_formatter_key=formatter_key,
            additional_formatter_functions={
                formatter_key: ContextIdRenderer(renderer)
            },
        )
        logger.disabled = False

    handlers = logging.getLogger().handlers
    formatters = {
        handler.formatter
        for handler in handlers
        if isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)
    }
    if helper_logging_is_configured:
        for formatter in formatters:
            renderer = formatter.processors[-1]
            formatter.processors = (
                *formatter.processors[:-1],
                ContextIdRenderer(renderer),
            )

        if is_local_dev:
            console_handler = next(
                handler
                for handler in handlers
                if handler.name
                == configure_logging.PHAC_HELPER_CONSOLE_HANDLER_KEY
            )
            formatter = console_handler.formatter
            formatter.processors = (
                *formatter.processors[:-1],
                ContextIdRenderer(PlainConsoleRenderer()),
            )

    for formatter in formatters:
        formatter.foreign_pre_chain = (
            *formatter.foreign_pre_chain,
            structlog.stdlib.ExtraAdder(allow={"context_id"}),
        )

    context_filter = ContextFilter()
    for handler in handlers:
        handler.addFilter(context_filter)
