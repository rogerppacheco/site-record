import os
import django

# Set DB vars so we can fetch a valid user
os.environ['DATABASE_UNPOOLED_URL'] = "postgresql://postgres:tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz@maglev.proxy.rlwy.net:56422/railway"
os.environ['DATABASE_URL'] = "postgresql://postgres:tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz@maglev.proxy.rlwy.net:56422/railway"
os.environ['POSTGRES_SCHEMA'] = "public"
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core_config.settings')
django.setup()

from usuarios.models import Usuario
from crm_app.services_pap_nio import PAPNioAutomation

def testar_pap():
    cpf = "02282999690"
    
    # Pegar todos os acessos de BO ativos
    usuarios_bo = Usuario.objects.filter(is_active=True, matricula_pap__isnull=False).exclude(matricula_pap="")
    
    if not usuarios_bo.exists():
        print("Nenhum usuario com acesso PAP encontrado no banco de dados.")
        return
        
    print(f"Iniciando Automacao PAP Visual (headless=False) para CPF {cpf}")
    print(f"Encontrados {usuarios_bo.count()} usuarios com matricula_pap. Testando logins...")
    
    sucesso = False
    msg = ""
    dados = {}
    
    for bo_usuario in usuarios_bo:
        print(f"\n--- Tentando login com: {bo_usuario.username} ({bo_usuario.matricula_pap}) ---")
        
        automacao = PAPNioAutomation(
            matricula_pap=bo_usuario.matricula_pap,
            senha_pap=bo_usuario.senha_pap,
            vendedor_nome="Teste-Visual",
            headless=False,
            capture_screenshots=False,
            optimize_for_credit=False,
        )
        
        sucesso_login, msg_login = automacao.iniciar_sessao()
        
        if sucesso_login:
            print(f"Login efetuado com sucesso usando {bo_usuario.username}! Iniciando consulta...")
            sucesso, msg, dados, extra = automacao.consulta_os_por_cpf_com_resultado(cpf)
            automacao._fechar_sessao()
            break
        else:
            print(f"Falha no login com {bo_usuario.username}: {msg_login}")
            automacao._fechar_sessao()
            continue

    if sucesso:
        print(f"\nResultado da Consulta: Sucesso={sucesso}")
        print(f"Mensagem: {msg}")
        print(f"Dados retornados: {dados}")
    else:
        print("\nTodos os usuarios testados falharam no login PAP!")

if __name__ == "__main__":
    testar_pap()
