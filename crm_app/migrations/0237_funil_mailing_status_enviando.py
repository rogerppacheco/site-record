from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0236_funil_template_envio_aba_mailing'),
    ]

    operations = [
        migrations.AlterField(
            model_name='funiltemplateenvio',
            name='status_entrega',
            field=models.CharField(
                blank=True,
                choices=[
                    ('ENVIANDO', 'Enviando'),
                    ('ACEITO', 'Aceito pela API'),
                    ('ENVIADO', 'Enviado'),
                    ('ENTREGUE', 'Entregue'),
                    ('LIDO', 'Lido'),
                    ('FALHOU', 'Falhou'),
                ],
                default='',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='mailingcontato',
            name='status',
            field=models.CharField(
                choices=[
                    ('NOVO', 'Novo'),
                    ('ENVIANDO', 'Enviando'),
                    ('ENVIADO', 'Enviado'),
                    ('FALHOU', 'Falhou'),
                    ('RESPONDEU', 'Respondeu'),
                    ('TRATADO', 'Tratado'),
                    ('IGNORADO', 'Ignorado'),
                ],
                db_index=True,
                default='NOVO',
                max_length=16,
            ),
        ),
    ]
