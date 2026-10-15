import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0218_importacaoosab_nr_ordem_original'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ChurnConsultaDebitoLote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('EM_ANDAMENTO', 'Em andamento'), ('CONCLUIDO', 'Concluído'), ('CANCELADO', 'Cancelado'), ('ERRO', 'Erro')], db_index=True, default='EM_ANDAMENTO', max_length=16)),
                ('forcar', models.BooleanField(default=False)),
                ('total', models.PositiveIntegerField(default=0)),
                ('processados', models.PositiveIntegerField(default=0)),
                ('adimplentes', models.PositiveIntegerField(default=0)),
                ('inadimplentes', models.PositiveIntegerField(default=0)),
                ('a_vencer', models.PositiveIntegerField(default=0)),
                ('erros', models.PositiveIntegerField(default=0)),
                ('mensagem', models.TextField(blank=True, default='')),
                ('iniciado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('finalizado_em', models.DateTimeField(blank=True, null=True)),
                ('iniciado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='churn_consultas_debito', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Lote consulta débito Nio (churn)',
                'verbose_name_plural': 'Lotes consulta débito Nio (churn)',
                'db_table': 'crm_churn_consulta_debito_lote',
                'ordering': ['-iniciado_em'],
            },
        ),
        migrations.CreateModel(
            name='ChurnConsultaDebitoNio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cpf', models.CharField(max_length=14, unique=True)),
                ('situacao', models.CharField(choices=[('ADIMPLENTE', 'Adimplente'), ('INADIMPLENTE', 'Inadimplente'), ('A_VENCER', 'A vencer'), ('ERRO', 'Erro na consulta')], db_index=True, max_length=16)),
                ('qtd_vencidas', models.PositiveIntegerField(default=0)),
                ('valor_vencido', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('vencimento_mais_antigo', models.DateField(blank=True, null=True)),
                ('qtd_a_vencer', models.PositiveIntegerField(default=0)),
                ('valor_a_vencer', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('detalhe', models.CharField(blank=True, default='', max_length=255)),
                ('consultado_em', models.DateTimeField(db_index=True)),
                ('lote', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='resultados', to='crm_app.churnconsultadebitolote')),
            ],
            options={
                'verbose_name': 'Débito Nio (churn)',
                'verbose_name_plural': 'Débitos Nio (churn)',
                'db_table': 'crm_churn_consulta_debito_nio',
            },
        ),
    ]
