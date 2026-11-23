from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0231_whatsapp_inbox_crm_kommo"),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppEtapaTrigger",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("etapa", models.CharField(db_index=True, max_length=16)),
                (
                    "acao",
                    models.CharField(
                        choices=[
                            ("PAUSAR_BOT", "Pausar bot / fila humana"),
                            ("DEVOLVER_BOT", "Devolver ao bot"),
                            ("TAG", "Aplicar tag"),
                            ("TAREFA", "Criar tarefa"),
                            ("TEMPLATE", "Enviar template Meta"),
                        ],
                        max_length=20,
                    ),
                ),
                ("ativo", models.BooleanField(default=True)),
                ("prioridade", models.PositiveSmallIntegerField(default=100)),
                ("tag_nome", models.CharField(blank=True, default="", max_length=40)),
                ("tag_cor", models.CharField(blank=True, default="#6c757d", max_length=16)),
                ("tarefa_titulo", models.CharField(blank=True, default="", max_length=200)),
                ("template_name", models.CharField(blank=True, default="", max_length=120)),
                ("template_params", models.JSONField(blank=True, default=list)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Trigger de etapa WhatsApp",
                "verbose_name_plural": "Triggers de etapa WhatsApp",
                "db_table": "crm_whatsapp_etapa_trigger",
                "ordering": ["etapa", "prioridade", "id"],
            },
        ),
    ]
