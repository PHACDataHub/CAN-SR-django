from django.test import signals

from htpy.django import _HtpyTemplate
from jinja2 import Template as Jinja2Template

# Without this, response.context is not accessible in forms
# this is useful for assertions on forms, and debugging tests
ORIGINAL_JINJA2_RENDERER = Jinja2Template.render


def instrumented_render(template_object, *args, **kwargs):
    context = dict(*args, **kwargs)
    signals.template_rendered.send(
        sender=template_object, template=template_object, context=context
    )
    return ORIGINAL_JINJA2_RENDERER(template_object, *args, **kwargs)


Jinja2Template.render = instrumented_render


ORIGINAL_HTPY_RENDERER = _HtpyTemplate.render


def instrumented_htpy_render(self, context, request):
    signals.template_rendered.send(
        sender=self.func, template=self.func, context=context
    )
    return ORIGINAL_HTPY_RENDERER(self, context, request)


_HtpyTemplate.render = instrumented_htpy_render
