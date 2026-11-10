from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0228_config_isencao_boleto_volume'),
    ]

    operations = [
        migrations.AddField(
            model_name='importacaochurn',
            name='data_importacao',
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text='Quando o registro entrou/foi importado nesta esteira do Funil.',
                null=True,
                verbose_name='Data Carga',
            ),
        ),
        migrations.CreateModel(
            name='ConfigDisparoFunil',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('aba', models.CharField(choices=[('INTERESSE', 'Interesse'), ('CHURN', 'Repescar Churn'), ('BIO', 'Repescagem Bio')], db_index=True, max_length=16, unique=True)),
                ('ativo', models.BooleanField(default=False)),
                ('hora_inicio', models.TimeField(default='09:00')),
                ('hora_fim', models.TimeField(default='18:00')),
                ('qtd_diaria', models.PositiveIntegerField(default=200, help_text='Máximo de envios bem-sucedidos por dia nesta aba.')),
                ('limite_por_ciclo', models.PositiveIntegerField(default=40, help_text='Máximo processado por ciclo do scheduler.')),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('atualizado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='configs_disparo_funil', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Config. disparo Funil',
                'verbose_name_plural': 'Configs. disparo Funil',
                'db_table': 'crm_config_disparo_funil',
            },
        ),
        migrations.CreateModel(
            name='FunilDisparoLote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('aba', models.CharField(choices=[('INTERESSE', 'Interesse'), ('CHURN', 'Repescar Churn'), ('BIO', 'Repescagem Bio')], db_index=True, max_length=16)),
                ('modo', models.CharField(choices=[('IDS', 'Selecionados'), ('FILTROS', 'Filtrados'), ('AUTO', 'Automático')], default='IDS', max_length=16)),
                ('status', models.CharField(choices=[('PENDENTE', 'Pendente'), ('DISPARANDO', 'Disparando'), ('PAUSADO', 'Pausado'), ('CONCLUIDO', 'Concluído'), ('CANCELADO', 'Cancelado')], db_index=True, default='PENDENTE', max_length=16)),
                ('ref_ids', models.JSONField(blank=True, default=list, help_text='IDs/refs selecionados (modo IDS).')),
                ('filtros', models.JSONField(blank=True, default=dict, help_text='Snapshot dos filtros da aba (modo FILTROS/AUTO).')),
                ('total', models.PositiveIntegerField(default=0)),
                ('enviados', models.PositiveIntegerField(default=0)),
                ('falhas', models.PositiveIntegerField(default=0)),
                ('pulados', models.PositiveIntegerField(default=0)),
                ('cursor', models.PositiveIntegerField(default=0, help_text='Índice já processado na fila de refs.')),
                ('mensagem', models.CharField(blank=True, default='', max_length=255)),
                ('criado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('iniciado_em', models.DateTimeField(blank=True, null=True)),
                ('finalizado_em', models.DateTimeField(blank=True, null=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('criado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='funil_disparo_lotes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Lote de disparo Funil',
                'verbose_name_plural': 'Lotes de disparo Funil',
                'db_table': 'crm_funil_disparo_lote',
                'ordering': ['-criado_em'],
            },
        ),
        migrations.AddIndex(
            model_name='funildisparolote',
            index=models.Index(fields=['status', 'aba'], name='crm_funil_d_status_aba_idx'),
        ),
    ]
