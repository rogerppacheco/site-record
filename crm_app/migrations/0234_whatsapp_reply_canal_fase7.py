from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0233_whatsapp_sla_csat_fase5"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconversation",
            name="reply_canal",
            field=models.CharField(
                choices=[("cliente", "Inbox (#194)"), ("funil", "Funil (#247)")],
                db_index=True,
                default="cliente",
                help_text="Purpose de envio do próximo reply humano (cliente=#194, funil=#247).",
                max_length=16,
            ),
        ),
    ]
