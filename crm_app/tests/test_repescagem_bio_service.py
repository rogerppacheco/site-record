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


class VincularVendaTests(SimpleTestCase):
    COBERTURA = [(_dt('01/10/2026 00:00'), _dt('15/10/2026 17:00'))]

    def test_link_e_apto_antes_da_venda(self):
        etapas = [
            {'resultado_analise': 'Link Enviado', 'data_envio': _dt('15/10/2026 16:02')},
            {'resultado_analise': 'Doc. Apto para Venda', 'data_envio': _dt('15/10/2026 16:08')},
        ]
        r = svc.vincular_venda(etapas, _dt('15/10/2026 16:14'), self.COBERTURA)
        self.assertEqual(r['situacao'], svc.APTO)
        self.assertTrue(r['venda_vinculada'])
        self.assertEqual(r['vinculo'], 'apto 6 min antes da venda')

    def test_sem_envio_com_ged_buscado_e_sem_biometria(self):
        r = svc.vincular_venda([], _dt('15/10/2026 16:14'), self.COBERTURA)
        self.assertEqual(r['situacao'], svc.SEM_BIOMETRIA)

    def test_sem_envio_fora_da_cobertura_e_nao_verificado(self):
        self.assertEqual(svc.vincular_venda([], _dt('15/10/2026 18:00'), self.COBERTURA)['situacao'], svc.NAO_VERIFICADO)
        self.assertEqual(svc.vincular_venda([], _dt('15/10/2026 16:14'), [])['situacao'], svc.NAO_VERIFICADO)

    def test_bio_antiga_nao_vale_para_venda_nova(self):
        etapas = [{'resultado_analise': 'Doc. Apto para Venda', 'data_envio': _dt('01/08/2026 10:00')}]
        r = svc.vincular_venda(etapas, _dt('14/10/2026 10:00'), self.COBERTURA)
        self.assertEqual(r['situacao'], svc.SEM_BIOMETRIA)
        self.assertTrue(r['venda_vinculada'])

    def test_venda_antiga_nao_e_da_bio_nova(self):
        etapas = [{'resultado_analise': 'Doc. Apto para Venda', 'data_envio': _dt('14/10/2026 10:00')}]
        r = svc.vincular_venda(etapas, _dt('01/08/2026 10:00'), self.COBERTURA)
        self.assertEqual(r['situacao'], svc.APTO)
        self.assertFalse(r['venda_vinculada'])

    def test_link_depois_da_venda(self):
        etapas = [{'resultado_analise': 'Link Enviado', 'data_envio': _dt('15/10/2026 12:00')}]
        r = svc.vincular_venda(etapas, _dt('14/10/2026 10:00'), self.COBERTURA)
        self.assertEqual(r['situacao'], svc.LINK_ENVIADO)
        self.assertEqual(r['vinculo'], 'último envio 26 h depois da venda')


