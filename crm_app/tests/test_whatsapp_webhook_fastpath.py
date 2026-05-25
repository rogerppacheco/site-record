from django.test import SimpleTestCase

from crm_app.whatsapp_webhook_fastpath import avaliar_fastpath_zapi


class WhatsappWebhookFastpathTests(SimpleTestCase):
    def test_ignora_grupo_sem_formato_gc(self):
        payload = {
            'isGroup': True,
            'phone': '120363349227318284-group',
            'type': 'ReceivedCallback',
            'text': {'message': 'Bom dia'},
        }
        out = avaliar_fastpath_zapi(payload)
        self.assertEqual(out['status'], 'ok')
        self.assertIn('grupo', out['mensagem'].lower())

    def test_grupo_com_resposta_gc_vai_para_handler(self):
        payload = {
            'isGroup': True,
            'phone': '120363349227318284-group',
            'participantPhone': '5531999999999',
            'type': 'ReceivedCallback',
            'text': {'message': '12345, antecipada'},
        }
        self.assertIsNone(avaliar_fastpath_zapi(payload))

    def test_ignora_from_me(self):
        payload = {
            'fromMe': True,
            'phone': '5511999999999',
            'text': {'message': 'oi'},
        }
        out = avaliar_fastpath_zapi(payload)
        self.assertEqual(out['status'], 'ok')
        self.assertIn('bot', out['mensagem'].lower())

    def test_mensagem_direta_nao_ignora(self):
        payload = {
            'phone': '5511999999999',
            'type': 'ReceivedCallback',
            'text': {'message': 'Fachada'},
        }
        self.assertIsNone(avaliar_fastpath_zapi(payload))
