"""
Restaura vendas marcadas erroneamente como INSTALADA OUTRO PDV pelo pós-processamento OSAB.

Uso (produção via DATABASE_URL):
  python manage.py corrigir_instalada_outro_pdv_osab --ids 6714,6709,...
  python manage.py corrigir_instalada_outro_pdv_osab --log-osab 111
  python manage.py corrigir_instalada_outro_pdv_osab --log-osab 111 --aplicar
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from crm_app.models import HistoricoAlteracaoVenda, LogImportacaoOSABSnapshotVenda, StatusCRM, Venda


class Command(BaseCommand):
    help = "Restaura vendas de INSTALADA OUTRO PDV para INSTALADA (correção pós-import OSAB)."

    def add_arguments(self, parser):
        parser.add_argument("--ids", type=str, default="", help="IDs separados por vírgula.")
        parser.add_argument("--log-osab", type=int, default=None, help="Log importação OSAB (snapshots AUSENTE_OSAB).")
        parser.add_argument("--aplicar", action="store_true", help="Grava alterações (sem flag: dry-run).")

    def handle(self, *args, **options):
        st_inst = StatusCRM.objects.filter(tipo="Esteira", nome__iexact="INSTALADA").first()
        st_outro = StatusCRM.objects.filter(tipo="Esteira", nome__iexact="INSTALADA OUTRO PDV").first()
        if not st_inst or not st_outro:
            self.stderr.write("Status INSTALADA / INSTALADA OUTRO PDV não encontrados.")
            return

        ids = set()
        if options.get("ids"):
            ids.update(int(x.strip()) for x in options["ids"].split(",") if x.strip())
        log_id = options.get("log_osab")
        if log_id:
            ids.update(
                LogImportacaoOSABSnapshotVenda.objects.filter(
                    log_id=log_id,
                    origem=LogImportacaoOSABSnapshotVenda.ORIGEM_AUSENTE_OSAB,
                ).values_list("venda_id", flat=True)
            )

        if not ids:
            self.stderr.write("Informe --ids ou --log-osab.")
            return

        qs = Venda.objects.filter(id__in=ids, ativo=True, status_esteira=st_outro).select_related(
            "status_esteira"
        )
        self.stdout.write(f"Vendas INSTALADA OUTRO PDV a restaurar: {qs.count()} (dry-run={not options['aplicar']})")

        vendas_ok = []
        historicos = []
        for v in qs.order_by("id"):
            snap_inst = v.data_instalacao
            self.stdout.write(f"  id={v.id} os={v.ordem_servico} data_inst={snap_inst}")
            if not options["aplicar"]:
                continue
            v.status_esteira = st_inst
            vendas_ok.append(v)
            historicos.append(
                HistoricoAlteracaoVenda(
                    venda=v,
                    usuario=None,
                    alteracoes={
                        "status_esteira": (
                            "De 'INSTALADA OUTRO PDV' para 'INSTALADA' "
                            "(correção: pós-processamento OSAB não deve rebaixar INSTALADA)"
                        ),
                    },
                )
            )

        if options["aplicar"] and vendas_ok:
            with transaction.atomic():
                Venda.objects.bulk_update(vendas_ok, ["status_esteira"], batch_size=500)
                HistoricoAlteracaoVenda.objects.bulk_create(historicos, batch_size=500)
            self.stdout.write(self.style.SUCCESS(f"Restauradas {len(vendas_ok)} vendas para INSTALADA."))
