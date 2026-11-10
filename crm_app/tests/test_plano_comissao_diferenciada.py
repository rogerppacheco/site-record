from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from crm_app.comissao_folha_service import (
    _banda_legado_comissao,
    chave_agrupamento_folha,
    chave_linha_folha,
    estimar_comissao_instaladas_vendedor,
    label_linha_folha,
    label_plano_folha,
    plano_tipo_to_chave,
    resolver_valor_comissao_venda,
)
from crm_app.services.comissao_matriz_service import _legacy_valores_faixa_banda


class ComissaoMatrizPlanoTest(SimpleTestCase):
    def test_resolver_usa_matriz_faixa_plano(self) -> None:
        plano = MagicMock()
        plano.id = 99
        faixa = MagicMock()

        with patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=150.0):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='1GB_PAP',
            )
        self.assertEqual(valor, 150.0)

    def test_resolver_fallback_faixa_legada(self) -> None:
        plano = MagicMock()
        faixa = MagicMock(valor_1gb_pap=Decimal('220.00'))

        with patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=None):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='1GB_PAP',
            )
        self.assertEqual(valor, 220.0)

    def test_banda_transicao_600_800(self) -> None:
        self.assertEqual(_banda_legado_comissao('600MB'), '500MB')
        self.assertEqual(_banda_legado_comissao('800MB'), '700MB')
        self.assertEqual(_banda_legado_comissao('500MB'), '500MB')

    def test_chave_excel_planos_transicao(self) -> None:
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA ESSENCIAL 600MB', 'CPF'), '600MB_PAP')
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA SUPER 800MB', 'CNPJ'), '700MB_CNPJ')
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA 500MB', 'CPF'), '500MB_PAP')

    def test_chave_600_cidade_especial(self) -> None:
        venda = MagicMock(cidade='CAMPINAS', estado='SP')
        with patch(
            'crm_app.services.comissao_cidade_especial_service.venda_em_cidade_oferta_especial',
            return_value=True,
        ):
            self.assertEqual(
                plano_tipo_to_chave(
                    'NIO FIBRA ESSENCIAL 600MB',
                    'CPF',
                    venda=venda,
                    cidades_especiais_cache={('SP', 'CAMPINAS')},
                ),
                '600MB_ESP_PAP',
            )
        with patch(
            'crm_app.services.comissao_cidade_especial_service.venda_em_cidade_oferta_especial',
            return_value=False,
        ):
            self.assertEqual(
                plano_tipo_to_chave(
                    'NIO FIBRA ESSENCIAL 600MB',
                    'CPF',
                    venda=venda,
                    cidades_especiais_cache=set(),
                ),
                '600MB_PAP',
            )

    def _venda_em(self, dia: date):
        return SimpleNamespace(
            data_instalacao=dia,
            data_instalacao_fisica=None,
            data_folha_comissao=None,
            data_pedido=None,
            data_criacao=None,
            cidade='SAO PAULO',
            estado='SP',
        )

    def test_600_setembro_continua_na_linha_600(self) -> None:
        venda = self._venda_em(date(2026, 9, 20))
        with patch(
            'crm_app.services.comissao_cidade_especial_service.venda_em_cidade_oferta_especial',
            return_value=False,
        ):
            self.assertEqual(
                plano_tipo_to_chave('NIO FIBRA ESSENCIAL 600MB', 'CPF', venda=venda),
                '600MB_PAP',
            )

    def test_600_outubro_mantem_linha_propria(self) -> None:
        venda = self._venda_em(date(2026, 10, 1))
        with patch(
            'crm_app.services.comissao_cidade_especial_service.venda_em_cidade_oferta_especial',
            return_value=False,
        ):
            self.assertEqual(
                plano_tipo_to_chave('NIO FIBRA ESSENCIAL 600MB', 'CPF', venda=venda),
                '600MB_PAP',
            )

    def test_setembro_ignora_celula_zerada_do_plano_600(self) -> None:
        plano = MagicMock(id=6, nome='NIO FIBRA ESSENCIAL 600MB')
        venda = self._venda_em(date(2026, 9, 18))
        config = MagicMock(valor_500mb_pap_manual=Decimal('180.00'))
        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=None,
            ),
            patch(
                'crm_app.services.comissao_matriz_service.get_valor_manual_vendedor_plano',
                return_value=None,
            ),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=None,
                config=config,
                usar_manual=True,
                chave='600MB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 180.0)

    def test_setembro_1gb_usa_celula_do_plano_e_nao_a_coluna_antiga(self) -> None:
        plano = MagicMock(id=5, nome='NIO FIBRA ULTRA 1GB (SEM MESH)')
        venda = self._venda_em(date(2026, 9, 18))
        faixa = MagicMock(valor_1gb_pap=Decimal('150'))
        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=None,
            ),
            patch(
                'crm_app.services.comissao_matriz_service.get_valor_faixa_plano',
                return_value=260.0,
            ),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='1GB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 260.0)

    def test_setembro_celula_zerada_cai_na_coluna_500(self) -> None:
        plano = MagicMock(id=6, nome='NIO FIBRA ESSENCIAL 600MB')
        venda = self._venda_em(date(2026, 9, 18))
        faixa = MagicMock(valor_500mb_pap=Decimal('180'))
        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=None,
            ),
            patch(
                'crm_app.services.comissao_matriz_service.get_valor_faixa_plano',
                return_value=0.0,
            ),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='600MB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 180.0)

    def test_setembro_separa_os_dois_planos_de_1gb(self) -> None:
        sem_mesh = SimpleNamespace(id=5, nome='NIO FIBRA ULTRA 1GB (SEM MESH)')
        ultra = SimpleNamespace(id=3, nome='NIO FIBRA ULTRA 1GB')
        venda_sem = self._venda_em(date(2026, 9, 10))
        venda_sem.plano = sem_mesh
        venda_sem.plano_id = 5
        venda_ultra = self._venda_em(date(2026, 9, 10))
        venda_ultra.plano = ultra
        venda_ultra.plano_id = 3

        chave_sem = chave_linha_folha(venda_sem, 'CPF')
        chave_ultra = chave_linha_folha(venda_ultra, 'CPF')
        self.assertEqual(chave_sem, 'plano_5_PAP')
        self.assertEqual(chave_ultra, 'plano_3_PAP')
        self.assertEqual(
            label_linha_folha(chave_sem, venda_sem, 'CPF'),
            'NIO FIBRA ULTRA 1GB (SEM MESH) PAP',
        )
        self.assertEqual(label_linha_folha(chave_ultra, venda_ultra, 'CPF'), 'NIO FIBRA ULTRA 1GB PAP')

    def test_outubro_mantem_a_grade_1gb(self) -> None:
        plano = SimpleNamespace(id=5, nome='NIO FIBRA ULTRA 1GB (SEM MESH)')
        venda = self._venda_em(date(2026, 10, 2))
        venda.plano = plano
        venda.plano_id = 5
        self.assertEqual(chave_linha_folha(venda, 'CPF'), '1GB_PAP')

    def test_setembro_cidade_especial_fica_em_linha_propria(self) -> None:
        plano = SimpleNamespace(id=6, nome='NIO FIBRA ESSENCIAL 600MB')
        venda = self._venda_em(date(2026, 9, 10))
        venda.plano = plano
        venda.plano_id = 6
        with patch(
            'crm_app.services.comissao_cidade_especial_service.venda_em_cidade_oferta_especial',
            return_value=True,
        ):
            chave = chave_linha_folha(venda, 'CPF')
        self.assertEqual(chave, 'plano_6_ESP_PAP')
        self.assertEqual(
            label_linha_folha(chave, venda, 'CPF'),
            'NIO FIBRA ESSENCIAL 600MB Cidade Especial PAP',
        )

    def test_chave_legado_lookup_600(self) -> None:
        from crm_app.comissao_folha_service import chave_legado_lookup

        self.assertEqual(chave_legado_lookup('600MB_PAP'), '500MB_PAP')
        self.assertEqual(chave_legado_lookup('600MB_ESP_CNPJ'), '500MB_CNPJ')
        self.assertEqual(chave_legado_lookup('1GB_PAP'), '1GB_PAP')

    def test_legacy_faixa_herda_valores_600_e_800(self) -> None:
        faixa = MagicMock(
            valor_500mb_pap=Decimal('150'),
            valor_500mb_cnpj=Decimal('250'),
            valor_700mb_pap=Decimal('190'),
            valor_700mb_cnpj=Decimal('280'),
            valor_1gb_pap=Decimal('220'),
            valor_1gb_cnpj=Decimal('300'),
        )
        self.assertEqual(
            _legacy_valores_faixa_banda(faixa, '600MB'),
            (Decimal('150'), Decimal('250')),
        )
        self.assertEqual(
            _legacy_valores_faixa_banda(faixa, '800MB'),
            (Decimal('190'), Decimal('280')),
        )

    def test_resolver_cidade_especial_tem_prioridade(self) -> None:
        plano = MagicMock()
        plano.id = 6
        faixa = MagicMock()
        venda = MagicMock(cidade='CAMPINAS', estado='SP')

        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=105.0,
            ),
            patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=180.0),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='500MB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 105.0)

    def test_resolver_sem_cidade_especial_usa_matriz(self) -> None:
        plano = MagicMock()
        faixa = MagicMock()
        venda = MagicMock(cidade='SAO PAULO', estado='SP')

        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=None,
            ),
            patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=180.0),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='500MB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 180.0)

    def test_estimar_comissao_inclui_plano_sem_regra_legado(self) -> None:
        vendedor = MagicMock(id=1)
        plano_600 = MagicMock(id=6, nome='NIO FIBRA ESSENCIAL 600MB')
        venda = MagicMock(plano=plano_600, plano_id=6, cidade='SAO PAULO', estado='SP')
        faixa = MagicMock(id=10, min_vendas=1, max_vendas=20, perfil='Vendedor')
        ctx = {
            'configs': {},
            'regras_perfil': [faixa],
            'regras_vendedor': {},
        }

        with (
            patch(
                'crm_app.performance_helpers.perfil_comissao_do_consultor',
                return_value='Vendedor',
            ),
            patch(
                'crm_app.services.cnpj_mei_service.tipo_cliente_comissao',
                return_value='CPF',
            ),
            patch(
                'crm_app.services.comissao_cidade_especial_service.carregar_cidades_oferta_especial',
                return_value=set(),
            ),
            patch(
                'crm_app.services.comissao_matriz_service.get_valor_faixa_plano',
                return_value=150.0,
            ),
        ):
            total = estimar_comissao_instaladas_vendedor(
                vendedor,
                [venda],
                ctx_faixas=ctx,
                matriz_cache=None,
            )

        self.assertEqual(total, 150.0)


