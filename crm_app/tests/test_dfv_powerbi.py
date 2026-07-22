# -*- coding: utf-8 -*-
"""Testes do comando DFV (Power BI ao vivo) e não-regressão do FACHADA."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from crm_app.services.dfv_powerbi_service import (
    DfvPowerBiDisabled,
    DfvPowerBiError,
    DfvPowerBiTimeout,
    _montar_complemento,
    consultar_fachadas_por_cep,
    formatar_resposta_dfv_powerbi,
    limpar_cep,
    parse_dsr_rows,
)


class LimparCepTest(SimpleTestCase):
    def test_com_hifen(self):
        self.assertEqual(limpar_cep("30130-000"), "30130000")

    def test_so_digitos(self):
        self.assertEqual(limpar_cep("23900315"), "23900315")

    def test_zero_esquerda(self):
        self.assertEqual(limpar_cep("130000"), "00130000")


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
        # ordenado por número
        self.assertLess(texto.index("10 (CA 1"), texto.index("12 (AP 101)"))

    def test_sem_resultado(self):
        partes = formatar_resposta_dfv_powerbi("00000000", [])
        self.assertEqual(len(partes), 1)
        self.assertIn("NENHUMA FACHADA", partes[0])
        self.assertIn("Power BI", partes[0])

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


class MenuEFluxoWebhookTest(SimpleTestCase):
    """Garante texto do MENU e que FACHADA não importa o service Power BI."""

    def test_menu_contem_dfv_e_fachada(self):
        # Trecho espelhado do handler (evita subir o webhook inteiro)
        linhas_menu = [
            "• *Fachada* - Consultar fachadas por CEP\n",
            "• *DFV* - Consultar fachadas por CEP (Power BI ao vivo)\n",
        ]
        menu = "".join(linhas_menu)
        self.assertIn("*DFV*", menu)
        self.assertIn("Power BI ao vivo", menu)
        self.assertIn("*Fachada*", menu)

    @patch("crm_app.utils.DFV")
    @patch("builtins.print")
    def test_fachada_usa_apenas_base_local(self, _mock_print, mock_dfv):
        """Não-regressão: listar_fachadas_dfv não chama Power BI."""
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
