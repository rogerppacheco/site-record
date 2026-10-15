from datetime import date, datetime

from django.test import SimpleTestCase
from django.utils import timezone

from crm_app.services import repescagem_bio_service as svc


def _dt(texto):
    return timezone.make_aware(datetime.strptime(texto, '%d/%m/%Y %H:%M'))


class ClassificarResultadoTests(SimpleTestCase):
    def test_situacoes(self):
        casos = {
            'Doc. Apto para Venda': svc.APTO,
            'Doc. Não Apto para Venda': svc.RISCO,
            'Risco de Fraude': svc.RISCO,
            'Reprovado': svc.RISCO,
            'Não Passível de Análise': svc.RISCO,
            'Digitalizar Novamente': svc.REFAZER,
            'Documento Ilegível': svc.REFAZER,
            'Selfie Ausente': svc.REFAZER,
            'Link Enviado': svc.LINK_ENVIADO,
            'Concluído': svc.EM_ANALISE,
            '': svc.EM_ANALISE,
        }
        for resultado, esperado in casos.items():
            with self.subTest(resultado=resultado):
                self.assertEqual(svc.classificar_resultado(resultado), esperado)


class ConsolidarSituacaoTests(SimpleTestCase):
    def test_sem_etapas_e_sem_biometria(self):
        self.assertEqual(svc.consolidar_situacao([]), svc.SEM_BIOMETRIA)

    def test_alguma_etapa_apta_vence(self):
        etapas = [
            {'resultado_analise': 'Doc. Apto para Venda', 'data_envio': _dt('10/10/2026 10:00')},
            {'resultado_analise': 'Digitalizar Novamente', 'data_envio': _dt('12/10/2026 10:00')},
        ]
        self.assertEqual(svc.consolidar_situacao(etapas), svc.APTO)

    def test_sem_apto_vale_a_mais_recente(self):
        etapas = [
            {'resultado_analise': 'Link Enviado', 'data_envio': _dt('14/10/2026 09:00')},
            {'resultado_analise': 'Digitalizar Novamente', 'data_envio': _dt('13/10/2026 09:00')},
        ]
        self.assertEqual(svc.consolidar_situacao(etapas), svc.LINK_ENVIADO)


class ParseCsvTests(SimpleTestCase):
    CABECALHO = ('Protocolo;CPF/CNPJ;MSISDN;Data de Digitalização;Data de Envio;Data de Conferência;Código PDV;'
                 'Login Digitalização;Tipo de Serviço;Origem da Digitalização;Resultado da Análise;'
                 'Origem do Pedido de Venda;Selfie Capturada')

    def _csv(self, *linhas):
        return '\r\n'.join((self.CABECALHO,) + linhas).encode('cp1252')

    def test_converte_linhas(self):
        conteudo = self._csv(
            '123;992.669.116-15;31999990000;14/10/2026 10:00:00;14/10/2026 10:05:00;;PDV1;TT001;Fibra;PAP;'
            'Doc. Apto para Venda;Nio;Sim',
        )
        linhas = svc.parse_csv(conteudo)
        self.assertEqual(len(linhas), 1)
        item = linhas[0]
        self.assertEqual(item['cpf'], '99266911615')
        self.assertEqual(item['login_digitalizacao'], 'TT001')
        self.assertEqual(item['resultado_analise'], 'Doc. Apto para Venda')
        self.assertEqual(timezone.localtime(item['data_envio']).strftime('%d/%m/%Y %H:%M'), '14/10/2026 10:05')
        self.assertIsNone(item['data_conferencia'])

    def test_ignora_linha_sem_protocolo_cpf_ou_envio(self):
        conteudo = self._csv(
            ';99266911615;;;14/10/2026 10:05:00;;;;;;;;',
            '124;;;;14/10/2026 10:05:00;;;;;;;;',
            '125;99266911615;;;;;;;;;;;',
        )
        self.assertEqual(svc.parse_csv(conteudo), [])

    def test_vazio(self):
        self.assertEqual(svc.parse_csv(b''), [])

    def test_sem_colunas_obrigatorias(self):
        with self.assertRaises(ValueError):
            svc.parse_csv('Coluna;Outra\r\n1;2'.encode('cp1252'))


class DividirPeriodoTests(SimpleTestCase):
    def test_partes_de_15_dias(self):
        partes = svc.dividir_periodo(date(2026, 9, 1), date(2026, 10, 5))
        self.assertEqual(partes, [
            (date(2026, 9, 1), date(2026, 9, 15)),
            (date(2026, 9, 16), date(2026, 9, 30)),
            (date(2026, 10, 1), date(2026, 10, 5)),
        ])

    def test_um_dia(self):
        self.assertEqual(svc.dividir_periodo(date(2026, 10, 15), date(2026, 10, 15)),
                         [(date(2026, 10, 15), date(2026, 10, 15))])
