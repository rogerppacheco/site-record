"""Testes do normalizador de webhook Evolution e factory de provider."""
from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from crm_app.whatsapp_webhook_normalizer import (
    detectar_provedor,
    normalizar_webhook,
)
from crm_app.services.whatsapp.factory import get_whatsapp_provider
from crm_app.services.whatsapp.zapi_provider import ZapiProvider
from crm_app.services.whatsapp.n8n_outbound_provider import N8nOutboundProvider
from crm_app.services.whatsapp.evolution_provider import EvolutionProvider


class TestWebhookNormalizer(SimpleTestCase):
    def test_detecta_evolution_por_evento(self) -> None:
        payload = {"event": "messages.upsert", "data": {"key": {"remoteJid": "5511999999999@s.whatsapp.net"}}}
        self.assertEqual(detectar_provedor(payload), "evolution")

    def test_detecta_zapi(self) -> None:
        self.assertEqual(detectar_provedor({"phone": "5511999999999", "message": "oi"}), "zapi")

    def test_normaliza_texto_evolution(self) -> None:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5531999882528@s.whatsapp.net",
                    "fromMe": False,
                    "id": "ABC123",
                },
                "message": {"conversation": "VENDER"},
            },
        }
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["phone"], "5531999882528")
        self.assertFalse(canon["fromMe"])
        self.assertEqual(canon["message"]["text"], "VENDER")

    def test_normaliza_botao_evolution(self) -> None:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {"remoteJid": "5531999882528@s.whatsapp.net", "fromMe": False},
                "message": {
                    "buttonsResponseMessage": {
                        "selectedButtonId": "pap_confirmar_sim",
                        "selectedDisplayText": "SIM",
                    }
                },
            },
        }
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["buttonsResponseMessage"]["buttonId"], "pap_confirmar_sim")

    def test_normaliza_grupo_evolution(self) -> None:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "120363019502650977@g.us",
                    "participant": "5531999882528@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {"conversation": "123, antecipada"},
            },
        }
        canon = normalizar_webhook(payload)
        self.assertTrue(canon["isGroup"])
        self.assertIn("-group", canon["phone"])
        self.assertEqual(canon["participantPhone"], "5531999882528")


class TestProviderFactory(SimpleTestCase):
    def tearDown(self) -> None:
        get_whatsapp_provider.cache_clear()

    @override_settings(WHATSAPP_PROVIDER="zapi")
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="zapi",
    )
    def test_factory_zapi(self, _mock_provider: object) -> None:
        get_whatsapp_provider.cache_clear()
        self.assertIsInstance(get_whatsapp_provider(), ZapiProvider)

    @override_settings(WHATSAPP_PROVIDER="evolution")
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="evolution",
    )
    def test_factory_evolution(self, _mock_provider: object) -> None:
        get_whatsapp_provider.cache_clear()
        self.assertIsInstance(get_whatsapp_provider(), N8nOutboundProvider)


class TestN8nOutboundProvider(SimpleTestCase):
    @override_settings(
        N8N_OUTBOUND_WEBHOOK_URL="https://n8n.example/webhook/site-record-enviar-mensagem",
    )
    @patch("crm_app.services.whatsapp.n8n_outbound_provider.requests.post")
    def test_enviar_texto_via_n8n(self, mock_post) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {"ok": True}
        provider = N8nOutboundProvider()
        ok, resp = provider.enviar_mensagem_texto_raw("31999882528", "Olá")
        self.assertTrue(ok)
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["phone_number"], "5531999882528")
        self.assertEqual(payload["message_body"], "Olá")

    @override_settings(N8N_OUTBOUND_WEBHOOK_URL="")
    def test_texto_sem_webhook_falha(self) -> None:
        provider = N8nOutboundProvider()
        ok, err = provider.enviar_mensagem_texto_raw("31999882528", "Olá")
        self.assertFalse(ok)
        self.assertIn("N8N_OUTBOUND", str(err))

    @override_settings(
        N8N_OUTBOUND_WEBHOOK_URL="https://n8n.example/webhook/site-record-enviar-mensagem",
    )
    @patch("crm_app.services.whatsapp.n8n_outbound_provider.requests.post")
    def test_enviar_pdf_url_via_n8n(self, mock_post) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b""
        provider = N8nOutboundProvider()
        ok = provider.enviar_pdf_url(
            "31999882528",
            "https://cdn.example/doc.pdf",
            nome_arquivo="extrato.pdf",
            caption="Segue extrato",
        )
        self.assertTrue(ok)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["media_type"], "document")
        self.assertEqual(payload["media_url"], "https://cdn.example/doc.pdf")

    @override_settings(N8N_OUTBOUND_WEBHOOK_URL="https://n8n.example/webhook/x")
    @patch.object(EvolutionProvider, "enviar_imagem_b64", return_value={"messageId": "1"})
    def test_imagem_b64_delega_evolution(self, mock_b64) -> None:
        provider = N8nOutboundProvider()
        result = provider.enviar_imagem_b64("31999882528", "abc123", caption="img")
        self.assertEqual(result, {"messageId": "1"})
        mock_b64.assert_called_once()
