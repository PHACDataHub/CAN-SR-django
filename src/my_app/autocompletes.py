from autocomplete import Autocomplete, ModelAutocomplete, register

from proj.models import User
from proj.text import tdt, tm

from my_app.models.citation import (
    CitationAIStatus,
    CitationHumanStatus,
    CitationStatus,
)


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


class StaticChoiceAutocomplete(
    FixRequiredFieldBaseAutocomplete, SuppressAutofillMixin
):
    minimum_search_length = 0

    # need to override choice dict with {value,label} collection
    choice_dict: dict

    @classmethod
    def search_items(cls, search, context):
        search = search.lower()
        choices = [
            {"key": code, "label": label}
            for code, label in cls.choice_dict.items()
        ]

        if search:
            choices = [
                c
                for c in choices
                if search in c["key"].lower() or search in c["label"].lower()
            ]

        return choices

    @classmethod
    def get_items_from_keys(cls, keys, context):
        items = []
        for key in keys:
            if key not in cls.choice_dict:
                continue
            items.append(
                {
                    "key": key,
                    "label": cls.choice_dict[key],
                }
            )
        return items


@register
class CitationStatusAutocomplete(StaticChoiceAutocomplete):
    minimum_search_length = 0
    choice_dict = {
        CitationStatus.In: tdt("Included"),
        CitationStatus.Out: tdt("Excluded"),
        CitationStatus.Unanswered: tdt("Not started"),
        CitationStatus.Ambiguous: tdt("Undecided"),
    }


@register
class CitationAIStatusAutocomplete(StaticChoiceAutocomplete):
    minimum_search_length = 0
    choice_dict = {
        CitationAIStatus.ConfidentlyIncluded: tdt("Included"),
        CitationAIStatus.AutoExcluded: tdt("Excluded"),
        CitationAIStatus.NotScreenedYet: tdt("Not started"),
        CitationAIStatus.AmbiguouslyIncluded: tdt("Needs Human Review"),
    }


@register
class CitationHumanStatusAutocomplete(StaticChoiceAutocomplete):
    minimum_search_length = 0
    choice_dict = {
        CitationHumanStatus.In: tdt("Validated-in"),
        CitationHumanStatus.Out: tdt("Validated-out"),
        CitationHumanStatus.Unanswered: tdt("Not-validated"),
    }
