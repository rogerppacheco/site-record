import os
import django
from pathlib import Path
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent / '.env'
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.whatsapp_service import WhatsAppService
import base64

def test_zapi():
    wa = WhatsAppService()
    
    img_path = r"c:\Projeto_Sysr\site-record\downloads\consulta_os_1790519721_20260927_113604.png"
    if not os.path.isfile(img_path):
        print(f"File not found: {img_path}")
        return
        
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
    
    print(f"Image size in base64: {len(img_b64)} bytes")
    
    from crm_app.models import SessaoWhatsapp
    s = SessaoWhatsapp.objects.order_by('-updated_at').first()
    if s:
        telefone = s.telefone
        print(f"Testing with phone {telefone}")
        
        caption = (
            "📡 *Status online (PAP)*\n\n"
            "⚠️ Pedido emitido, porém não pertence ao seu PDV.\n\n"
            "• *Status:* CONCLUIDO\n"
            "• *Data:* 22/09/2026 12:30\n"
            "• *Plano:* FIBRA 400MB\n"
            "• *Nº OS:* 123456 - SA-123456\n"
            "• *Status agendamento:* CONCLUIDO\n"
            "• *Agendamento:* 22/09/2026 - Tarde\n"
            "• *Pendência:* NENHUMA\n"
            "\n⏱ _120s_"
        )
        
        print("Enviando imagem com caption real...")
        resp = wa.enviar_imagem_b64(telefone, img_b64, caption=caption)
        print("Response:", resp)
    else:
        print("No phone found to test")

if __name__ == '__main__':
    test_zapi()
