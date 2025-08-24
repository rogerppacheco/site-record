# core/views.py
from django.views.generic import TemplateView

# View para a página inicial (pública)
class IndexView(TemplateView):
    template_name = 'index.html'

# View para a área interna (requer login)
class AreaInternaView(TemplateView):
    template_name = 'area-interna.html'

# View para a página de governança (requer login)
class GovernancaView(TemplateView):
    template_name = 'governanca.html'

# View para a página de presença (requer login)
class PresencaView(TemplateView):
    template_name = 'presenca.html'

# View para o CRM de Vendas (requer login)
class CrmVendasView(TemplateView):
    template_name = 'crm_vendas.html'

# --- VIEWS QUE ESTAVAM FALTANDO ---
# View para a página de consulta de CPF (pública)
class ConsultaCpfView(TemplateView):
    template_name = 'consulta-cpf.html'

# View para a página de consulta de tratamento (pública)
class ConsultaTratamentoView(TemplateView):
    template_name = 'consulta-tratamento.html'