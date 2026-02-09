# crm_app/management/commands/testar_pap_visivel.py
"""
Teste da automação PAP com navegador VISÍVEL.

Abre o Chromium na tela para você acompanhar cada etapa no site
https://pap.niointernet.com.br/

Uso:
  python manage.py testar_pap_visivel
    -> Modo interativo: pede todos os dados no terminal

  python manage.py testar_pap_visivel --auto
    -> Usa dados de teste automáticos
"""
import re
from django.core.management.base import BaseCommand


def _limpar_numeros(s):
    return re.sub(r"\D", "", s) if s else ""


def _pedir(rotulo, obrigatorio=True, default="", mascara=False):
    """Pede valor no terminal. Se mascara=True, não exibe a digitação (senha)."""
    if default:
        prompt = f"  {rotulo} [{default}]: "
    else:
        prompt = f"  {rotulo}: "
    if mascara:
        import getpass
        v = getpass.getpass(prompt)
    else:
        v = input(prompt).strip()
    v = v or default
    if obrigatorio and not v:
        return None
    return v


class Command(BaseCommand):
    help = "Testa a automação PAP com navegador visível (headless=False)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--matricula-bo",
            type=str,
            help="Matrícula do usuário BackOffice (login PAP)",
        )
        parser.add_argument(
            "--senha-bo",
            type=str,
            help="Senha do usuário BackOffice",
        )
        parser.add_argument(
            "--matricula-vendedor",
            type=str,
            help="Matrícula do vendedor (para seleção no pedido)",
        )
        parser.add_argument(
            "--cep",
            type=str,
            default="01310100",
            help="CEP para teste (default: 01310100)",
        )
        parser.add_argument(
            "--numero",
            type=str,
            default="1000",
            help="Número do endereço (default: 1000)",
        )
        parser.add_argument(
            "--referencia",
            type=str,
            default="Teste automatizado",
            help="Referência do endereço",
        )
        parser.add_argument(
            "--cpf",
            type=str,
            default="",
            help="CPF do cliente (11 dígitos)",
        )
        parser.add_argument(
            "--celular",
            type=str,
            default="11987654321",
            help="Celular com DDD",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="teste@exemplo.com",
            help="E-mail do cliente",
        )
        parser.add_argument(
            "--velocidade",
            type=int,
            default=2,
            help="Segundos de pausa entre etapas (default: 2)",
        )
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Usa dados de teste automáticos (sem pedir input)",
        )

    def handle(self, *args, **options):
        import django
        django.setup()

        from usuarios.models import Usuario
        from crm_app.services_pap_nio import PAPNioAutomation

        auto = options.get("auto", False)
        pausa = options.get("velocidade", 2)

        if auto:
            matricula_bo = options.get("matricula_bo")
            senha_bo = options.get("senha_bo")
            matricula_vendedor = options.get("matricula_vendedor")
            cep = options.get("cep", "01310100")
            numero = options.get("numero", "1000")
            referencia = options.get("referencia", "Teste automatizado")
            cpf = options.get("cpf") or "12345678909"
            celular = options.get("celular", "11987654321")
            email = options.get("email", "teste@exemplo.com")
            forma_pag = "boleto"
            plano = "500mega"
            turno = "manha"
        else:
            self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
            self.stdout.write("  DADOS PARA O TESTE - Digite os dados reais")
            self.stdout.write("=" * 60)

            matricula_bo = options.get("matricula_bo") or _pedir("Matrícula BackOffice (login PAP)")
            senha_bo = options.get("senha_bo") or _pedir("Senha BackOffice", mascara=True)
            matricula_vendedor = options.get("matricula_vendedor") or _pedir("Matrícula do vendedor (no pedido)")

            self.stdout.write("\n--- Endereço ---")
            cep = _pedir("CEP (8 dígitos)", default=options.get("cep", ""))
            numero = _pedir("Número (ou S/N)", default=options.get("numero", ""))
            referencia = _pedir("Referência do endereço", default=options.get("referencia", ""))

            self.stdout.write("\n--- Cliente ---")
            cpf = _pedir("CPF do cliente (11 dígitos)", default=options.get("cpf", ""))
            celular = _pedir("Celular com DDD", default=options.get("celular", ""))
            email = _pedir("E-mail do cliente", default=options.get("email", ""))

            self.stdout.write("\n--- Pagamento e Plano ---")
            fp = _pedir("Forma pagamento (1=Boleto, 2=Cartão, 3=Débito)", default="1")
            forma_pag = {"1": "boleto", "2": "cartao", "3": "debito"}.get(fp, "boleto")
            pl = _pedir("Plano (1=1Giga, 2=700Mega, 3=500Mega)", default="3")
            plano = {"1": "1giga", "2": "700mega", "3": "500mega"}.get(pl, "500mega")
            t = _pedir("Turno (1=Manhã, 2=Tarde)", default="1")
            turno = "manha" if t == "1" else "tarde"

            cep = _limpar_numeros(cep)
            cpf = _limpar_numeros(cpf)
            celular = _limpar_numeros(celular)

            if not all([matricula_bo, senha_bo, matricula_vendedor, cep, numero, referencia, cpf, celular, email]):
                self.stdout.write(self.style.ERROR("Dados obrigatórios faltando. Abortando."))
                return

        # Buscar credenciais do banco se não informadas (só em modo auto)
        if auto and (not matricula_bo or not senha_bo):
            bo = Usuario.objects.filter(
                perfil__cod_perfil__iexact="backoffice",
                is_active=True,
                matricula_pap__isnull=False,
            ).exclude(matricula_pap="").exclude(senha_pap__isnull=True).exclude(senha_pap="").first()
            if bo:
                matricula_bo = bo.matricula_pap
                senha_bo = bo.senha_pap
                self.stdout.write(f"Usando BO: {bo.username} (matrícula {matricula_bo})")
            else:
                self.stdout.write(self.style.ERROR(
                    "Nenhum usuário BackOffice encontrado. Use --matricula-bo e --senha-bo"
                ))
                return

        if auto and not matricula_vendedor:
            vendedor = Usuario.objects.filter(matricula_pap__isnull=False).exclude(matricula_pap="").first()
            matricula_vendedor = vendedor.matricula_pap if vendedor else matricula_bo

        def pausar(msg=""):
            if msg:
                self.stdout.write(self.style.SUCCESS(f"\n>>> {msg}"))
            if auto:
                import time
                self.stdout.write(f"    (aguardando {pausa}s)")
                time.sleep(pausa)
            else:
                input("    Pressione ENTER para continuar...")

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write("  TESTE PAP - NAVEGADOR VISÍVEL")
        self.stdout.write("  O Chromium será aberto na tela.")
        self.stdout.write("=" * 60)
        if not auto:
            input("\nPressione ENTER para abrir o navegador e iniciar...")

        automacao = PAPNioAutomation(
            matricula_pap=matricula_bo,
            senha_pap=senha_bo,
            vendedor_nome="Teste",
            headless=False,
        )

        try:
            # Etapa 0: Login
            self.stdout.write("\n[ETAPA 0] Iniciando sessão e login...")
            sucesso, msg = automacao.iniciar_sessao()
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Falha: {msg}"))
                return
            pausar("Login concluído")

            # Etapa 1: Novo pedido
            self.stdout.write("\n[ETAPA 1] Iniciando novo pedido...")
            sucesso, msg = automacao.iniciar_novo_pedido(matricula_vendedor)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Falha: {msg}"))
                automacao._fechar_sessao()
                return
            pausar("Vendedor selecionado")

            # Etapa 2: Viabilidade
            self.stdout.write(f"\n[ETAPA 2] Consultando viabilidade: CEP {cep}, nº {numero}")
            sucesso, msg, _ = automacao.etapa2_viabilidade(cep, numero, referencia)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Falha: {msg}"))
                automacao._fechar_sessao()
                return
            pausar("Viabilidade OK")

            # Etapa 3: Cadastro cliente
            self.stdout.write(f"\n[ETAPA 3] Cadastrando cliente CPF: {cpf}")
            sucesso, msg, _ = automacao.etapa3_cadastro_cliente(cpf)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Falha: {msg}"))
                automacao._fechar_sessao()
                return
            pausar("Cliente cadastrado")

            # Etapa 4: Contato
            self.stdout.write(f"\n[ETAPA 4] Contato: {celular}, {email}")
            sucesso, msg, _ = automacao.etapa4_contato(celular, email)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Falha: {msg}"))
                automacao._fechar_sessao()
                return
            pausar("Contato e crédito OK")

            # Etapa 5: Pagamento e plano
            self.stdout.write(f"\n[ETAPA 5] Pagamento ({forma_pag}) e plano ({plano})...")
            sucesso, msg = automacao.etapa5_pagamento_plano(forma_pag, plano)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Falha: {msg}"))
                automacao._fechar_sessao()
                return
            pausar("Plano selecionado")

            # Etapa 6: Biometria
            self.stdout.write("\n[ETAPA 6] Verificando biometria...")
            sucesso, msg, biometria_ok = automacao.etapa6_verificar_biometria()
            if not biometria_ok:
                self.stdout.write(self.style.WARNING(
                    f"Biometria pendente: {msg}\n"
                    "O teste para aqui. Em produção, o cliente completa a biometria."
                ))
                input("\nPressione ENTER para fechar o navegador...")
                automacao._fechar_sessao()
                return

            # Etapa 7: Abrir OS
            self.stdout.write(f"\n[ETAPA 7] Abrindo O.S. (turno: {turno})...")
            sucesso, msg, numero_os = automacao.etapa7_abrir_os(turno=turno)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Falha: {msg}"))
                automacao._fechar_sessao()
                return
            pausar(f"O.S. aberta: {numero_os or 'N/A'}")

            self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
            self.stdout.write("  TESTE CONCLUÍDO COM SUCESSO!")
            self.stdout.write("=" * 60)

        except KeyboardInterrupt:
            self.stdout.write("\n\nInterrompido pelo usuário.")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nErro: {e}"))
            import traceback
            traceback.print_exc()
        finally:
            input("\nPressione ENTER para fechar o navegador...")
            automacao._fechar_sessao()
            self.stdout.write("Navegador fechado.\n")
