from __future__ import annotations

from typing import Any, Optional
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from crm_app.models import AssertivaNomeCache
from crm_app.services.assertiva_localize_service import (
    AssertivaConfigurationError,
    AssertivaError,
    AssertivaLocalizeService,
    obter_nome_por_cpf,
    obter_primeiro_nome_por_cpf,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, consulta_payload: dict[str, Any]) -> None:
        self.consulta_payload = consulta_payload
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append({"url": url, **kwargs})
        return FakeResponse(
            200,
            {
                "access_token": "token-de-teste",
                "token_type": "bearer",
                "expires_in": 60,
            },
        )

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        return FakeResponse(200, self.consulta_payload)


@override_settings(
    ASSERTIVA_API_BASE_URL="https://api.assertiva.test",
    ASSERTIVA_TOKEN_URL="https://api.assertiva.test/oauth2/v3/token",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "assertiva-tests",
        }
    },
)
class AssertivaLocalizeServiceTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def _criar_servico(
        self,
        payload: dict[str, Any],
        session: Optional[FakeSession] = None,
    ) -> tuple[AssertivaLocalizeService, FakeSession]:
        fake_session = session or FakeSession(payload)
        servico = AssertivaLocalizeService(
            client_id="client-id",
            client_secret="client-secret",
            http_session=fake_session,  # type: ignore[arg-type]
        )
        return servico, fake_session

    def test_seleciona_contatos_e_endereco_mais_confiaveis(self) -> None:
        payload = {
            "resposta": {
                "nome": "MARIA DA SILVA SANTOS",
                "telefones": {
                    "moveis": [
                        {
                            "numero": "(31) 98888-1111",
                            "relacao": "Possível",
                            "naoPerturbe": True,
                            "aplicativos": {"whatsApp": False},
                        },
                        {
                            "numero": "(31) 99999-2222",
                            "relacao": "Direto",
                            "naoPerturbe": False,
                            "aplicativos": {"whatsApp": True},
                        },
                    ],
                    "fixos": [
                        {
                            "numero": "(31) 3333-4444",
                            "relacao": "Direto",
                            "naoPerturbe": False,
                        }
                    ],
                },
                "emails": [
                    {"email": " CLIENTE@EXEMPLO.COM "},
                    {"email": "invalido"},
                ],
                "enderecos": [
                    {
                        "logradouro": "RUA APROXIMADA",
                        "numero": "10",
                        "cep": "30100-000",
                        "precisaoCep": "APROXIMADA",
                    },
                    {
                        "logradouro": "RUA CONFIRMADA",
                        "numero": "20",
                        "complemento": "AP 2",
                        "cep": "30200-000",
                        "precisaoCep": "CONFIRMADA",
                    },
                ],
            }
        }
        servico, session = self._criar_servico(payload)

        dados = servico.consultar_para_credito("123.456.789-01")

        self.assertEqual(dados.nome, "MARIA DA SILVA SANTOS")
        self.assertEqual(dados.primeiro_nome, "Maria")
        self.assertEqual(dados.telefone_principal, "31999992222")
        self.assertEqual(dados.telefone_secundario, "31988881111")
        self.assertEqual(dados.email_principal, "cliente@exemplo.com")
        self.assertIsNotNone(dados.endereco)
        assert dados.endereco is not None
        self.assertEqual(dados.endereco.cep, "30200000")
        self.assertEqual(dados.endereco.numero, "20")
        self.assertEqual(dados.endereco.referencia, "AP 2")
        self.assertEqual(
            session.post_calls[0]["auth"],
            ("client-id", "client-secret"),
        )
        self.assertEqual(
            session.get_calls[0]["params"],
            {"cpf": "12345678901", "idFinalidade": 2},
        )

    def test_consulta_cnpj_no_endpoint_correto(self) -> None:
        servico, session = self._criar_servico({"resposta": {}})

        servico.consultar_para_credito("12.345.678/0001-90")

        self.assertTrue(session.get_calls[0]["url"].endswith("/localize/v3/cnpj"))
        self.assertEqual(
            session.get_calls[0]["params"],
            {"cnpj": "12345678000190", "idFinalidade": 2},
        )

    def test_reutiliza_token_enquanto_estiver_no_cache(self) -> None:
        servico, session = self._criar_servico({"resposta": {}})

        servico.consultar_para_credito("12345678901")
        servico.consultar_para_credito("12345678901")

        self.assertEqual(len(session.post_calls), 1)
        self.assertEqual(len(session.get_calls), 2)

    def test_exige_credenciais(self) -> None:
        servico = AssertivaLocalizeService(
            client_id="",
            client_secret="",
            http_session=FakeSession({"resposta": {}}),  # type: ignore[arg-type]
        )

        with self.assertRaises(AssertivaConfigurationError):
            servico.consultar_para_credito("12345678901")

    def test_converte_timeout_em_erro_controlado(self) -> None:
        session = FakeSession({"resposta": {}})
        session.get = Mock(side_effect=requests.Timeout("tempo esgotado"))
        servico, _ = self._criar_servico(
            {"resposta": {}},
            session=session,
        )

        with self.assertRaisesMessage(
            AssertivaError,
            "não respondeu dentro do tempo esperado",
        ):
            servico.consultar_para_credito("12345678901")

    def test_selecionar_nome_em_cadastro_basico(self) -> None:
        nome = AssertivaLocalizeService._selecionar_nome(
            {"cadastroBasico": {"nomeCompleto": "  PEDRO ALVES  "}}
        )
        self.assertEqual(nome, "PEDRO ALVES")


