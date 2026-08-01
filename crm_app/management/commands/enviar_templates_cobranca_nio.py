"""
Dispara templates Meta de cobrança Nio (D−5, D+5, recorrente a cada 7 dias).

Uso:
  python manage.py enviar_templates_cobranca_nio
  python manage.py enviar_templates_cobranca_nio --dry-run
  python manage.py enviar_templates_cobranca_nio --limite 20
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from crm_app.models import FaturaM10, HistoricoEnvioQualidade
from crm_app.services.qualidade_service import enviar_cobranca_whatsapp, pode_tratar_contrato


class Command(BaseCommand):
    help = "Envia templates Meta de cobrança (lembrete D−5, vencida D+5, recorrente)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Só lista, não envia")
        parser.add_argument("--limite", type=int, default=50, help="Máximo de envios nesta execução")
        parser.add_argument(
            "--apenas",
            choices=["d5_antes", "d5_depois", "recorrente", "todos"],
            default="todos",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry = bool(options["dry_run"])
        limite = max(1, int(options["limite"]))
        apenas = options["apenas"]
        hoje = timezone.localdate()
        enviados = 0
        erros = 0

        alvos: list[tuple[str, FaturaM10]] = []

        if apenas in ("d5_antes", "todos"):
            alvo = hoje + timedelta(days=5)
            qs = self._qs_base().filter(data_vencimento=alvo)
            for f in qs[: limite * 2]:
                alvos.append(("d5_antes", f))

        if apenas in ("d5_depois", "todos"):
            alvo = hoje - timedelta(days=5)
            qs = self._qs_base().filter(data_vencimento=alvo)
            for f in qs[: limite * 2]:
                alvos.append(("d5_depois", f))

        if apenas in ("recorrente", "todos"):
            # D+12, D+19, D+26… (a cada 7 dias após D+5)
            for k in range(1, 8):
                dias = 5 + 7 * k
                alvo = hoje - timedelta(days=dias)
                qs = self._qs_base().filter(data_vencimento=alvo)
                for f in qs[: limite]:
                    alvos.append(("recorrente", f))

        vistos: set[int] = set()
        for tipo, fatura in alvos:
            if enviados >= limite:
                break
            if fatura.id in vistos:
                continue
            if self._ja_enviou_hoje(fatura):
                continue
            contrato = fatura.contrato
            if not pode_tratar_contrato(contrato):
                continue
            vistos.add(fatura.id)
            self.stdout.write(
                f"[{tipo}] fatura={fatura.id} contrato={contrato.id} "
                f"venc={fatura.data_vencimento} valor={fatura.valor}"
            )
            if dry:
                enviados += 1
                continue
            result = enviar_cobranca_whatsapp(
                contrato.id,
                fatura.id,
                user=None,
                modo="template",
            )
            if result.get("ok"):
                enviados += 1
                self.stdout.write(self.style.SUCCESS(f"  ok canal={result.get('canal')}"))
            else:
                erros += 1
                self.stdout.write(self.style.ERROR(f"  falha: {result.get('erro')}"))

        self.stdout.write(
            self.style.NOTICE(f"Concluído: enviados={enviados} erros={erros} dry_run={dry}")
        )

    def _qs_base(self):
        return (
            FaturaM10.objects.filter(
                status__in=["NAO_PAGO", "ATRASADO", "AGUARDANDO"],
            )
            .exclude(status="PAGO")
            .select_related("contrato")
            .order_by("id")
        )

    def _ja_enviou_hoje(self, fatura: FaturaM10) -> bool:
        inicio = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        return HistoricoEnvioQualidade.objects.filter(
            fatura=fatura,
            canal="WHATSAPP",
            sucesso=True,
            criado_em__gte=inicio,
        ).filter(Q(mensagem__icontains="template") | Q(mensagem__startswith="[")).exists()
