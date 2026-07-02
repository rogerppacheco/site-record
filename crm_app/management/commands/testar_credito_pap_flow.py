# crm_app/management/commands/testar_credito_pap_flow.py
"""
Teste local do fluxo CRÉDITO completo (espelha _executar_analise_credito_background).

Uso:
  python manage.py testar_credito_pap_flow --cpf 05623705600
  python manage.py testar_credito_pap_flow --cpf 05623705600 --headless
  python manage.py testar_credito_pap_flow --cpf 05623705600 --slow-mo 500 --no-fast
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional, Tuple

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Executa fluxo CRÉDITO PAP local (etapas 1–4), espelhando produção"

    def add_arguments(self, parser):
        parser.add_argument("--cpf", type=str, default="05623705600", help="CPF/CNPJ para etapa 3")
        parser.add_argument("--matricula-bo", type=str, help="Matrícula BO (login PAP)")
        parser.add_argument("--senha-bo", type=str, help="Senha BO")
        parser.add_argument(
            "--headless",
            action="store_true",
            help="Navegador headless (igual produção Railway)",
        )
        parser.add_argument(
            "--no-fast",
            action="store_true",
            help="Desativa PAP_CREDITO_FAST_MODE (timeouts maiores)",
        )
        parser.add_argument(
            "--slow-mo",
            type=int,
            default=0,
            help="Pausa em ms entre ações Playwright (útil com navegador visível)",
        )
        parser.add_argument(
            "--trace",
            action="store_true",
            help="Grava trace Playwright em downloads/pap_trace_*.zip",
        )

    def handle(self, *args, **options):
        import django

        django.setup()

        from django.conf import settings
        from usuarios.models import Usuario
        from crm_app.controle_tts_service import (
            obter_matricula_tt_para_credito_pap,
            pular_tt_credito_indisponivel,
            registrar_uso_tt_credito,
        )
        from crm_app.credito_utils import gerar_celular_random, gerar_email_credito
        from crm_app.services_pap_nio import PAPNioAutomation
        from crm_app.whatsapp_webhook_handler import (
            CREDITO_CEP_FIXO,
            CREDITO_ENDERECO_ALVO,
            CREDITO_NUMERO_FIXO,
            CREDITO_REFERENCIA_FIXA,
            _run_orm_returning,
        )

        documento_limpo = re.sub(r"\D", "", options.get("cpf") or "")
        if len(documento_limpo) not in (11, 14):
            self.stdout.write(self.style.ERROR("CPF/CNPJ inválido (11 ou 14 dígitos)"))
            return

        matricula_bo = options.get("matricula_bo")
        senha_bo = options.get("senha_bo")
        if not matricula_bo or not senha_bo:
            bo = (
                Usuario.objects.filter(
                    perfil__cod_perfil__iexact="backoffice",
                    is_active=True,
                    matricula_pap__isnull=False,
                )
                .exclude(matricula_pap="")
                .exclude(senha_pap__isnull=True)
                .exclude(senha_pap="")
                .first()
            )
            if bo:
                matricula_bo = matricula_bo or bo.matricula_pap
                senha_bo = senha_bo or bo.senha_pap
                self.stdout.write(f"BO: {bo.username} ({matricula_bo})")

        if not matricula_bo or not senha_bo:
            self.stdout.write(self.style.ERROR("Informe --matricula-bo e --senha-bo"))
            return

        headless = bool(options.get("headless"))
        optimize_for_credit = not options.get("no_fast") and getattr(
            settings, "PAP_CREDITO_FAST_MODE", True
        )
        slow_mo = options.get("slow_mo") or (300 if not headless else 0)

        self.stdout.write(self.style.SUCCESS("\n=== TESTE LOCAL: fluxo CRÉDITO PAP ==="))
        self.stdout.write(
            f"  CPF: {documento_limpo} | headless={headless} | fast={optimize_for_credit} | slow_mo={slow_mo}\n"
        )

        pap = PAPNioAutomation(
            matricula_pap=matricula_bo,
            senha_pap=senha_bo,
            vendedor_nome="Teste-Local-Credito",
            headless=headless,
            slow_mo=slow_mo,
            capture_screenshots=not headless,
            optimize_for_credit=optimize_for_credit,
            run_id=f"test_credito_{int(time.time())}",
        )
        if options.get("trace"):
            pap.enable_trace = True

        tempos: dict[str, float] = {}
        t_total = time.time()

        def _log_etapa(nome: str, t0: float) -> None:
            tempos[nome] = round(time.time() - t0, 1)
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"  [{nome}] {tempos[nome]}s (acumulado {round(time.time() - t_total, 1)}s)"
                )
            )

        try:
            t0 = time.time()
            ok, msg = pap.iniciar_sessao()
            if not ok:
                self.stdout.write(self.style.ERROR(f"Login falhou: {msg}"))
                return
            _log_etapa("login", t0)

            matricula_fallback = matricula_bo
            t0 = time.time()
            ok_prep, msg_prep = pap._preparar_novo_pedido_etapa1()
            if not ok_prep:
                self.stdout.write(self.style.ERROR(f"Preparar pedido: {msg_prep}"))
                return

            usar_pool_osab = bool(
                headless or getattr(settings, "PAP_CREDITO_SKIP_LISTA_VENDEDORES", False)
            )
            matriculas_pap: list[str] = []
            if not usar_pool_osab:
                matriculas_pap = pap.listar_matriculas_vendedor_no_pap()
                if not matriculas_pap:
                    pap._cache_matriculas_pap_dropdown = []
                    matriculas_pap = pap.listar_matriculas_vendedor_no_pap(forcar_recarga=True)

            if usar_pool_osab or not matriculas_pap:
                usar_pool_osab = True
                candidatos_pap: list = []
                max_tentativas_tt = 8
                self.stdout.write("  Seleção TT: pool OSAB (sem dropdown)")
            else:
                candidatos_pap = list(matriculas_pap)
                max_tentativas_tt = min(max(5, len(candidatos_pap)), 10)
                self.stdout.write(f"  Vendedores no PDV: {len(candidatos_pap)}")

            excluir_tt: set[str] = set()
            sucesso_pedido = False
            msg_pedido = ""
            matricula_pedido = ""
            for tentativa in range(1, max_tentativas_tt + 1):
                if not usar_pool_osab:
                    cache = pap.obter_cache_matriculas_pap_dropdown()
                    if cache:
                        candidatos_pap = cache
                matricula_pedido = _run_orm_returning(
                    lambda fb=matricula_fallback, ex=set(excluir_tt), cand=None if usar_pool_osab else list(candidatos_pap): obter_matricula_tt_para_credito_pap(
                        fb, excluir=ex, candidatos=cand
                    )
                )
                self.stdout.write(f"  TT tentativa {tentativa}: {matricula_pedido}")
                sucesso_pedido, msg_pedido = pap._concluir_novo_pedido_etapa1(matricula_pedido)
                if sucesso_pedido:
                    _run_orm_returning(lambda m=matricula_pedido: registrar_uso_tt_credito(m))
                    break
                msg_lower = (msg_pedido or "").lower()
                if (
                    tentativa < max_tentativas_tt
                    and (
                        "não encontrada no pap" in msg_lower
                        or "nao encontrada no pap" in msg_lower
                        or "não está entre os" in msg_lower
                        or "não foi possível selecionar o vendedor" in msg_lower
                    )
                ):
                    _run_orm_returning(lambda m=matricula_pedido: pular_tt_credito_indisponivel(m))
                    excluir_tt.add(matricula_pedido)
                    continue
                break

            if not sucesso_pedido:
                self.stdout.write(self.style.ERROR(f"Etapa 1 falhou: {msg_pedido}"))
                return
            _log_etapa("pedido", t0)

            t0 = time.time()
            ok_tela, msg_tela = pap.validar_tela_pronta_para_cep()
            if not ok_tela:
                self.stdout.write(self.style.ERROR(f"Tela CEP: {msg_tela}"))
                return
            _log_etapa("tela", t0)

            cep = CREDITO_CEP_FIXO
            numero = CREDITO_NUMERO_FIXO
            ref = CREDITO_REFERENCIA_FIXA
            t0 = time.time()
            sucesso, msg, extra = pap.etapa2_viabilidade(cep, numero, ref)
            if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
                sucesso, msg, extra = pap.etapa2_credito_selecionar_complemento_e_avancar(cep, numero, 1)

            if not sucesso and isinstance(extra, dict) and extra.get("_codigo") == "MULTIPLOS_ENDERECOS":
                lista = extra.get("lista", [])
                idx = 1
                for item in lista:
                    txt = (item.get("texto") or "").upper()
                    if CREDITO_ENDERECO_ALVO.upper() in txt and numero in txt:
                        idx = item.get("indice", 1)
                        break
                ok_sel, _ = pap.etapa2_selecionar_endereco_instalacao(idx)
                if ok_sel:
                    sucesso, msg, extra = pap.etapa2_preencher_referencia_e_continuar(cep, numero, ref)
                    if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
                        sucesso, msg, extra = pap.etapa2_credito_selecionar_complemento_e_avancar(
                            cep, numero, 1
                        )

            _log_etapa("etapa2", t0)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Etapa 2 falhou: {msg}"))
                return
            self.stdout.write(self.style.SUCCESS(f"  Etapa 2 OK: {msg}"))

            t0 = time.time()
            sucesso, msg, _ = pap.etapa3_cadastro_cliente(documento_limpo)
            _log_etapa("etapa3", t0)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Etapa 3 falhou: {msg}"))
                return
            self.stdout.write(self.style.SUCCESS(f"  Etapa 3 OK: {msg}"))

            cel = gerar_celular_random()
            cel_sec = gerar_celular_random()
            email = gerar_email_credito()
            t0 = time.time()
            resultado_credito: Optional[str] = None
            for tentativa in range(5):
                sucesso, msg, resultado_credito, _ = pap.etapa4_contato(
                    cel, email, celular_secundario=cel_sec, parar_no_modal_credito=True
                )
                if sucesso:
                    break
                if msg in ("TELEFONE_REJEITADO",):
                    cel = gerar_celular_random()
                    cel_sec = gerar_celular_random()
                    continue
                if msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                    email = gerar_email_credito()
                    continue
                break

            _log_etapa("etapa4", t0)
            if not sucesso:
                self.stdout.write(self.style.ERROR(f"Etapa 4 falhou: {msg}"))
                return

            self.stdout.write(self.style.SUCCESS(f"\nCREDITO OK: {resultado_credito or msg}"))
            self.stdout.write(f"Tempos: {tempos} | total={round(time.time() - t_total, 1)}s")

        finally:
            try:
                pap._fechar_sessao()
            except Exception:
                pass
