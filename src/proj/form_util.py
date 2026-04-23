from django import forms
from django.forms import widgets

from proj.text import tm

# TODO: this mixin isn't easily overriden.
# Ideally we'd plug into this logic into a ModelForm subclass, or use different model-fields altogether

widget_classes_that_should_have_form_control = [
    forms.widgets.TextInput,
    forms.widgets.NumberInput,
    forms.widgets.DateInput,
    forms.widgets.DateTimeInput,
    forms.widgets.TimeInput,
    forms.widgets.SelectMultiple,
    forms.widgets.EmailInput,
    forms.widgets.URLInput,
    forms.widgets.PasswordInput,
    forms.widgets.FileInput,
    forms.widgets.Textarea,
]


class FormControlMixin(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # not all forms have a class Meta

        for key, field in self.fields.items():
            for widget_class in widget_classes_that_should_have_form_control:
                if isinstance(field.widget, widget_class):
                    field.widget.attrs["class"] = (
                        field.widget.attrs.get("class", "") + " form-control"
                    )


class SelectMixin(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for key, field in self.fields.items():
            if isinstance(field.widget, forms.widgets.Select):
                field.widget.attrs["class"] = (
                    field.widget.attrs.get("class", "") + " form-select"
                )

    def configure_select_null_option(self, fieldname, label=None):
        """
        for a11y, we want to replace any ---- options
        with a better label
        tm("please_select_an_option_below") is a good option
        sometimes, tm("all") may be better
        """

        if label is None:
            label = tm("please_select_an_option_below")

        f = self.fields[fieldname]

        value = f.widget.choices[0][0]
        if not value in (None, "", 0):
            raise ValueError(
                f"Cannot set null option for {fieldname}, choice is not blank"
            )

        f.widget.choices = [(value, label)] + list(f.choices)[1:]


class NumberInputMixin(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for key, field in self.fields.items():
            if isinstance(field.widget, forms.widgets.NumberInput):
                field.widget.attrs["type"] = "number"
                # right-align numbers
                field.widget.attrs["class"] = (
                    field.widget.attrs.get("class", "") + " text-end"
                )


class TallTextAreasMixin(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for key, field in self.fields.items():
            if isinstance(field.widget, forms.widgets.Textarea):
                field.widget.attrs["rows"] = 5


class M2MWidgetMixin(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for key, field in self.fields.items():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget = forms.CheckboxSelectMultiple(
                    choices=field.choices
                )


class DateInputMixin(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for key, field in self.fields.items():
            if isinstance(field.widget, forms.widgets.DateInput):
                field.widget.input_type = "date"


class YesNoMixin(forms.Form):
    """
    Translates/capitalizes the default yes/no labels
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            if hasattr(field, "choices") and isinstance(field.choices, list):
                self.translate_choices(field.choices)

            if hasattr(field.widget, "choices") and isinstance(
                field.choices, list
            ):
                self.translate_choices(field.widget.choices)

    @staticmethod
    def translate_choices(choices):
        # modifies a list in place

        for i, (value, label) in enumerate(choices):
            if label in ("yes", "Yes"):
                choices[i] = (value, tm("yes"))
            elif label in ("no", "No"):
                choices[i] = (value, tm("no"))


class DisableAutocompleteMixin(forms.Form):
    """
    Disables autocomplete for all fields
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for key, field in self.fields.items():
            if isinstance(
                field.widget,
                (
                    widgets.TextInput,
                    widgets.Textarea,
                    widgets.EmailInput,
                    widgets.PasswordInput,
                    widgets.URLInput,
                ),
            ):
                field.widget.attrs["autocomplete"] = "new-password"


class RequiredMixin(forms.Form):
    required_css_class = "required"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if field.required:
                # add aria-required
                field.widget.attrs["aria-required"] = "true"


class ExplicitlyRequiredFieldNamesMixin(forms.Form):
    """
    changes required error messages from "this field is required" to
    "<fieldname> is required"

    You can opt in to particular fields by setting a list on the class.
    Otherwise, it will apply to all required fields
    """

    explicitly_required_field_names = None

    def get_required_error_message(self, field_name):
        label = (
            # BoundField label (always the humanized one)
            # force non-lazy str before passing to tm()
            self[field_name].label
            + ""
        )
        return tm("fieldname_is_required", text_kwargs={"field": label})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.explicitly_required_field_names is None:
            fieldnames = self.fields.keys()
        else:
            fieldnames = self.explicitly_required_field_names

        # Use BoundField to get the final, human label (pretty_name / Meta.labels / model verbose_name)
        for name, field in self.fields.items():
            if name not in fieldnames:
                continue

            field.error_messages["required"] = self.get_required_error_message(
                name
            )


class StandardFormMixin(
    FormControlMixin,
    NumberInputMixin,
    TallTextAreasMixin,
    M2MWidgetMixin,
    DateInputMixin,
    YesNoMixin,
    SelectMixin,
    RequiredMixin,
    DisableAutocompleteMixin,
):
    pass
