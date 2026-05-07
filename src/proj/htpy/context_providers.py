from contextvars import ContextVar
from typing import Callable

import htpy
from htpy import Context, Node
from markupsafe import Markup


class _ConcatenatingProvider:
    def __init__(self, provider_func: Callable[[Node], Node]):
        self.provider_func = provider_func

    def __getitem__(self, children: Node) -> Node:
        return self.provider_func(children)


class _ContextBoundNode:
    def __init__(self, context_value: ContextVar[str], value: str, node: Node):
        self.context_value = context_value
        self.value = value
        self.node = node

    def __str__(self) -> Markup:
        token = self.context_value.set(self.value)
        try:
            return Markup(str(self.node))
        finally:
            self.context_value.reset(token)

    __html__ = __str__

    def iter_chunks(self, context=None):
        token = self.context_value.set(self.value)
        try:
            if context is None:
                yield from self.node.iter_chunks()
            else:
                yield from self.node.iter_chunks(context)
        finally:
            self.context_value.reset(token)

    def aiter_chunks(self, context=None):
        token = self.context_value.set(self.value)

        async def _iterator():
            try:
                if context is None:
                    async for chunk in self.node.aiter_chunks():
                        yield chunk
                else:
                    async for chunk in self.node.aiter_chunks(context):
                        yield chunk
            finally:
                self.context_value.reset(token)

        return _iterator()


class ConcatenatingStringContext:
    """
    Wrapper around ``htpy.Context`` that concatenates nested provider values.

    Example:
        label_context.provider(value="x")[
            label_context.provider(value="y")[my_consumer()],
            my_consumer(),
        ]

    Consumers inside the nested provider receive ``"x y"`` while sibling
    consumers receive ``"x"``.

    AI built this, probably over-engineered.
    We just want a way to easily and flexibly pass strings
    down the component tree and have them concatenate when nested so they
    can be used for things like multi-part IDs like aria-labelledby
    """

    def __init__(
        self,
        name: str,
        *,
        default: str = "",
        separator: str = " ",
    ):
        self._context: Context[str] = Context(name, default=default)
        self._default = default
        self._separator = separator
        self._context_value: ContextVar[str] = ContextVar(
            f"concatenating-context-{name}", default=default
        )

    def _combine(self, current_value: str, value: str) -> str:
        chunks = [chunk for chunk in [current_value, value] if chunk]
        return self._separator.join(chunks)

    def provider(self, *, value: str) -> _ConcatenatingProvider:
        @self._context.consumer
        def _provider(current_value: str, children: Node) -> Node:
            merged_value = self._combine(current_value, value)
            node = self._context.provider(merged_value, children)
            return _ContextBoundNode(self._context_value, merged_value, node)

        return _ConcatenatingProvider(_provider)

    def consumer(self, component: Callable[..., Node]) -> Callable[..., Node]:
        return self._context.consumer(component)

    def get(self) -> str:
        return self._context_value.get()

    @property
    def default(self) -> str:
        return self._default


aria_labelledby_context = ConcatenatingStringContext("aria-labelledby")


@htpy.with_children
def WithAriaLabelledBy(
    children: htpy.Node, label_id: str, label_text=None
) -> Node:
    """
    All CjdStandardFields in this component's subtree
    will have provided aria-labeledby values

    does not work (yet?) on autocomplete fields

    if you don't pass label_text,
    it's assumed you're rendering that element yourself

    """

    if label_text is None:
        return aria_labelledby_context.provider(value=label_id)[children]

    label_element = htpy.div({"id": label_id, "class": "visually-hidden"})[
        label_text
    ]

    return htpy.fragment[
        label_element,
        aria_labelledby_context.provider(value=label_id)[children],
    ]
