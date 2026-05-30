from datetime import date

from django.test import SimpleTestCase

from crm_app.esteira_posso_reagendar_service import (
    gerar_tres_datas_opcao,
    montar_botoes_sim_nao,
    parse_button_id_posso_reagendar,
    deve_tentar_posso_reagendar,
)


class ParseBotaoPossoReagendarTests(SimpleTestCase):
    def test_sim(self):
        r = parse_button_id_posso_reagendar('pr_100_sim')
        self.assertEqual(100, r['venda_id'])
        self.assertEqual('sim', r['acao'])

    def test_data(self):
        r = parse_button_id_posso_reagendar('pr_100_dt_20260615')
        self.assertEqual(date(2026, 6, 15), r['data'])

    def test_turno_tarde(self):
        r = parse_button_id_posso_reagendar('pr_50_tarde')
        self.assertEqual('TARDE', r['turno'])


class BotoesPossoReagendarTests(SimpleTestCase):
    def test_botoes_sim_nao(self):
        b = montar_botoes_sim_nao(42)
        self.assertEqual(2, len(b))
        self.assertEqual('pr_42_sim', b[0]['id'])

    def test_tres_datas(self):
        datas = gerar_tres_datas_opcao(a_partir_de=date(2026, 6, 1))
        self.assertEqual(3, len(datas))
        self.assertEqual(date(2026, 6, 1), datas[0])

    def test_deve_tentar_botao_pr(self):
        self.assertTrue(deve_tentar_posso_reagendar('', button_id='pr_100_sim'))
