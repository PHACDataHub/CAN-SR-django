from django.forms import inlineformset_factory
from django.http import QueryDict

from proj.form_util import SoftDeleteInlineFormSet

from my_app.model_factories import ParameterFactory, ReviewFactory
from my_app.models import Parameter, Review


def test_soft_delete_inline_formset():
    """
    The models and forms used here are just examples showcasing how to use
    soft-delete in formsets
    """
    review = ReviewFactory()
    active_parameter = ParameterFactory(
        review=review,
        name="Active parameter",
    )
    parameter_to_modify = ParameterFactory(
        review=review,
        name="Parameter to modify",
        description="Original description",
    )
    deleted_parameter = ParameterFactory(
        review=review,
        name="Soft-deleted parameter",
    )
    deleted_parameter.soft_delete()

    FormSet = inlineformset_factory(
        Review,
        Parameter,
        formset=SoftDeleteInlineFormSet,
        fields="__all__",
        can_delete=True,
        extra=1,
    )

    formset = FormSet(instance=review)
    rendered_formset = formset.as_p()

    assert "Active parameter" in rendered_formset
    assert "Parameter to modify" in rendered_formset
    assert "Soft-deleted parameter" not in rendered_formset
    assert 'type="checkbox"' in rendered_formset
    assert f'name="{formset.prefix}-0-DELETE"' in rendered_formset

    data = QueryDict(mutable=True)
    data.update(
        {
            f"{formset.prefix}-TOTAL_FORMS": "3",
            f"{formset.prefix}-INITIAL_FORMS": "2",
            f"{formset.prefix}-MIN_NUM_FORMS": "0",
            f"{formset.prefix}-MAX_NUM_FORMS": "1000",
            f"{formset.prefix}-0-id": str(active_parameter.pk),
            f"{formset.prefix}-0-review": str(review.pk),
            f"{formset.prefix}-0-name": active_parameter.name,
            f"{formset.prefix}-0-description": active_parameter.description,
            f"{formset.prefix}-0-option_type": active_parameter.option_type,
            f"{formset.prefix}-0-units_and_reporting_instructions": (
                active_parameter.units_and_reporting_instructions
            ),
            f"{formset.prefix}-0-calculation_instructions": (
                active_parameter.calculation_instructions
            ),
            f"{formset.prefix}-0-DELETE": "on",
            f"{formset.prefix}-1-id": str(parameter_to_modify.pk),
            f"{formset.prefix}-1-review": str(review.pk),
            f"{formset.prefix}-1-name": "Modified parameter",
            f"{formset.prefix}-1-description": "Modified description",
            f"{formset.prefix}-1-option_type": parameter_to_modify.option_type,
            f"{formset.prefix}-1-units_and_reporting_instructions": (
                parameter_to_modify.units_and_reporting_instructions
            ),
            f"{formset.prefix}-1-calculation_instructions": (
                parameter_to_modify.calculation_instructions
            ),
            f"{formset.prefix}-2-review": str(review.pk),
            f"{formset.prefix}-2-name": "Created parameter",
            f"{formset.prefix}-2-description": "Created description",
            f"{formset.prefix}-2-option_type": Parameter.OptionType.SELECT,
            f"{formset.prefix}-2-units_and_reporting_instructions": "kg",
            f"{formset.prefix}-2-calculation_instructions": "Add the values",
        }
    )

    bound_formset = FormSet(data=data, instance=review)
    assert bound_formset.is_valid(), bound_formset.errors

    bound_formset.save()

    active_parameter.refresh_from_db()
    assert active_parameter.deletion_time is not None
    assert not Parameter.active_objects.filter(pk=active_parameter.pk).exists()
    assert Parameter.objects.filter(pk=active_parameter.pk).exists()

    parameter_to_modify.refresh_from_db()
    assert parameter_to_modify.name == "Modified parameter"
    assert parameter_to_modify.description == "Modified description"

    created_parameter = Parameter.active_objects.get(
        review=review,
        name="Created parameter",
    )
    assert created_parameter.description == "Created description"
    assert created_parameter.option_type == Parameter.OptionType.SELECT
    assert created_parameter.units_and_reporting_instructions == "kg"
    assert created_parameter.calculation_instructions == "Add the values"
