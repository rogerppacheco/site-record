"""Testes de validação de cobrança Qualidade."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from django.test import SimpleTestCase

from crm_app.services.qualidade_service import validar_fatura_para_envio_cobranca


class TestValidarFaturaCobranca(SimpleTestCase):
    def test_bloqueia_valor_zero(self) -> None:
        fatura = SimpleNamespace(valor=0, data_vencimento=date(2026, 6, 30))
        ok, msg = validar_fatura_para_envio_cobranca(fatura)
        self.assertFalse(ok)
        self.assertIn("valor", msg.lower())

    def test_bloqueia_sem_vencimento(self) -> None:
        fatura = SimpleNamespace(valor=99.9, data_vencimento=None)
        ok, msg = validar_fatura_para_envio_cobranca(fatura)
        self.assertFalse(ok)
        self.assertIn("vencimento", msg.lower())

    def test_permite_valor_e_vencimento(self) -> None:
        fatura = SimpleNamespace(valor="120.50", data_vencimento=date(2026, 6, 30))
        ok, msg = validar_fatura_para_envio_cobranca(fatura)
        self.assertTrue(ok)
        self.assertEqual(msg, "")
