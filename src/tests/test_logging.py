import io
import logging

from django.http import HttpResponse
from django.urls import path, reverse
from django.views import View

from phac_aspc.django.helpers.logging.configure_logging import (
    PHAC_HELPER_CONSOLE_HANDLER_KEY,
)

from proj.logging import logger


class LoggingView(View):
    def get(self, request):
        logger.info("Test log message")
        return HttpResponse()


urlpatterns = [
    path("test-logging/", LoggingView.as_view(), name="test_logging"),
]


def test_request_logs_include_context_id(
    monkeypatch, settings, vanilla_client
):
    context_id = "fixed-context-id"
    monkeypatch.setattr(
        "proj.middleware.generate_context_id", lambda: context_id
    )
    settings.ROOT_URLCONF = __name__

    handler = next(
        handler
        for handler in logging.getLogger().handlers
        if handler.name == PHAC_HELPER_CONSOLE_HANDLER_KEY
    )
    output = io.StringIO()
    original_stream = handler.setStream(output)

    try:
        response = vanilla_client.get(reverse("test_logging"))
    finally:
        handler.setStream(original_stream)

    assert response.status_code == 200
    assert output.getvalue() == (
        f"INFO:app:[context_id=r-{context_id}] Test log message\n"
    )
