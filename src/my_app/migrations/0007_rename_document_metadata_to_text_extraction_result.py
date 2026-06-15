import django.db.models.deletion
from django.db import migrations

from phac_aspc.django import fields

import proj.text


class Migration(migrations.Migration):

    dependencies = [
        ("my_app", "0006_documentfigure_documenttable_figureextractionresult"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="DocumentMetadata",
            new_name="TextExtractionResult",
        ),
        migrations.AlterField(
            model_name="textextractionresult",
            name="document",
            field=fields.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="text_extraction_result",
                to="my_app.document",
                verbose_name=proj.text.tdt("Document"),
            ),
        ),
    ]
