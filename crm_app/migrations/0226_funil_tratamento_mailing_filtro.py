from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0225_venda_permissoes_esteira_gestao_export'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='mailinglote',
            name='filtro_situacao',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.CreateModel(
            name='FunilTratamento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('aba', models.CharField(choices=[('INTERESSE', 'Interesse'), ('PRE_VENDA', 'Pré-venda'), ('VENDA', 'Venda'), ('CHURN', 'Repescar Churn'), ('BIO', 'Repescagem Bio'), ('MAILING', 'Mailing')], db_index=True, max_length=16)),
                ('ref_id', models.CharField(db_index=True, max_length=64)),
                ('protocolo', models.CharField(blank=True, default='', max_length=80)),
                ('nome', models.CharField(blank=True, default='', max_length=200)),
                ('documento', models.CharField(blank=True, default='', max_length=14)),
                ('telefone', models.CharField(blank=True, default='', max_length=20)),
                ('status', models.CharField(choices=[('ABERTO', 'Aberto'), ('TRATADO', 'Tratado')], db_index=True, default='TRATADO', max_length=16)),
                ('observacao', models.TextField(blank=True, default='')),
                ('tratado_em', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('tratado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='funil_tratamentos', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Tratamento do Funil',
                'verbose_name_plural': 'Tratamentos do Funil',
                'db_table': 'crm_funil_tratamento',
            },
        ),
        migrations.AddConstraint(
            model_name='funiltratamento',
            constraint=models.UniqueConstraint(fields=('aba', 'ref_id'), name='uniq_funil_tratamento_aba_ref'),
        ),
    ]
