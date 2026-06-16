"""Testes do relatório diário de esteira enviado ao GC."""
from datetime import datetime, time
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from crm_app.models import AnteciparInstalacaoConfig, Cliente, StatusCRM, Venda
from crm_app.services.relatorio_esteira_gc_service import (
    calcular_metricas,
    contar_ativados,
    contagem_esteira_auditoria,
    montar_mensagem_relatorio_esteira_gc,
    processar_envio_relatorio_esteira_gc,
)
from usuarios.models import Usuario


class RelatorioEsteiraGcServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.st_sem = StatusCRM.objects.create(nome='SEM TRATAMENTO', tipo='Tratamento', estado='ABERTO')
        cls.st_pend = StatusCRM.objects.create(nome='PENDENTE VENDEDOR', tipo='Tratamento', estado='ABERTO')
        cls.st_bio = StatusCRM.objects.create(nome='FALTA BIOMETRIA', tipo='Tratamento', estado='ABERTO')
        cls.st_cad = StatusCRM.objects.create(nome='CADASTRADA', tipo='Tratamento', estado='FECHADO')
        cls.st_agend = StatusCRM.objects.create(nome='AGENDADO', tipo='Esteira', estado='ABERTO')
        cls.st_fechado = StatusCRM.objects.create(nome='CANCELADA', tipo='Tratamento', estado='FECHADO')
        cls.vendedor = Usuario.objects.create_user(
            username='vend_rel',
            password='x',
            first_name='Vendedor',
        )
        cls.cliente = Cliente.objects.create(
            nome_razao_social='Cliente Rel',
            cpf_cnpj='11122233344',
        )
        cls.config = AnteciparInstalacaoConfig.objects.create(
            nome_gc='Marcella Silva',
            telefone_gc='21999998888',
            relatorio_esteira_gc_ativo=True,
            relatorio_esteira_horario_1=time(17, 20),
            relatorio_esteira_horario_2=time(18, 0),
        )

    def _criar_venda(self, **kwargs):
        defaults = {
            'vendedor': self.vendedor,
            'cliente': self.cliente,
            'ordem_servico': 'OS123456',
            'ativo': True,
        }
        defaults.update(kwargs)
        return Venda.objects.create(**defaults)

    def test_contar_ativados_apenas_cadastrada_com_os_no_dia(self):
        hoje = timezone.localdate()
        ontem = hoje - timezone.timedelta(days=1)

        self._criar_venda(
            status_tratamento=self.st_cad,
            data_abertura=timezone.make_aware(datetime.combine(hoje, time(10, 0))),
        )
        self._criar_venda(
            status_tratamento=self.st_cad,
            data_abertura=timezone.make_aware(datetime.combine(ontem, time(10, 0))),
        )
        self._criar_venda(
            status_tratamento=self.st_sem,
            data_abertura=timezone.make_aware(datetime.combine(hoje, time(11, 0))),
        )

        self.assertEqual(contar_ativados(hoje), 1)

    def test_contagem_esteira_auditoria_por_status_do_dia(self):
        hoje = timezone.localdate()
        ontem = hoje - timezone.timedelta(days=1)
        agora = timezone.now()

        self._criar_venda(status_tratamento=self.st_sem, data_criacao=agora)
        self._criar_venda(status_tratamento=self.st_sem, data_criacao=agora)
        self._criar_venda(status_tratamento=self.st_pend, data_criacao=agora)
        self._criar_venda(status_tratamento=self.st_bio, data_criacao=agora)
        self._criar_venda(
            status_tratamento=self.st_cad,
            status_esteira=self.st_agend,
            data_criacao=agora,
        )
        self._criar_venda(
            status_tratamento=self.st_fechado,
            data_criacao=agora,
        )
        v_ontem = self._criar_venda(status_tratamento=self.st_sem)
        Venda.objects.filter(pk=v_ontem.pk).update(
            data_criacao=timezone.make_aware(datetime.combine(ontem, time(9, 0)))
        )

        esteira = contagem_esteira_auditoria(hoje)
        por_status = {item['status']: item['qtd'] for item in esteira}
        self.assertEqual(por_status.get('SEM TRATAMENTO'), 2)
        self.assertEqual(por_status.get('PENDENTE VENDEDOR'), 1)
        self.assertEqual(por_status.get('FALTA BIOMETRIA'), 1)
        self.assertNotIn('CANCELADA', por_status)

    def test_mensagem_sem_caixa_alta(self):
        hoje = timezone.localdate()
        metricas = {
            'ativados': 3,
            'esteira': [
                {'status': 'SEM TRATAMENTO', 'qtd': 2},
                {'status': 'FALTA BIOMETRIA', 'qtd': 1},
            ],
        }
        agora = timezone.make_aware(datetime.combine(hoje, time(17, 25)))
        msg = montar_mensagem_relatorio_esteira_gc(
            self.config,
            metricas,
            slot='17:20',
            agora=agora,
        )
        self.assertIn('Marcella, boa tarde', msg)
        self.assertIn('Segue resultado e esteira de vendas:', msg)
        self.assertIn('Ativados: 3', msg)
        self.assertIn('Sem Tratamento: 2', msg)
        self.assertIn('Falta Biometria: 1', msg)
        self.assertNotIn('SEM TRATAMENTO', msg)
        self.assertNotIn('FALTA BIOMETRIA', msg)

    def test_mensagem_atualizacao_segundo_horario(self):
        hoje = timezone.localdate()
        metricas = calcular_metricas(hoje)
        agora = timezone.make_aware(datetime.combine(hoje, time(18, 2)))
        msg = montar_mensagem_relatorio_esteira_gc(
            self.config,
            metricas,
            slot='18:00',
            agora=agora,
        )
        self.assertIn('Atualização 18:00', msg)

    @patch('crm_app.services.relatorio_esteira_gc_service.WhatsAppService')
    def test_processar_envio_respeita_toggle_e_slot(self, mock_svc_cls):
        mock_svc = mock_svc_cls.return_value
        mock_svc.enviar_mensagem_texto.return_value = (True, 'ok')

        hoje = timezone.localdate()
        agora = timezone.make_aware(datetime.combine(hoje, time(17, 22)))
        if agora.weekday() > 4:
            self.skipTest('Teste de slot seg-sex')

        with patch('crm_app.services.relatorio_esteira_gc_service.timezone.localtime', return_value=agora):
            processar_envio_relatorio_esteira_gc()

        mock_svc.enviar_mensagem_texto.assert_called_once()
        self.config.refresh_from_db()
        controle = self.config.relatorio_esteira_controle_disparos
        self.assertEqual(controle.get('date'), hoje.isoformat())
        self.assertIn('17:20', controle.get('slots', []))

        mock_svc.enviar_mensagem_texto.reset_mock()
        with patch('crm_app.services.relatorio_esteira_gc_service.timezone.localtime', return_value=agora):
            processar_envio_relatorio_esteira_gc()
        mock_svc.enviar_mensagem_texto.assert_not_called()

    def test_processar_nao_envia_quando_inativo(self):
        self.config.relatorio_esteira_gc_ativo = False
        self.config.save(update_fields=['relatorio_esteira_gc_ativo'])
        hoje = timezone.localdate()
        agora = timezone.make_aware(datetime.combine(hoje, time(17, 22)))
        if agora.weekday() > 4:
            self.skipTest('Teste de slot seg-sex')

        with patch('crm_app.services.relatorio_esteira_gc_service.WhatsAppService') as mock_svc_cls:
            with patch('crm_app.services.relatorio_esteira_gc_service.timezone.localtime', return_value=agora):
                processar_envio_relatorio_esteira_gc()
            mock_svc_cls.return_value.enviar_mensagem_texto.assert_not_called()
