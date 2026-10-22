from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0224_repescagem_bio_pedido_pap'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='venda',
            options={
                'permissions': [
                    ('pode_reverter_status', 'Pode reverter o status'),
                    ('can_view_auditoria', 'Pode visualizar auditoria'),
                    ('can_view_esteira', 'Pode visualizar esteira'),
                    ('can_view_comissao_dashboard', 'Pode visualizar card de comissão'),
                    ('can_view_gestao_esteira', 'Pode visualizar gestão da esteira'),
                    ('can_export_agendados_pendentes_esteira', 'Pode exportar Agendados e Pendentes da esteira'),
                ],
                'verbose_name': 'Venda',
                'verbose_name_plural': 'Vendas',
            },
        ),
    ]
