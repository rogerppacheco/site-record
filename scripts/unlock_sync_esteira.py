from django.utils import timezone
from crm_app.models import SyncStatusEsteiraExecucao

updated = SyncStatusEsteiraExecucao.objects.filter(status='em_andamento').update(
    status='interrompido',
    finalizado_em=timezone.now(),
    mensagem_erro='Encerrado manualmente — processo travado',
)
print('updated', updated)
e = SyncStatusEsteiraExecucao.objects.get(pk=1)
print('status', e.status, 'finalizado', e.finalizado_em)
