import typing

from django import http
from django.http import HttpRequest
from django.template.context import ContextDict
from django.views import View as DjangoView
from django.views.generic import TemplateView as DjangoTemplateView
from django.views.generic.base import TemplateResponseMixin

import htpy
from markupsafe import Markup

from proj.text import tm


class HtpyComponent(htpy.Renderable):
    """
    When simple functions get too complex, use this and override render()
    NOTE: This does not (currently) support htpy-style attributes/children
    """

    def render(self):
        raise NotImplementedError("Subclasses must implement render method")

    def __str__(self):
        return str(self.render())

    def __html__(self):
        return self.render()

    def iter_chunks(self, context=None):
        return iter(str(self.render()))

    async def aiter_chunks(self, context=None):
        # not sure if this even works...
        return self.iter_chunks(context)


def as_safe_renderable(
    value: htpy.Node | str | int | float | None,
) -> htpy.Node:
    """
    Ensure the value is an htpy-renderable. If it's already a Node, return it as-is.
    If it's a string, int, float, or None, treat it as safe text
    """

    if value is None:
        return None

    if isinstance(value, (str, int, float)):
        return Markup(str(value))

    else:
        return value


# For a tighter coupling between view and component,
# you can ignore the template API, have views subclass this
# and return htpy nodes from content/title/content_fluid overrides
# this co-location makes it easier to follow flow of data and types
# try not to use context when rendering
class HtpyTemplatelessMixin(TemplateResponseMixin):
    """
    render from the view via title/content/content_fluid overrides
    """

    template_name = "proj.htpy.base_page.BasePageComponent"

    def title(self):
        return None

    def content(self):
        return None

    def content_fluid(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title()
        context["content"] = self.content()
        context["content_fluid"] = self.content_fluid()
        return context


# Alternatively, the HtpyTemplateMixin keeps views and template decoupled,
# this is the traditional MVT pattern
# great for interop and migrating existing templates


class HtpyTemplateMixin(TemplateResponseMixin):
    """
    facilitates using htpy components as templates
    rather than provide module paths to htpy templates,
    just provide the reference to the component class/function
    via the template_component class attribute
    """

    # override this with the component class/func
    # recall that templates receive a context and a request argument
    # note: this class must be statically importable
    template_component: typing.Callable[
        [ContextDict, HttpRequest],
        htpy.Node | htpy.Renderable,
    ]

    def get_template_names(self):
        # return the module path the template component
        cls = self.template_component
        module_str = [f"{cls.__module__}.{cls.__name__}"]
        return module_str
