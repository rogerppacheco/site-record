from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0235_whatsapp_conv_canal_list_idx'),
    ]

    operations = [
        migrations.AlterField(
            model_name='funiltemplateenvio',
            name='aba',
            field=models.CharField(
                choices=[
                    ('INTERESSE', 'Interesse'),
                    ('CHURN', 'Repescar Churn'),
                    ('BIO', 'Repescagem Bio'),
                    ('MAILING', 'Mailing'),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name='configdisparofunil',
            name='aba',
            field=models.CharField(
                choices=[
                    ('INTERESSE', 'Interesse'),
                    ('CHURN', 'Repescar Churn'),
                    ('BIO', 'Repescagem Bio'),
                    ('MAILING', 'Mailing'),
                ],
                db_index=True,
                max_length=16,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name='funildisparolote',
            name='aba',
            field=models.CharField(
                choices=[
                    ('INTERESSE', 'Interesse'),
                    ('CHURN', 'Repescar Churn'),
                    ('BIO', 'Repescagem Bio'),
                    ('MAILING', 'Mailing'),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
    ]
