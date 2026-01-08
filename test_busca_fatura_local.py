
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()


from crm_app.services_nio import buscar_fatura_nio_por_cpf

if __name__ == "__main__":
    cpf = input("Digite o CPF para buscar a fatura: ").strip()
    print("[DEBUG] Iniciando busca de fatura para:", cpf)
    resultado = buscar_fatura_nio_por_cpf(cpf, incluir_pdf=True)
    print("[DEBUG] Resultado da busca:", resultado)