class ComissaoCidadeEspecialServiceTest(SimpleTestCase):
    def test_cidade_em_oferta_com_cache(self) -> None:
        from crm_app.services.comissao_cidade_especial_service import cidade_em_oferta_especial

        cache = {('SP', 'CAMPINAS'), ('PR', 'LONDRINA')}
        self.assertTrue(cidade_em_oferta_especial('Campinas', 'sp', cache=cache))
        self.assertTrue(cidade_em_oferta_especial('LONDRINA', 'PR', cache=cache))
        self.assertFalse(cidade_em_oferta_especial('São Paulo', 'SP', cache=cache))

    def test_get_valor_so_com_flag_true(self) -> None:
        from crm_app.services.comissao_cidade_especial_service import (
            get_valor_comissao_cidade_especial,
        )

        plano = MagicMock()
        vc = MagicMock()
        vc.usa_comissao_cidade_especial = True
        vc.valor_pap_cidade_especial = Decimal('105.00')
        vc.valor_cnpj_cidade_especial = Decimal('105.00')
        plano.valores_comissao = vc

        self.assertEqual(get_valor_comissao_cidade_especial(plano, 'CPF'), 105.0)

        vc.usa_comissao_cidade_especial = False
        self.assertIsNone(get_valor_comissao_cidade_especial(plano, 'CPF'))

    def test_lista_canonica_tem_161_cidades(self) -> None:
        from crm_app.cidades_oferta_especial_data import CIDADES_OFERTA_ESPECIAL

        self.assertEqual(len(CIDADES_OFERTA_ESPECIAL), 161)
        self.assertIn(('SP', 'CAMPINAS'), CIDADES_OFERTA_ESPECIAL)
        self.assertIn(('PR', 'LONDRINA'), CIDADES_OFERTA_ESPECIAL)

