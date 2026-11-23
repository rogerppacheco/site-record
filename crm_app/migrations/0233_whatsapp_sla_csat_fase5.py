from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0232_whatsapp_etapa_trigger_fase3"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversation",
            name="primeira_resposta_humana_em",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Momento da 1ª mensagem de saída de um operador humano.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="whatsappconversation",
            name="csat_nota",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="whatsappconversation",
            name="csat_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
