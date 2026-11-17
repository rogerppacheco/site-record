"""Testes de elegibilidade WhatsApp (celular BR + não perturbe)."""
from django.test import SimpleTestCase, TestCase

from crm_app.models import Cliente, Venda
from crm_app.services.whatsapp.eligibility import (
    REGEX_CELULAR_BR,
    avaliar_elegibilidade_whatsapp,
    validar_celular_br,
)
from usuarios.models import Usuario


class ValidarCelularBrTests(SimpleTestCase):
    def test_aceita_ddd_mais_9_digitos(self):
        tel, ok = validar_celular_br("61985517198")
        self.assertTrue(ok)
        self.assertEqual(tel, "5561985517198")
        self.assertTrue(REGEX_CELULAR_BR.match(tel))

    def test_aceita_com_55(self):
        tel, ok = validar_celular_br("55 (61) 98551-7198")
        self.assertTrue(ok)
        self.assertEqual(tel, "5561985517198")

    def test_rejeita_fixo_sem_9(self):
        tel, ok = validar_celular_br("6133334444")
        self.assertFalse(ok)

    def test_rejeita_vazio(self):
        tel, ok = validar_celular_br("")
        self.assertFalse(ok)
        self.assertEqual(tel, "")


class AvaliarElegibilidadeTests(SimpleTestCase):
    def test_ok_com_celular_valido(self):
        r = avaliar_elegibilidade_whatsapp(
            telefone="61985517198", verificar_mailing_opt_out=False
        )
        self.assertTrue(r["ok"])
        self.assertEqual(r["telefone"], "5561985517198")
        self.assertEqual(r["motivos"], [])

    def test_nao_perturbe_bloqueia(self):
        r = avaliar_elegibilidade_whatsapp(
            telefone="61985517198",
            nao_perturbe=True,
            verificar_mailing_opt_out=False,
        )
        self.assertFalse(r["ok"])
        self.assertTrue(any("não perturbe" in m.lower() for m in r["motivos"]))

    def test_telefone_invalido(self):
        r = avaliar_elegibilidade_whatsapp(
            telefone="123", verificar_mailing_opt_out=False
        )
        self.assertFalse(r["ok"])
        self.assertTrue(any("inválido" in m.lower() for m in r["motivos"]))


class VendaEligibilityPropertyTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(username="vend_elig", password="x")
        self.cliente = Cliente.objects.create(
            nome_razao_social="Cliente Teste",
            cpf_cnpj="52998224725",
        )

    def test_venda_elegivel(self):
        venda = Venda.objects.create(
            vendedor=self.user,
            cliente=self.cliente,
            telefone1="61985517198",
        )
        self.assertTrue(venda.is_whatsapp_eligible)
        self.assertEqual(venda.whatsapp_eligibility["telefone"], "5561985517198")

    def test_venda_nao_perturbe(self):
        venda = Venda.objects.create(
            vendedor=self.user,
            cliente=self.cliente,
            telefone1="61985517198",
            nao_perturbe=True,
        )
        self.assertFalse(venda.is_whatsapp_eligible)
        self.assertTrue(
            any("não perturbe" in m.lower() for m in venda.whatsapp_eligibility["motivos"])
        )
