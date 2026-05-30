from django.test import SimpleTestCase

from crm_app.esteira_posso_antecipar_service import parse_resposta_posso_antecipar_vendedor


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
