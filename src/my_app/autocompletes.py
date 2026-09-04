from autocomplete import Autocomplete, ModelAutocomplete, register

from proj.models import User


class SuppressAutofillMixin:
    autocomplete_attr = "one-time-code"


class FixRequiredFieldBaseAutocomplete(Autocomplete):
    @classmethod
    def get_items_from_keys(cls, keys, context):
        # TODO: fix this upstream? What's going on?
        # Is this still necessary if we don't set required=True ?
        keys = [key for key in keys if key]
        return super().get_items_from_keys(keys, context)


@register
class UserAutocomplete(
    FixRequiredFieldBaseAutocomplete, ModelAutocomplete, SuppressAutofillMixin
):
    model = User
    search_attrs = ["email"]
    minimum_search_length = 0
