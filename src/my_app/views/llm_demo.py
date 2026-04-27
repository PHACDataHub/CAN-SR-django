from django.http import HttpResponse, StreamingHttpResponse
from django.views.generic import TemplateView, View

import htpy as h

from proj.htpy.util import HtpyTemplateMixin
from proj.llm_client import LLMMessage, get_client
from proj.text import tdt

from my_app.htpy.llm_demo import LLMDemoPage, build_stream_shell
from my_app.router import route


@route("llm-demo/", name="llm_demo")
class LLMDemoView(TemplateView, HtpyTemplateMixin):
    template_component = LLMDemoPage


@route("llm-demo/shell/", name="llm_demo_shell")
class LLMDemoShellView(View):
    def get(self, request, *args, **kwargs):
        prompt = request.GET.get("prompt", "").strip()
        if not prompt:
            return HttpResponse(
                str(
                    h.div(
                        "#llm-demo-stream-shell.border.rounded.p-3.bg-body-tertiary"
                    )[
                        h.p(".text-muted.mb-0")[
                            tdt("Submit a prompt to load the streaming shell.")
                        ]
                    ]
                )
            )

        return HttpResponse(str(build_stream_shell(prompt)))


@route("llm-demo/stream/", name="llm_demo_stream")
class LLMDemoStreamView(View):
    async def get(self, request, *args, **kwargs):
        prompt = request.GET.get("prompt", "").strip()
        client = get_client()
        messages = [LLMMessage(role="user", content=prompt)]

        async def stream():
            async for chunk in client.astream(messages):
                for line in chunk.splitlines() or [""]:
                    yield f"data: {line}\n"
                yield "\n"
            yield "data: [DONE]\n\n"

        response = StreamingHttpResponse(
            stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
