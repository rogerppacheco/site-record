"""Testes unitários — elegibilidade e params dos templates do Funil."""
from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from crm_app.services import funil_template_envio_service as svc
from crm_app.services.whatsapp.nio_templates import (
    TEMPLATE_CONSULTA_VIABILIDADE,
    TEMPLATE_REATIVACAO_CONTRATO,
    TEMPLATE_SELFIE_PENDENTE,
)


class FunilTemplateConstantesTests(SimpleTestCase):
    def test_selfie_usa_v1_nao_v2(self):
        self.assertEqual(TEMPLATE_SELFIE_PENDENTE, "nio_selfie_pendente_v1")
        self.assertNotIn("v2", TEMPLATE_SELFIE_PENDENTE)


class FunilTemplateBioContextoTests(SimpleTestCase):
    def test_bio_elegivel_com_nome_telefone_protocolo(self):
        from unittest.mock import patch

        with patch.object(svc, "_dedup_recente", return_value=None):
            ctx = svc.montar_contexto_bio(
                {
                    "cpf": "12345678901",
                    "telefone": "21999998888",
                    "protocolo": "1453635",
                    "nome_cliente": "Camila Souza",
                    "repescavel": True,
                },
                resolver_nome=False,
            )
        self.assertTrue(ctx["elegivel"])
        self.assertEqual(ctx["template_nome"], TEMPLATE_SELFIE_PENDENTE)
        self.assertEqual(ctx["body_params"], ["Camila", "Prot. 1453635"])

    def test_bio_protocolo_ja_com_prefixo(self):
        from unittest.mock import patch

        with patch.object(svc, "_dedup_recente", return_value=None):
            ctx = svc.montar_contexto_bio(
                {
                    "cpf": "12345678901",
                    "telefone": "21999998888",
                    "protocolo": "Prot. 99",
                    "nome_cliente": "Ana",
                    "repescavel": True,
                },
                resolver_nome=False,
            )
        self.assertEqual(ctx["body_params"][1], "Prot. 99")

    def test_bio_sem_repescavel_inelegivel(self):
        ctx = svc.montar_contexto_bio(
            {
                "cpf": "12345678901",
                "telefone": "21999998888",
                "protocolo": "1",
                "nome_cliente": "Ana",
                "repescavel": False,
            },
            resolver_nome=False,
        )
        self.assertFalse(ctx["elegivel"])
        self.assertIn("repescável", ctx["motivo_inelegivel"].lower())

    def test_preflight_bio_nao_exige_nome_na_listagem_via_resumo(self):
        ctx = svc.preflight_bio_linha(
            {
                "cpf": "12345678901",
                "telefone": "21999998888",
                "protocolo": "1453635",
                "nome_cliente": "",
                "repescavel": True,
            }
        )
        self.assertFalse(ctx["elegivel"])
        resumo = svc.resumo_envio_listagem(ctx, assertiva_no_envio=True)
        self.assertTrue(resumo["elegivel_envio"])
        self.assertTrue(resumo["assertiva_no_envio"])


class FunilTemplateChurnInteresseTests(SimpleTestCase):
    def test_churn_exige_adimplente(self):
        ctx = svc.montar_contexto_churn(
            {
                "churn_id": 1,
                "venda_id": 10,
                "pedido": "OS1",
                "cpf_cliente": "12345678901",
                "nome_cliente": "João",
                "situacao_nio": "INADIMPLENTE",
                "sem_venda_crm": False,
                "telefone": "21988887777",
            }
        )
        self.assertFalse(ctx["elegivel"])
        self.assertIn("ADIMPLENTE", ctx["motivo_inelegivel"])

    def test_interesse_params_tres_vars(self):
        from unittest.mock import patch

        with patch.object(svc, "_cpf_tem_venda_crm", return_value=False), patch.object(
            svc, "_dedup_recente", return_value=None
        ):
            ctx = svc.montar_contexto_interesse(
                {
                    "tipo_venda": "INTERESSE",
                    "cliente": "Mariana Costa",
                    "cpf": "12345678901",
                    "celular_principal": "21977776666",
                    "logradouro": "Av. Brasil",
                    "numero": "450",
                    "bairro": "Centro",
                    "cidade": "Rio",
                    "pedido": "882341",
                },
                pedido_id=55,
            )
        self.assertEqual(ctx["template_nome"], TEMPLATE_CONSULTA_VIABILIDADE)
        self.assertTrue(ctx["elegivel"])
        self.assertEqual(len(ctx["body_params"]), 3)
        self.assertEqual(ctx["body_params"][0], "Mariana")

    def test_validar_params_selfie_duas_vars(self):
        ok, _ = svc.validar_params(TEMPLATE_SELFIE_PENDENTE, ["Camila", "Prot. 1"])
        self.assertTrue(ok)
        ok2, msg = svc.validar_params(TEMPLATE_SELFIE_PENDENTE, ["Camila"])
        self.assertFalse(ok2)
        self.assertIn("2", msg)

    def test_validar_params_reativacao_tres_vars(self):
        ok, _ = svc.validar_params(TEMPLATE_REATIVACAO_CONTRATO, ["João", "OS1", "Rua A, 1"])
        self.assertTrue(ok)


@override_settings(WHATSAPP_USE_NIO_TEMPLATES=False)
class FunilTemplateCanalTests(SimpleTestCase):
    def test_canal_bloqueia_sem_templates(self):
        pronto, motivo = svc._canal_pronto()
        self.assertFalse(pronto)
        self.assertIn("desabilitados", motivo.lower())
