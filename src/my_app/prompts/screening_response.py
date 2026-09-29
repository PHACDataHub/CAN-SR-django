from copy import deepcopy

import pydantic

NONE_OF_THE_ABOVE = "None of the above"


def result_model_without_fields(model, excluded_fields):
    """Derive validation and JSON schemas from the same maximal field set."""
    return pydantic.create_model(
        f"Contextual{model.__name__}",
        __config__=model.model_config,
        **{
            name: (field.annotation, deepcopy(field))
            for name, field in model.model_fields.items()
            if name not in excluded_fields
        },
    )


def screening_options(options, answer_to_critique):
    return [
        option
        for option in options
        if option.is_active
        and (answer_to_critique is None or option.pk != answer_to_critique.pk)
    ]


def response_option_strings(options, answer_to_critique):
    values = [
        option.option_text
        for option in screening_options(options, answer_to_critique)
    ]
    if answer_to_critique is not None:
        values.append(NONE_OF_THE_ABOVE)
    return values
