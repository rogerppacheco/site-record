from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0211_venda_codigo_sa_ba'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='desconto_recompra_aplicado_em',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name='Desconto Recompra aplicado em (AAAAMM)',
            ),
        ),
    ]
