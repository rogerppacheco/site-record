from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0227_venda_permissao_funil_vendas'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfigIsencaoBoletoVolume',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ativo', models.BooleanField(
                    default=True,
                    help_text='Se ativo, vendedores com instaladas do mês ≥ limiar não sofrem desconto de boleto no líquido.',
                    verbose_name='Isentar boleto por volume?',
                )),
                ('min_vendas_instaladas', models.PositiveIntegerField(
                    default=30,
                    help_text='Quantidade mínima de vendas instaladas no mês para zerar o desconto de boleto (≥).',
                    verbose_name='A partir de quantas vendas instaladas',
                )),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('atualizado_por', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Config. Isenção Boleto por Volume',
                'verbose_name_plural': 'Config. Isenção Boleto por Volume',
                'db_table': 'crm_config_isencao_boleto_volume',
            },
        ),
    ]
