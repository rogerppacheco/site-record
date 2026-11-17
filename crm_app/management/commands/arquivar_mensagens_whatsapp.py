"""Arquiva mensagens de atendimento WhatsApp mais antigas que N dias.

Mantém a tabela quente enxuta; preview/denormalização da Conversation permanece.
Uso:
  python manage.py arquivar_mensagens_whatsapp
  python manage.py arquivar_mensagens_whatsapp --dias 180 --batch 2000 --dry-run
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from crm_app.models import MensagemWhatsAppAtendimento, MensagemWhatsAppAtendimentoArquivo


class Command(BaseCommand):
    help = "Arquiva MensagemWhatsAppAtendimento com mais de N dias (default 180)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=180)
        parser.add_argument("--batch", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--max-batches", type=int, default=100)

    def handle(self, *args, **options):
        dias = max(30, int(options["dias"]))
        batch = max(50, min(int(options["batch"]), 5000))
        dry = bool(options["dry_run"])
        max_batches = max(1, int(options["max_batches"]))
        limite = timezone.now() - timedelta(days=dias)

        total = MensagemWhatsAppAtendimento.objects.filter(data_hora__lt=limite).count()
        self.stdout.write(
            f"Candidatas a arquivar: {total} (antes de {limite.isoformat()}, dry_run={dry})"
        )
        if total == 0:
            return

        arquivadas = 0
        for _ in range(max_batches):
            ids = list(
                MensagemWhatsAppAtendimento.objects.filter(data_hora__lt=limite)
                .order_by("data_hora", "id")
                .values_list("id", flat=True)[:batch]
            )
            if not ids:
                break
            if dry:
                arquivadas += len(ids)
                self.stdout.write(f"[dry-run] lote de {len(ids)} (acumulado {arquivadas})")
                # Em dry-run não remove; sai após um lote para não loop infinito.
                break

            msgs = list(MensagemWhatsAppAtendimento.objects.filter(id__in=ids))
            with transaction.atomic():
                arquivo_objs = [
                    MensagemWhatsAppAtendimentoArquivo(
                        telefone=m.telefone,
                        conversa_id=m.conversa_id,
                        venda_id=m.venda_id,
                        direcao=m.direcao,
                        tipo=m.tipo,
                        texto=m.texto or "",
                        template_name=m.template_name or "",
                        message_id=m.message_id or "",
                        origem=m.origem or "",
                        sucesso=bool(m.sucesso),
                        erro=m.erro or "",
                        status_entrega=getattr(m, "status_entrega", "") or "",
                        media_url=getattr(m, "media_url", "") or "",
                        media_tipo=getattr(m, "media_tipo", "") or "",
                        enviado_por_id=m.enviado_por_id,
                        data_hora=m.data_hora,
                        origem_pk=m.pk,
                    )
                    for m in msgs
                ]
                MensagemWhatsAppAtendimentoArquivo.objects.bulk_create(
                    arquivo_objs, batch_size=500
                )
                deleted, _ = MensagemWhatsAppAtendimento.objects.filter(id__in=ids).delete()
                arquivadas += deleted

            self.stdout.write(f"Arquivadas {arquivadas}/{total}…")

        self.stdout.write(self.style.SUCCESS(f"Concluído. Arquivadas: {arquivadas}"))
