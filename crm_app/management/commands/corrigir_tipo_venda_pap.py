"""
Management command para corrigir tipo_venda incorreto nos registros HistoricoPapPedido.
Uso: python manage.py corrigir_tipo_venda_pap
"""
from django.core.management.base import BaseCommand
from django.db.models import Count


VTAL_TO_INTERNO = {
    "VENDA": "VENDA",
    "CONCLUIDO": "VENDA",
    "concluido": "VENDA",
    "INTERESSE": "INTERESSE",
    "interesse": "INTERESSE",
    "Interesse": "INTERESSE",
    "PRE_VENDA": "PRE_VENDA",
    "PRE-VENDA": "PRE_VENDA",
    "pre_venda": "PRE_VENDA",
}


class Command(BaseCommand):
    help = "Corrige o campo tipo_venda nos registros HistoricoPapPedido com base no payload da Vtal"

    def handle(self, *args, **options):
        from crm_app.models import HistoricoPapPedido

        total = HistoricoPapPedido.objects.count()
        self.stdout.write(f"Total de registros: {total}")

        self.stdout.write("\nDistribuição ATUAL por tipo_venda:")
        for pt in HistoricoPapPedido.objects.values('tipo_venda').annotate(n=Count('id')):
            self.stdout.write(f"  tipo_venda={pt['tipo_venda']}: {pt['n']} registros")

        # Mostra amostra para diagnóstico
        self.stdout.write("\nAmostra dos primeiros 5 payloads:")
        for p in HistoricoPapPedido.objects.all()[:5]:
            payload = p.payload or {}
            tv = payload.get('tipoVenda') or payload.get('tipo_venda') or payload.get('type')
            csp = payload.get('chaveStatusPrimario') or payload.get('status')
            self.stdout.write(
                f"  {p.numero_pedido}: tipo_venda={p.tipo_venda}, "
                f"tipoVenda={tv}, chaveStatus={csp}"
            )

        self.stdout.write("\nCorrigindo registros...")
        corrigidos = 0
        sem_info = 0
        ja_corretos = 0

        todos = HistoricoPapPedido.objects.all()
        for pedido in todos:
            payload = pedido.payload or {}
            tipo_real = None

            tv = payload.get("tipoVenda") or payload.get("tipo_venda") or payload.get("type")
            if tv:
                tipo_real = VTAL_TO_INTERNO.get(str(tv).strip())

            if not tipo_real:
                csp = payload.get("chaveStatusPrimario") or payload.get("status")
                if csp:
                    tipo_real = VTAL_TO_INTERNO.get(str(csp).strip())

            if not tipo_real:
                sem_info += 1
                continue

            if pedido.tipo_venda == tipo_real:
                ja_corretos += 1
                continue

            self.stdout.write(
                f"  Corrigindo {pedido.numero_pedido}: "
                f"{pedido.tipo_venda} -> {tipo_real} (tipoVenda={tv})"
            )
            pedido.tipo_venda = tipo_real
            pedido.save(update_fields=['tipo_venda'])
            corrigidos += 1

        self.stdout.write(f"\n--- Resultado ---")
        self.stdout.write(f"  Corrigidos:    {corrigidos}")
        self.stdout.write(f"  Já corretos:   {ja_corretos}")
        self.stdout.write(f"  Sem info:      {sem_info}")

        self.stdout.write("\nDistribuição APÓS correção:")
        for pt in HistoricoPapPedido.objects.values('tipo_venda').annotate(n=Count('id')):
            self.stdout.write(f"  tipo_venda={pt['tipo_venda']}: {pt['n']} registros")

        self.stdout.write(self.style.SUCCESS("Concluído!"))
