from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0223_assertiva_nome_cache'),
    ]

    operations = [
        migrations.CreateModel(
            name='RepescagemBioPedidoPap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cpf', models.CharField(help_text='CPF só dígitos', max_length=14, unique=True)),
                ('data_pedido', models.DateTimeField(blank=True, null=True)),
                ('numero_pedido', models.CharField(blank=True, default='', max_length=40)),
                ('numero_os', models.CharField(blank=True, default='', max_length=40)),
                ('de_outro_pdv', models.BooleanField(blank=True, null=True)),
                ('sem_pedido', models.BooleanField(default=False)),
                ('fonte', models.CharField(blank=True, default='consulta_os_pap', max_length=32)),
                ('consultado_em', models.DateTimeField(auto_now=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Pedido PAP (Repescagem Bio)',
                'verbose_name_plural': 'Pedidos PAP (Repescagem Bio)',
                'db_table': 'crm_repescagem_bio_pedido_pap',
            },
        ),
    ]
