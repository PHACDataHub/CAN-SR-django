from django.test import signals

from htpy.django import _HtpyTemplate

ORIGINAL_HTPY_RENDERER = _HtpyTemplate.render


def instrumented_htpy_render(self, context, request):
    signals.template_rendered.send(
        sender=self.func, template=self.func, context=context
    )
    return ORIGINAL_HTPY_RENDERER(self, context, request)


_HtpyTemplate.render = instrumented_htpy_render
