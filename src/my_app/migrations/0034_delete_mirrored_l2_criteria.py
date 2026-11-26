from django.db import migrations


def delete_mirrored_l2_criteria(apps, schema_editor):
    Question = apps.get_model("my_app", "L2ScreeningQuestion")
    Option = apps.get_model("my_app", "L2ScreeningQuestionOption")
    db_alias = schema_editor.connection.alias

    Question.objects.using(db_alias).filter(l1_question__isnull=False).delete()
    Option.objects.using(db_alias).filter(l1_option__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("my_app", "0033_bulkworkflowrequest_cancellation_generation_id_and_more"),
    ]

    operations = [migrations.RunPython(delete_mirrored_l2_criteria)]
