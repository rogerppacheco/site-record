from django.test import SimpleTestCase

from crm_app.esteira_posso_antecipar_service import (
    formatar_posso_antecipar_exibicao,
    montar_botoes_posso_antecipar,
    parse_button_id_posso_antecipar,
    parse_resposta_posso_antecipar_vendedor,
)


class _VendaStub:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FormatacaoExibicaoPossoAnteciparTests(SimpleTestCase):
    def test_sim_manha(self):
        v = _VendaStub(vendedor_pode_antecipar=True, vendedor_pode_antecipar_turno='MANHA')
        self.assertEqual(formatar_posso_antecipar_exibicao(v), 'Sim, Manhã')

    def test_aguardando(self):
        from django.utils import timezone
        v = _VendaStub(
            data_solicitacao_posso_antecipar=timezone.now(),
            data_resposta_posso_antecipar=None,
        )
        self.assertEqual(formatar_posso_antecipar_exibicao(v), 'Aguardando')


class BotaoPossoAnteciparTests(SimpleTestCase):
    def test_botoes_tres_opcoes_com_id_pedido(self):
        botoes = montar_botoes_posso_antecipar(6735)
        self.assertEqual(3, len(botoes))
        self.assertEqual('pa_6735_sim_manha', botoes[0]['id'])
        self.assertEqual('Sim, manhã', botoes[0]['label'])

    def test_parse_botao_sim_tarde(self):
        r = parse_button_id_posso_antecipar('pa_6735_sim_tarde')
        self.assertEqual(6735, r['venda_id'])
        self.assertTrue(r['pode'])
        self.assertEqual('TARDE', r['turno'])

    def test_parse_botao_nao(self):
        r = parse_button_id_posso_antecipar('pa_99_nao')
        self.assertEqual(99, r['venda_id'])
        self.assertFalse(r['pode'])


class ParseRespostaPossoAnteciparTests(SimpleTestCase):
    def test_sim_manha(self):
        r = parse_resposta_posso_antecipar_vendedor('Sim, manhã')
        self.assertTrue(r['pode'])
        self.assertEqual(r['turno'], 'MANHA')
        self.assertEqual(r['observacao'], '')

    def test_sim_tarde(self):
        r = parse_resposta_posso_antecipar_vendedor('Sim, tarde')
        self.assertTrue(r['pode'])
        self.assertEqual(r['turno'], 'TARDE')

    def test_nao(self):
        r = parse_resposta_posso_antecipar_vendedor('Não')
        self.assertFalse(r['pode'])
        self.assertIsNone(r['turno'])

    def test_nao_com_observacao(self):
        r = parse_resposta_posso_antecipar_vendedor('Não, cliente viaja amanhã')
        self.assertFalse(r['pode'])
        self.assertIn('cliente viaja', r['observacao'].lower())

    def test_sim_sem_turno_guarda_mensagem(self):
        r = parse_resposta_posso_antecipar_vendedor('Sim')
        self.assertTrue(r['pode'])
        self.assertIsNone(r['turno'])
        self.assertEqual(r['resposta_completa'], 'Sim')

    def test_texto_livre_sem_sim_nao(self):
        r = parse_resposta_posso_antecipar_vendedor('Talvez depois')
        self.assertIsNone(r['pode'])
        self.assertEqual(r['resposta_completa'], 'Talvez depois')
