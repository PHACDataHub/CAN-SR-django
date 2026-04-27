import json
from urllib.parse import quote_plus

from django.urls import reverse

import htpy as h

from proj.htpy.base_page import BasePageTemplate, static_no_cache
from proj.text import tdt


class LLMDemoPage(BasePageTemplate):
    def title(self):
        return tdt("LLM demo")

    def content(self):

        return [
            h.h1[tdt("LLM demo")],
            h.p(".text-muted")[
                tdt(
                    "Use the form below to load a streaming prompt shell with HTMX."
                )
            ],
            h.p(".text-muted")[
                tdt(
                    "The shell then opens a tiny EventSource connection to the async stream endpoint."
                )
            ],
            h.form(
                hx_get=reverse("llm_demo_shell"),
                hx_target="#llm-demo-shell",
                hx_swap="innerHTML",
                method="get",
                class_="mb-3",
            )[
                h.label(".form-label", for_="llm-prompt")[tdt("Prompt")],
                h.textarea(
                    ".form-control",
                    id="llm-prompt",
                    name="prompt",
                    rows="5",
                    placeholder=tdt("Ask the model something"),
                ),
                h.div(".mt-3")[
                    h.button(".btn.btn-primary", type="submit")[
                        tdt("Stream response")
                    ]
                ],
            ],
            h.div("#llm-demo-shell.border.rounded.p-3.bg-body-tertiary")[
                h.p(".text-muted.mb-0")[
                    tdt("Submit a prompt to load the streaming shell.")
                ]
            ],
        ]


def build_stream_shell(prompt: str):

    stream_url = reverse("llm_demo_stream") + f"?prompt={quote_plus(prompt)}"

    return h.div(
        id="llm-demo-stream-shell",
        data_stream_url=stream_url,
    )[
        h.div(".d-flex.align-items-center.gap-2.mb-2")[
            h.div(".spinner-border.spinner-border-sm", role="status"),
            h.strong[tdt("Streaming response")],
            h.span(".text-muted", data_stream_status=True)[tdt("Starting")],
        ],
        h.pre(
            ".border.rounded.bg-dark.text-light.p-3.mb-0",
            style="min-height: 12rem; white-space: pre-wrap;",
            data_stream_output=True,
        )[""],
        h.script(
            src=static_no_cache("stream_shell.js"),
            data_translations=json.dumps(
                {
                    "done": tdt("Done"),
                    "stream_closed": tdt("Stream closed"),
                }
            ),
        ),
    ]
