from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0217_reagendar_cliente'),
    ]

    operations = [
        migrations.AddField(
            model_name='importacaoosab',
            name='nr_ordem_original',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
    ]
