from django.test import SimpleTestCase

from crm_app.pap_link_pagamento import formatar_resultado_link_pagamento


class LinkPagamentoMensagemTests(SimpleTestCase):
    def test_sem_pedido(self):
        texto = formatar_resultado_link_pagamento([], 3.2)
        self.assertIn("Não tem pedido", texto)
        self.assertIn("3.2s", texto)

    def test_link_reenviado_com_contato(self):
        texto = formatar_resultado_link_pagamento(
            [{
                "numero_os": "11815239",
                "link_pagamento": {
                    "ok": True,
                    "whatsapp": "(31) 99793-1645",
                    "email": "cliente@exemplo.com",
                },
            }],
            8,
        )
        self.assertIn("11815239", texto)
        self.assertIn("link reenviado", texto)
        self.assertIn("(31) 99793-1645", texto)
        self.assertIn("cliente@exemplo.com", texto)

    def test_botao_ausente(self):
        texto = formatar_resultado_link_pagamento(
            [{
                "numero_os": "08907507",
                "link_pagamento": {
                    "ok": False,
                    "mensagem": "Botão Enviar link de pagamento não apareceu nesta O.S.",
                },
            }],
            4,
        )
        self.assertIn("não apareceu", texto)
        self.assertNotIn("link reenviado", texto)
