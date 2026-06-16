from collections import defaultdict
from typing import Dict, List, Union

from django.utils.translation import get_language

JSONValue = Union[
    str, int, float, bool, None, Dict[str, "JSONValue"], List["JSONValue"]
]


def group_by(iterable, key):
    groups = defaultdict(list)
    for item in iterable:
        groups[key(item)].append(item)
    return groups


def flatten(iterable):
    return [item for sublist in iterable for item in sublist]


def get_lang_code():
    lang_locale = get_language()
    if "-ca" not in lang_locale:
        raise Exception("Unexpected language locale: {}".format(lang_locale))
    return lang_locale.split("-ca")[0]


class MissingPreconditionError(Exception):
    pass
