from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from crm_app.services.whatsapp.factory import PURPOSE_FUNIL, resolve_backend_for_purpose
from crm_app.services.whatsapp.whatsatende_provider import WhatsAtendeProvider
from crm_app.services.whatsapp_config_service import canal_funil_pronto


class TestCanalFunilSeparadoDoB(SimpleTestCase):
    @override_settings(WHATSATENDE_TOKEN_FUNIL="", WHATSATENDE_WHATSAPP_ID_FUNIL="")
    def test_sem_credencial_funil_nao_pronto(self) -> None:
        self.assertFalse(canal_funil_pronto())

    @override_settings(
        WHATSATENDE_TOKEN_FUNIL="tok-funil",
        WHATSATENDE_WHATSAPP_ID_FUNIL="247",
        WHATSATENDE_TOKEN_B="tok-b",
        WHATSATENDE_WHATSAPP_ID_B="194",
    )
    def test_funil_usa_token_e_id_proprios(self) -> None:
        self.assertTrue(canal_funil_pronto())
        backend, role = resolve_backend_for_purpose("whatsatende", PURPOSE_FUNIL)
        self.assertEqual(backend, "whatsatende")
        self.assertEqual(role, PURPOSE_FUNIL)
        provider = WhatsAtendeProvider(role=PURPOSE_FUNIL)
        self.assertEqual(provider.token, "tok-funil")
        self.assertEqual(provider.whatsapp_id, "247")
        cliente = WhatsAtendeProvider(role="cliente")
        self.assertEqual(cliente.token, "tok-b")
        self.assertEqual(cliente.whatsapp_id, "194")
