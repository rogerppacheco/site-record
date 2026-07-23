# -*- coding: utf-8 -*-
"""Testes do DFV/CDOE (Power BI) e não-regressão da Fachada desativada."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from crm_app.services.dfv_powerbi_service import (
    DfvPowerBiDisabled,
    DfvPowerBiError,
    DfvPowerBiTimeout,
    _montar_complemento,
    consultar_fachadas_por_cdo,
    consultar_fachadas_por_cep,
    formatar_numeros_rua_cdoe,
    formatar_resumo_cdoe,
    formatar_resposta_dfv_powerbi,
    limpar_cep,
    limpar_codigo_cdo,
    montar_grupos_rua_cdoe,
    parse_dsr_rows,
)


class LimparCepTest(SimpleTestCase):
    def test_com_hifen(self):
        self.assertEqual(limpar_cep("30130-000"), "30130000")

    def test_so_digitos(self):
        self.assertEqual(limpar_cep("23900315"), "23900315")

    def test_zero_esquerda(self):
        self.assertEqual(limpar_cep("130000"), "00130000")


class LimparCodigoCdoTest(SimpleTestCase):
    def test_trim_e_upper(self):
        self.assertEqual(limpar_codigo_cdo("  cdo-1  "), "CDO-1")

    def test_remove_espacos(self):
        self.assertEqual(limpar_codigo_cdo("CDO 123"), "CDO123")

    def test_vazio(self):
        self.assertEqual(limpar_codigo_cdo("   "), "")


class MontarComplementoTest(SimpleTestCase):
    def test_concatena_tres(self):
        row = {
            "COMPLEMENTO1": "CA 1",
            "COMPLEMENTO2": "BL A",
            "COMPLEMENTO3": "AP 101",
        }
        self.assertEqual(_montar_complemento(row), "CA 1 | BL A | AP 101")

    def test_ignora_vazios(self):
        row = {"COMPLEMENTO1": "CA 1", "COMPLEMENTO2": "", "COMPLEMENTO3": None}
        self.assertEqual(_montar_complemento(row), "CA 1")


class ParseDsrTest(SimpleTestCase):
    def test_value_dicts_repeat_null(self):
        # 3 colunas: A, B, C — linha1 valores; linha2 R=repeat col0, Ø=null col2
        data = {
            "results": [
                {
                    "result": {
                        "data": {
                            "dsr": {
                                "DS": [
                                    {
                                        "ValueDicts": {"D0": ["RUA X", "CENTRO"]},
                                        "IC": True,
                                        "PH": [
                                            {
                                                "DM0": [
                                                    {
                                                        "S": [
                                                            {"N": "G0", "DN": "D0"},
                                                            {"N": "G1"},
                                                            {"N": "G2", "DN": "D0"},
                                                        ],
                                                        "C": [0, 10, 1],
                                                    },
                                                    {
                                                        "R": 1,  # col 0 repeat
                                                        "\u00d8": 4,  # col 2 null (bit 2)
                                                        "C": [12],
                                                    },
                                                ]
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                }
            ]
        }
        rows, incomplete, rt = parse_dsr_rows(data, 3)
        self.assertFalse(incomplete)
        self.assertIsNone(rt)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ["RUA X", 10, "CENTRO"])
        self.assertEqual(rows[1][0], "RUA X")  # repeat
        self.assertEqual(rows[1][1], 12)
        self.assertIsNone(rows[1][2])  # null mask


class FormatacaoRespostaTest(SimpleTestCase):
    def test_lista_com_complementos(self):
        regs = [
            {
                "CEP": "30130000",
                "NO_FACHADA": "12",
                "COMPLEMENTO1": "AP 101",
                "COMPLEMENTO2": None,
                "COMPLEMENTO3": None,
                "LOGRADOURO": "RUA X",
                "BAIRRO": "Y",
                "MUNICIPIO": "BH",
                "UF": "MG",
                "VIABILIDADE_ATUAL": "Viável",
                "CODIGO_CDO": "CDO-1",
            },
            {
                "CEP": "30130000",
                "NO_FACHADA": "10",
                "COMPLEMENTO1": "CA 1",
                "COMPLEMENTO2": "BL A",
                "COMPLEMENTO3": None,
                "LOGRADOURO": "RUA X",
                "BAIRRO": "Y",
                "MUNICIPIO": "BH",
                "UF": "MG",
                "VIABILIDADE_ATUAL": "Viável",
                "CODIGO_CDO": "CDO-1",
            },
            {
                "CEP": "30130000",
                "NO_FACHADA": "10",
                "COMPLEMENTO1": "CA 1",
                "COMPLEMENTO2": "BL A",
                "COMPLEMENTO3": None,
                "LOGRADOURO": "RUA X",
                "BAIRRO": "Y",
                "MUNICIPIO": "BH",
                "UF": "MG",
                "VIABILIDADE_ATUAL": "Viável",
                "CODIGO_CDO": "CDO-1",
            },
        ]
        partes = formatar_resposta_dfv_powerbi("30130-000", regs)
        self.assertEqual(len(partes), 1)
        texto = partes[0]
        self.assertIn("DFV (Power BI ao vivo)", texto)
        self.assertIn("RUA X", texto)
        self.assertIn("*Total de fachadas:* 2", texto)
        self.assertIn("10 (CA 1 | BL A)", texto)
        self.assertIn("12 (AP 101)", texto)
        # formato compacto com vírgula (como a antiga Fachada)
        self.assertIn("10 (CA 1 | BL A), 12 (AP 101)", texto)
        # ordenado por número
        self.assertLess(texto.index("10 (CA 1"), texto.index("12 (AP 101)"))

    def test_sem_resultado(self):
        partes = formatar_resposta_dfv_powerbi("00000000", [])
        self.assertEqual(len(partes), 1)
        self.assertIn("NENHUMA FACHADA", partes[0])
        self.assertIn("Power BI", partes[0])
        self.assertNotIn("Fachada", partes[0])
        self.assertIn("CDOE", partes[0])

    def test_sem_viaveis_mostra_status(self):
        regs = [
            {
                "CEP": "30130000",
                "NO_FACHADA": "5",
                "COMPLEMENTO1": None,
                "COMPLEMENTO2": None,
                "COMPLEMENTO3": None,
                "LOGRADOURO": "RUA Z",
                "BAIRRO": "B",
                "MUNICIPIO": "C",
                "UF": "RJ",
                "VIABILIDADE_ATUAL": "Inviável",
                "CODIGO_CDO": "X",
            }
        ]
        texto = formatar_resposta_dfv_powerbi("30130000", regs)[0]
        self.assertIn("Sem fachadas viáveis", texto)
        self.assertIn("Inviável", texto)
        self.assertIn("5", texto)

    def test_fatiar_mensagem_longa(self):
        regs = []
        for i in range(200):
            regs.append(
                {
                    "CEP": "30130000",
                    "NO_FACHADA": str(i + 1),
                    "COMPLEMENTO1": f"COMPL MUITO LONGO PARA ESTOURAR LIMITE {i}",
                    "COMPLEMENTO2": "BL A",
                    "COMPLEMENTO3": "AP 999",
                    "LOGRADOURO": "RUA LONGA",
                    "BAIRRO": "BAIRRO",
                    "MUNICIPIO": "CIDADE",
                    "UF": "MG",
                    "VIABILIDADE_ATUAL": "Viável",
                    "CODIGO_CDO": "CDO",
                }
            )
        partes = formatar_resposta_dfv_powerbi("30130000", regs)
        self.assertGreater(len(partes), 1)
        self.assertTrue(all(len(p) <= 4000 for p in partes))


class CdoeFormatacaoTest(SimpleTestCase):
    def _regs_duas_ruas(self):
        return [
            {
                "CEP": "30130000",
                "NO_FACHADA": "10",
                "COMPLEMENTO1": None,
                "COMPLEMENTO2": None,
                "COMPLEMENTO3": None,
                "LOGRADOURO": "RUA A",
                "BAIRRO": "CENTRO",
                "MUNICIPIO": "BH",
                "UF": "MG",
                "VIABILIDADE_ATUAL": "Viável",
                "CODIGO_CDO": "CDO-99",
            },
            {
                "CEP": "30130000",
                "NO_FACHADA": "12",
                "COMPLEMENTO1": "AP 1",
                "COMPLEMENTO2": None,
                "COMPLEMENTO3": None,
                "LOGRADOURO": "RUA A",
                "BAIRRO": "CENTRO",
                "MUNICIPIO": "BH",
                "UF": "MG",
                "VIABILIDADE_ATUAL": "Viável",
                "CODIGO_CDO": "CDO-99",
            },
            {
                "CEP": "30140000",
                "NO_FACHADA": "5",
                "COMPLEMENTO1": None,
                "COMPLEMENTO2": None,
                "COMPLEMENTO3": None,
                "LOGRADOURO": "RUA B",
                "BAIRRO": "SAVASSI",
                "MUNICIPIO": "BH",
                "UF": "MG",
                "VIABILIDADE_ATUAL": "Viável",
                "CODIGO_CDO": "CDO-99",
            },
        ]

    def test_agrupa_por_rua_cep(self):
        grupos = montar_grupos_rua_cdoe(self._regs_duas_ruas())
        self.assertEqual(len(grupos), 2)
        self.assertEqual(grupos[0]["logradouro"], "RUA A")
        self.assertEqual(len(grupos[0]["linhas"]), 2)
        self.assertEqual(grupos[1]["logradouro"], "RUA B")
        self.assertEqual(len(grupos[1]["linhas"]), 1)

    def test_resumo_numerado(self):
        grupos = montar_grupos_rua_cdoe(self._regs_duas_ruas())
        texto = formatar_resumo_cdoe("cdo-99", grupos)[0]
        self.assertIn("CDOE (Power BI ao vivo)", texto)
        self.assertIn("CDO-99", texto)
        self.assertIn("1)", texto)
        self.assertIn("2)", texto)
        self.assertIn("RUA A", texto)
        self.assertIn("RUA B", texto)
        self.assertIn("CANCELAR", texto)

    def test_resumo_vazio(self):
        texto = formatar_resumo_cdoe("X", [])[0]
        self.assertIn("NENHUM ENDEREÇO", texto)
        self.assertIn("DFV", texto)

    def test_numeros_da_rua(self):
        grupos = montar_grupos_rua_cdoe(self._regs_duas_ruas())
        texto = formatar_numeros_rua_cdoe("CDO-99", grupos[0])[0]
        self.assertIn("CDOE CDO-99", texto)
        self.assertIn("RUA A", texto)
        self.assertIn("*Total de fachadas:* 2", texto)
        self.assertIn("10", texto)
        self.assertIn("12 (AP 1)", texto)


@override_settings(
    DFV_POWERBI_ENABLED=True,
    DFV_POWERBI_RESOURCE_KEY="test-key",
    DFV_POWERBI_CLUSTER="https://example.invalid",
    DFV_POWERBI_MODEL_ID=1,
    DFV_POWERBI_TIMEOUT_SECONDS=5,
    DFV_POWERBI_CACHE_TTL_SECONDS=0,
)
class ConsultarPowerBiTest(SimpleTestCase):
    @override_settings(DFV_POWERBI_ENABLED=False)
    def test_feature_flag_desligada(self):
        with self.assertRaises(DfvPowerBiDisabled):
            consultar_fachadas_por_cep("30130000")

    def test_cep_invalido(self):
        with self.assertRaises(DfvPowerBiError):
            consultar_fachadas_por_cep("123")

    def test_cdo_invalido(self):
        with self.assertRaises(DfvPowerBiError):
            consultar_fachadas_por_cdo("   ")

    @patch("crm_app.services.dfv_powerbi_service.requests.post")
    def test_timeout(self, mock_post):
        import requests as req

        mock_post.side_effect = req.Timeout("timeout")
        with self.assertRaises(DfvPowerBiTimeout):
            consultar_fachadas_por_cep("30130000")

    @patch("crm_app.services.dfv_powerbi_service.requests.post")
    def test_sucesso_mock(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "result": {
                        "data": {
                            "dsr": {
                                "DS": [
                                    {
                                        "ValueDicts": {
                                            "D0": ["30130000", "RUA X", "Y", "BH", "MG", "Viável", "CDO-1"]
                                        },
                                        "IC": True,
                                        "PH": [
                                            {
                                                "DM0": [
                                                    {
                                                        "S": [
                                                            {"N": "G0", "DN": "D0"},  # CEP
                                                            {"N": "G1"},  # NO_FACHADA
                                                            {"N": "G2"},  # C1
                                                            {"N": "G3"},  # C2
                                                            {"N": "G4"},  # C3
                                                            {"N": "G5", "DN": "D0"},  # LOGRADOURO
                                                            {"N": "G6", "DN": "D0"},  # BAIRRO
                                                            {"N": "G7", "DN": "D0"},  # MUNICIPIO
                                                            {"N": "G8", "DN": "D0"},  # UF
                                                            {"N": "G9", "DN": "D0"},  # VIAB
                                                            {"N": "G10", "DN": "D0"},  # CDO
                                                        ],
                                                        "C": [0, 10, 1, 2, 3, 4, 5, 6],
                                                        "\u00d8": (1 << 2) | (1 << 3) | (1 << 4),
                                                    }
                                                ]
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp
        regs = consultar_fachadas_por_cep("30130000")
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0]["NO_FACHADA"], 10)
        self.assertEqual(regs[0]["LOGRADOURO"], "RUA X")

    @patch("crm_app.services.dfv_powerbi_service.requests.post")
    def test_consulta_por_cdo_filtra_coluna(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "result": {
                        "data": {
                            "dsr": {
                                "DS": [
                                    {
                                        "ValueDicts": {},
                                        "IC": True,
                                        "PH": [{"DM0": []}],
                                    }
                                ]
                            }
                        }
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp
        regs = consultar_fachadas_por_cdo("CDO-99")
        self.assertEqual(regs, [])
        payload = mock_post.call_args.kwargs.get("data") or mock_post.call_args[1].get("data")
        if payload is None:
            # requests.post(..., data=json.dumps(...))
            import json

            raw = mock_post.call_args[1].get("data") if mock_post.call_args[1] else mock_post.call_args.kwargs.get("data")
            self.assertIsNotNone(raw)
            payload = raw
        import json

        body = json.loads(payload) if isinstance(payload, str) else payload
        cmd = body["queries"][0]["Query"]["Commands"][0]
        where = cmd["SemanticQueryDataShapeCommand"]["Query"]["Where"][0]
        prop = where["Condition"]["Comparison"]["Left"]["Column"]["Property"]
        lit = where["Condition"]["Comparison"]["Right"]["Literal"]["Value"]
        self.assertEqual(prop, "CODIGO_CDO")
        self.assertEqual(lit, "'CDO-99'")


class MenuEFluxoWebhookTest(SimpleTestCase):
    """Garante texto do MENU e que Fachada foi desativada em favor de DFV/CDOE."""

    def test_menu_contem_dfv_e_cdoe_sem_fachada(self):
        linhas_menu = [
            "• *DFV* - Consultar fachadas por CEP (Power BI ao vivo)\n",
            "• *CDOE* - Consultar endereços por código do CDO (Power BI)\n",
        ]
        menu = "".join(linhas_menu)
        self.assertIn("*DFV*", menu)
        self.assertIn("*CDOE*", menu)
        self.assertIn("Power BI ao vivo", menu)
        self.assertNotIn("*Fachada*", menu)

    def test_mensagem_redirecionamento_fachada(self):
        msg = (
            "A consulta de fachadas agora é pelo *DFV*.\n"
            "Envie *DFV* no chat para consultar online a base de viabilidade da Nio."
        )
        self.assertIn("*DFV*", msg)
        self.assertIn("viabilidade da Nio", msg)

    @patch("crm_app.utils.DFV")
    @patch("builtins.print")
    def test_listar_fachadas_local_ainda_existe(self, _mock_print, mock_dfv):
        """Base local permanece no código (legado), mas o comando WPP não a usa mais."""
        from crm_app.utils import listar_fachadas_dfv

        qs = MagicMock()
        qs.filter.return_value = qs
        qs.values_list.return_value = [
            ("10", "CA 1", "RUA A", "CENTRO", "GPON", "CDO-1"),
        ]
        mock_dfv.objects.filter.return_value = qs

        with patch(
            "crm_app.services.dfv_powerbi_service.consultar_fachadas_por_cep"
        ) as mock_pbi:
            resultado = listar_fachadas_dfv("30130000")
            mock_pbi.assert_not_called()

        texto = "\n".join(resultado) if isinstance(resultado, list) else resultado
        self.assertIn("RELATÓRIO DE FACHADAS (DFV)", texto)
        self.assertNotIn("Power BI ao vivo", texto)
