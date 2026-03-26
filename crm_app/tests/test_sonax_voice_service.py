from django.test import SimpleTestCase, override_settings

from crm_app.sonax_voice_service import SonaxVoiceService
from crm_app.auditoria_ligacoes_api import (
    _finalizada_por_status,
    _merge_webhook_payload,
    _webhook_call_id,
)


@override_settings(
    SONAX_CLICK2CALL_TOKEN="t",
    SONAX_ID_CLIENTE="1",
    SONAX_INTEGRATION_TOKEN="t",
)
class SonaxVoiceServiceParseTest(SimpleTestCase):
    def test_extract_protocol_from_html_message(self):
        svc = SonaxVoiceService()
        self.assertEqual(
            svc._extract_protocol_from_text("PROTOCOLO 998877 da Ligacao Realizada para 31999999999"),
            "998877",
        )

    def test_extract_protocol_from_click2call_started_message(self):
        svc = SonaxVoiceService()
        self.assertEqual(
            svc._extract_protocol_from_text("Ligação iniciada. ID: 20 | Provedor: sem_id_1774555202.672607"),
            "20",
        )

    def test_parse_json_response_body(self):
        svc = SonaxVoiceService()
        import requests

        r = requests.Response()
        r.status_code = 200
        r._content = b'{"id_chamada": "42", "ok": true}'
        r.headers["content-type"] = "application/json"
        parsed = svc._parse_click2call_response(r)
        self.assertEqual(parsed.get("id_chamada"), "42")


class AuditoriaWebhookHelpersTest(SimpleTestCase):
    def test_merge_query_and_body(self):
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        django_req = factory.get("/hook/", {"id_chamada": "7", "duracao": "15"})
        merged = _merge_webhook_payload(Request(django_req))
        self.assertEqual(merged.get("id_chamada"), "7")
        self.assertEqual(merged.get("duracao"), "15")

    def test_call_id_keys(self):
        self.assertEqual(_webhook_call_id({"id_chamada": "99"}), "99")
        self.assertEqual(_webhook_call_id({"ID_CHAMADA": "100"}), "100")

    def test_sonax_finalizada_status(self):
        self.assertTrue(_finalizada_por_status("SONAX", "desligada"))
        self.assertFalse(_finalizada_por_status("SONAX", "discando"))
