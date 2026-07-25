from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from crm_app.services.whatsapp.delivery_tracker import (
    aguardar_entrega,
    processar_delivery_callback,
)
from crm_app.whatsapp_webhook_fastpath import avaliar_fastpath_zapi

_LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "wa-delivery-tests",
    }
}


@override_settings(CACHES=_LOCMEM)
class DeliveryTrackerTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_callback_sucesso_sem_error(self) -> None:
        out = processar_delivery_callback(
            {
                "type": "DeliveryCallback",
                "phone": "5531999999999",
                "messageId": "MID1",
                "zaapId": "ZAAP1",
            }
        )
        self.assertTrue(out["ok"])
        ok, detalhe = aguardar_entrega("MID1", timeout=0.5)
        self.assertTrue(ok)
        self.assertIsNotNone(detalhe)

    def test_callback_falha_com_error(self) -> None:
        processar_delivery_callback(
            {
                "type": "DeliveryCallback",
                "phone": "5531999999999",
                "messageId": "MID2",
                "zaapId": "ZAAP2",
                "error": "Phone number does not exist",
                "errorCode": "SHADOW_BAN",
            }
        )
        ok, detalhe = aguardar_entrega("ZAAP2", timeout=0.5)
        self.assertFalse(ok)
        self.assertEqual(detalhe["error"], "Phone number does not exist")

    def test_timeout_sem_callback(self) -> None:
        with patch(
            "crm_app.services.whatsapp.delivery_tracker._POLL_INTERVAL",
            0.05,
        ):
            ok, detalhe = aguardar_entrega("MID_INEXISTENTE", timeout=0.2)
        self.assertFalse(ok)
        self.assertIsNone(detalhe)

    def test_fastpath_ainda_ignora_delivery_se_chegar_la(self) -> None:
        """Defesa: se o view não interceptar, fastpath não enfileira handler pesado."""
        out = avaliar_fastpath_zapi(
            {
                "type": "DeliveryCallback",
                "phone": "5531999999999",
                "messageId": "MID3",
            }
        )
        self.assertIsNotNone(out)
        self.assertIn("ignorado", out["mensagem"].lower())