class AgrupamentoPlanoCadastradoTest(SimpleTestCase):
    def test_plano_fora_da_grade_excel_ainda_agrupa(self) -> None:
        plano = MagicMock()
        plano.id = 18
        plano.nome = 'BLINK 300MB'
        venda = MagicMock(plano=plano, plano_id=18)
        self.assertIsNone(plano_tipo_to_chave('BLINK 300MB', 'CPF'))
        self.assertEqual(chave_agrupamento_folha(venda, 'CPF'), 'plano_18_PAP')
        self.assertEqual(label_plano_folha(venda, 'CPF'), 'BLINK 300MB PAP')

    def test_venda_sem_plano_aparece_como_sem_plano(self) -> None:
        venda = MagicMock(plano=None, plano_id=None)
        self.assertEqual(chave_agrupamento_folha(venda, 'CPF'), 'sem_plano_PAP')
        self.assertEqual(label_plano_folha(venda, 'CPF'), 'SEM PLANO PAP')

    def test_resolver_paga_plano_pela_matriz_sem_chave_excel(self) -> None:
        plano = MagicMock()
        plano.id = 6
        faixa = MagicMock()
        with patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=45.0):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave=None,
            )
        self.assertEqual(valor, 45.0)

    def test_outubro_manual_600mb_cai_na_coluna_500mb_quando_sem_celula(self) -> None:
        plano = MagicMock(id=24, nome='NIO FIBRA 600MB')
        venda = SimpleNamespace(
            data_instalacao=date(2026, 10, 15),
            data_instalacao_fisica=None,
            data_folha_comissao=None,
            data_pedido=None,
            data_criacao=None,
            cidade='SAO PAULO',
            estado='SP',
        )
        config = SimpleNamespace(
            id=51,
            valor_500mb_pap_manual=Decimal('200.00'),
            valor_700mb_pap_manual=Decimal('220.00'),
            valor_1gb_pap_manual=Decimal('240.00'),
            valor_500mb_cnpj_manual=Decimal('250.00'),
            valor_700mb_cnpj_manual=Decimal('280.00'),
            valor_1gb_cnpj_manual=Decimal('300.00'),
        )
        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=None,
            ),
            patch(
                'crm_app.services.comissao_matriz_service.get_valor_manual_vendedor_plano',
                return_value=None,
            ),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=None,
                config=config,
                usar_manual=True,
                chave='600MB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 200.0)

    def test_manual_700mb_herda_de_plano_800mb_equivalente_na_mesma_config(self) -> None:
        from crm_app.services.comissao_matriz_service import (
            MatrizComissaoCache,
            get_valor_manual_vendedor_plano,
        )

        plano_700 = SimpleNamespace(id=25, nome='NIO ESSENCIAL 700MB', gdp_velocidade_mbps=700)
        plano_800 = SimpleNamespace(id=26, nome='NIO SUPER 800MB', gdp_velocidade_mbps=800)
        row_800 = SimpleNamespace(
            config_id=13,
            plano_id=26,
            plano=plano_800,
            valor_pap=Decimal('220.00'),
            valor_cnpj=Decimal('280.00'),
        )
        cache = MatrizComissaoCache()
        cache._manual_config[(13, 26)] = row_800
        cache._manual_por_config[13] = [row_800]
        config = SimpleNamespace(id=13)

        self.assertEqual(
            get_valor_manual_vendedor_plano(config, plano_700, 'CPF', matriz_cache=cache),
            220.0,
        )
        self.assertEqual(
            get_valor_manual_vendedor_plano(config, plano_700, 'CNPJ', matriz_cache=cache),
            280.0,
        )

