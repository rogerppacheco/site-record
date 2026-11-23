from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crm_app", "0230_whatsapp_channel_conversation_eligibility"),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=40, unique=True)),
                ("cor", models.CharField(blank=True, default="#6c757d", max_length=16)),
                ("ativo", models.BooleanField(default=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Tag WhatsApp",
                "verbose_name_plural": "Tags WhatsApp",
                "db_table": "crm_whatsapp_tag",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="RespostaRapida",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("atalho", models.CharField(max_length=40, unique=True)),
                ("texto", models.TextField()),
                ("grupo", models.CharField(blank=True, default="", max_length=40)),
                ("ativo", models.BooleanField(default=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Resposta rápida WhatsApp",
                "verbose_name_plural": "Respostas rápidas WhatsApp",
                "db_table": "crm_whatsapp_resposta_rapida",
                "ordering": ["atalho"],
            },
        ),
        migrations.AddField(
            model_name="whatsappconversation",
            name="etapa_funil",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "—"),
                    ("INTERESSE", "Interesse"),
                    ("PRE_VENDA", "Pré-venda"),
                    ("VENDA", "Venda"),
                    ("CHURN", "Repescar Churn"),
                    ("BIO", "Repescagem Bio"),
                    ("MAILING", "Mailing"),
                    ("SUPORTE", "Suporte"),
                ],
                db_index=True,
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="whatsappconversation",
            name="encerrada_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="whatsappconversation",
            name="tags",
            field=models.ManyToManyField(blank=True, related_name="conversas", to="crm_app.whatsapptag"),
        ),
        migrations.CreateModel(
            name="ConversacaoNota",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("texto", models.TextField()),
                ("criado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "autor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notas_conversa_whatsapp",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "conversa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notas",
                        to="crm_app.whatsappconversation",
                    ),
                ),
            ],
            options={
                "verbose_name": "Nota de conversa WhatsApp",
                "verbose_name_plural": "Notas de conversa WhatsApp",
                "db_table": "crm_whatsapp_conversacao_nota",
                "ordering": ["-criado_em", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ConversacaoTarefa",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("titulo", models.CharField(max_length=200)),
                ("prazo", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDENTE", "Pendente"),
                            ("CONCLUIDA", "Concluída"),
                            ("CANCELADA", "Cancelada"),
                        ],
                        db_index=True,
                        default="PENDENTE",
                        max_length=16,
                    ),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("concluida_em", models.DateTimeField(blank=True, null=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "conversa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tarefas",
                        to="crm_app.whatsappconversation",
                    ),
                ),
                (
                    "criado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tarefas_criadas_conversa_whatsapp",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "dono",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tarefas_conversa_whatsapp",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Tarefa de conversa WhatsApp",
                "verbose_name_plural": "Tarefas de conversa WhatsApp",
                "db_table": "crm_whatsapp_conversacao_tarefa",
                "ordering": ["status", "prazo", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ConversacaoEvento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "tipo",
                    models.CharField(
                        choices=[
                            ("ASSUMIU", "Assumiu"),
                            ("TRANSFERIU", "Transferiu"),
                            ("LIBEROU", "Liberou"),
                            ("ENCERROU", "Encerrou"),
                            ("REABRIU", "Reabriu"),
                            ("ETAPA", "Etapa"),
                            ("TAG", "Tag"),
                            ("NOTA", "Nota"),
                            ("TAREFA", "Tarefa"),
                            ("NAO_PERTURBE", "Não perturbe"),
                            ("FUNIL", "Funil"),
                            ("SISTEMA", "Sistema"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("texto", models.CharField(blank=True, default="", max_length=500)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("criado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "autor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="eventos_conversa_whatsapp",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "conversa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="eventos",
                        to="crm_app.whatsappconversation",
                    ),
                ),
            ],
            options={
                "verbose_name": "Evento de conversa WhatsApp",
                "verbose_name_plural": "Eventos de conversa WhatsApp",
                "db_table": "crm_whatsapp_conversacao_evento",
                "ordering": ["-criado_em", "-id"],
            },
        ),
    ]