class AvaliarRepescagemTests(SimpleTestCase):
    AGORA = _dt('15/10/2026 16:00')

    def test_sem_registro_no_ged_nao_repesca(self):
        for situacao in (svc.SEM_BIOMETRIA, svc.NAO_VERIFICADO):
            with self.subTest(situacao=situacao):
                self.assertEqual(svc.avaliar_repescagem(situacao, _dt('10/10/2026 10:00'), agora=self.AGORA),
                                 (False, 'Sem registro no GED'))

    def test_risco_nao_repesca(self):
        self.assertEqual(svc.avaliar_repescagem(svc.RISCO, None, agora=self.AGORA), (False, 'Biometria reprovada/risco'))

    def test_sem_venda_repesca_qualquer_situacao_do_ged(self):
        for situacao, rotulo in ((svc.APTO, 'apto'), (svc.EM_ANALISE, 'em análise'),
                                 (svc.LINK_ENVIADO, 'link enviado'), (svc.REFAZER, 'refazer')):
            with self.subTest(situacao=situacao):
                self.assertEqual(svc.avaliar_repescagem(situacao, None, agora=self.AGORA),
                                 (True, f'Biometria sem venda no CRM ({rotulo})'))

    def test_venda_com_os_nao_repesca(self):
        self.assertEqual(svc.avaliar_repescagem(svc.LINK_ENVIADO, _dt('01/10/2026 10:00'), '11725616', agora=self.AGORA),
                         (False, 'Venda com O.S. 11725616'))

    def test_venda_sem_os_dentro_do_prazo_aguarda(self):
        self.assertEqual(svc.avaliar_repescagem(svc.APTO, _dt('14/10/2026 10:00'), '', agora=self.AGORA),
                         (False, 'Aguardando cadastro da O.S. (venda há 30h)'))

    def test_venda_sem_os_fora_do_prazo_repesca(self):
        self.assertEqual(svc.avaliar_repescagem(svc.APTO, _dt('12/10/2026 10:00'), '  ', 'CLIENTE DESISTIU', agora=self.AGORA),
                         (True, 'Venda sem O.S. há 3 dias · tratamento: CLIENTE DESISTIU'))
        self.assertEqual(svc.avaliar_repescagem(svc.LINK_ENVIADO, _dt('13/10/2026 15:00'), agora=self.AGORA),
                         (True, 'Venda sem O.S. há 2 dias'))

    def test_biometria_com_menos_de_48h_nao_repesca_mesmo_sem_venda(self):
        self.assertEqual(
            svc.avaliar_repescagem(svc.LINK_ENVIADO, None, agora=self.AGORA, ultimo_envio=_dt('15/10/2026 10:00')),
            (False, 'Aguardando 48h da biometria (enviada há 6h)'),
        )
        self.assertEqual(
            svc.avaliar_repescagem(svc.LINK_ENVIADO, _dt('12/10/2026 10:00'), agora=self.AGORA,
                                   ultimo_envio=_dt('14/10/2026 18:00')),
            (False, 'Aguardando 48h da biometria (enviada há 22h)'),
        )

    def test_biometria_com_mais_de_48h_sem_venda_repesca(self):
        repescavel, _ = svc.avaliar_repescagem(svc.LINK_ENVIADO, None, agora=self.AGORA,
                                               ultimo_envio=_dt('13/10/2026 10:00'))
        self.assertTrue(repescavel)

    def test_venda_com_os_tem_prioridade_no_motivo(self):
        self.assertEqual(
            svc.avaliar_repescagem(svc.APTO, _dt('15/10/2026 10:00'), '11726750', agora=self.AGORA,
                                   ultimo_envio=_dt('15/10/2026 09:00')),
            (False, 'Venda com O.S. 11726750'),
        )

    def test_consta_pedido_com_menos_de_30_dias_no_pap_nao_repesca(self):
        # Caso Vieira: biometria apta, sem O.S., CONSTA PEDIDO, pedido PAP há 7 dias.
        self.assertEqual(
            svc.avaliar_repescagem(
                svc.APTO, _dt('08/10/2026 15:13'), '', 'CONSTA PEDIDO', agora=self.AGORA,
                ultimo_envio=_dt('08/10/2026 15:13'),
                info_pedido_pap={
                    'consultado': True, 'data_criacao': _dt('08/10/2026 12:08'),
                    'de_outro_pdv': True, 'sem_pedido': False,
                },
            ),
            (False, 'CONSTA PEDIDO: pedido no PAP há 7 dias (aguarda 30 dias)'),
        )

    def test_consta_pedido_sem_consulta_aguarda_pap(self):
        self.assertEqual(
            svc.avaliar_repescagem(
                svc.APTO, _dt('13/10/2026 16:20'), '', 'CONSTA PEDIDO', agora=self.AGORA,
                ultimo_envio=_dt('13/10/2026 10:00'),
                info_pedido_pap={'consultado': False, 'em_andamento': True},
            ),
            (False, 'CONSTA PEDIDO: consultando pedido no PAP…'),
        )

    def test_consta_pedido_sem_pedido_no_pap(self):
        self.assertEqual(
            svc.avaliar_repescagem(
                svc.APTO, _dt('13/10/2026 16:20'), '', 'CONSTA PEDIDO', agora=self.AGORA,
                ultimo_envio=_dt('13/10/2026 10:00'),
                info_pedido_pap={'consultado': True, 'sem_pedido': True, 'data_criacao': None},
            ),
            (False, 'CONSTA PEDIDO: nenhum pedido encontrado no PAP'),
        )

    def test_consta_pedido_com_mais_de_30_dias_pode_repescar(self):
        repescavel, motivo = svc.avaliar_repescagem(
            svc.APTO, _dt('01/09/2026 10:00'), '', 'CONSTA PEDIDO', agora=self.AGORA,
            ultimo_envio=_dt('01/09/2026 10:00'),
            info_pedido_pap={
                'consultado': True, 'data_criacao': _dt('01/09/2026 10:00'),
                'de_outro_pdv': True, 'sem_pedido': False,
            },
        )
        self.assertTrue(repescavel)
        self.assertIn('CONSTA PEDIDO', motivo)

    def test_texto_dias(self):
        self.assertEqual(svc._texto_dias(1), '1 dia')
        self.assertEqual(svc._texto_dias(7), '7 dias')


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
