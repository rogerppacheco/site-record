from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0222_funil_template_envio'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssertivaNomeCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cpf', models.CharField(help_text='CPF/CNPJ só dígitos', max_length=14, unique=True)),
                ('nome', models.CharField(max_length=200)),
                ('fonte', models.CharField(blank=True, default='assertiva', max_length=32)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Cache nome Assertiva',
                'verbose_name_plural': 'Caches nome Assertiva',
                'db_table': 'crm_assertiva_nome_cache',
            },
        ),
    ]