@override_settings(
    ASSERTIVA_API_BASE_URL="https://api.assertiva.test",
    ASSERTIVA_TOKEN_URL="https://api.assertiva.test/oauth2/v3/token",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "assertiva-nome-bd-tests",
        }
    },
)
class ObterNomePorCpfPersistenciaTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def _servico_com_nome(self, nome: str) -> AssertivaLocalizeService:
        fake_session = FakeSession({"resposta": {"nome": nome}})
        return AssertivaLocalizeService(
            client_id="client-id",
            client_secret="client-secret",
            http_session=fake_session,  # type: ignore[arg-type]
        )

    def test_hit_bd_nao_chama_api(self) -> None:
        AssertivaNomeCache.objects.create(
            cpf="12345678901",
            nome="JOANA PRADO LIMA",
            fonte="assertiva",
        )
        with patch(
            "crm_app.services.assertiva_localize_service.AssertivaLocalizeService"
        ) as mock_cls:
            nome = obter_nome_por_cpf("123.456.789-01")
        self.assertEqual(nome, "JOANA PRADO LIMA")
        mock_cls.assert_not_called()

    def test_miss_consulta_api_e_grava_bd(self) -> None:
        servico = self._servico_com_nome("JOANA PRADO LIMA")
        with patch(
            "crm_app.services.assertiva_localize_service.AssertivaLocalizeService",
            return_value=servico,
        ):
            nome = obter_nome_por_cpf("12345678901")
        self.assertEqual(nome, "JOANA PRADO LIMA")
        registro = AssertivaNomeCache.objects.get(cpf="12345678901")
        self.assertEqual(registro.nome, "JOANA PRADO LIMA")
        self.assertEqual(registro.fonte, "assertiva")
        self.assertEqual(obter_primeiro_nome_por_cpf("12345678901"), "Joana")

    def test_falha_api_retorna_none_sem_gravar(self) -> None:
        with patch(
            "crm_app.services.assertiva_localize_service.AssertivaLocalizeService",
            side_effect=AssertivaError("indisponível"),
        ):
            nome = obter_nome_por_cpf("12345678901")
        self.assertIsNone(nome)
        self.assertFalse(AssertivaNomeCache.objects.filter(cpf="12345678901").exists())

    def test_segunda_chamada_usa_bd_sem_api(self) -> None:
        servico = self._servico_com_nome("PEDRO ALVES COSTA")
        with patch(
            "crm_app.services.assertiva_localize_service.AssertivaLocalizeService",
            return_value=servico,
        ) as mock_cls:
            n1 = obter_nome_por_cpf("12345678901")
            cache.clear()  # força lookup via BD, não cache Django
            n2 = obter_nome_por_cpf("12345678901")
        self.assertEqual(n1, "PEDRO ALVES COSTA")
        self.assertEqual(n2, "PEDRO ALVES COSTA")
        self.assertEqual(mock_cls.call_count, 1)
        self.assertEqual(AssertivaNomeCache.objects.filter(cpf="12345678901").count(), 1)
