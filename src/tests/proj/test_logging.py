import logging
from io import StringIO

import structlog

from proj.logging import ContextIdRenderer, PlainConsoleRenderer


def console_logger():
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                ContextIdRenderer(PlainConsoleRenderer()),
            ],
        )
    )
    logger = logging.Logger("app", level=logging.INFO)
    logger.addHandler(handler)
    return logger, output


def test_plain_console_preserves_exception_traceback():
    # Use the actual stdlib -> structlog -> console formatting path: a captured
    # LogRecord alone would miss the renderer dropping the traceback.
    logger, output = console_logger()
    try:
        raise RuntimeError("PDF storage unavailable")
    except RuntimeError:
        logger.exception("DOI PDF task failed")
    rendered = output.getvalue()
    assert "ERROR:app:DOI PDF task failed" in rendered
    assert rendered.count("Traceback (most recent call last)") == 1
    assert "RuntimeError: PDF storage unavailable" in rendered


def test_plain_console_preserves_stack_info():
    logger, output = console_logger()
    logger.warning("Inspect task dispatch", stack_info=True)
    assert "WARNING:app:Inspect task dispatch" in output.getvalue()
    assert "Stack (most recent call last)" in output.getvalue()


def test_plain_console_keeps_normal_log_format():
    logger, output = console_logger()
    logger.info("DOI PDF task started")
    assert output.getvalue() == "INFO:app:DOI PDF task started\n"
