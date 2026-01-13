from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

# IMPORTAÇÃO DAS VIEWS DE AUTH (DO APP USUARIOS)
from usuarios.views import LoginView, DefinirNovaSenhaView

# IMPORTAÇÕES ESPECÍFICAS DE VIEWS
from .views import (
        buscar_fatura_nio_bonus_m10,
    duplicar_venda,
    # ViewSets
    VendaViewSet, 
    ClienteViewSet, 
    ComissaoOperadoraViewSet,
    ComunicadoViewSet,
    LancamentoFinanceiroViewSet,
    GrupoDisparoViewSet,

    # Views Genéricas (List/Detail)
    OperadoraListCreateView, OperadoraDetailView,
    PlanoListCreateView, PlanoDetailView,
    FormaPagamentoListCreateView, FormaPagamentoDetailView,
    StatusCRMListCreateView, StatusCRMDetailView,
    MotivoPendenciaListCreateView, MotivoPendenciaDetailView,
    RegraComissaoListCreateView, RegraComissaoDetailView,
    CampanhaListCreateView, CampanhaDetailView,
    
    # Dashboards e Importações
    DashboardResumoView,
    VendasStatusCountView,
    ListaVendedoresView,
    ComissionamentoView,
    FecharPagamentoView,
    ReabrirPagamentoView,
    GerarRelatorioPDFView,
    EnviarExtratoEmailView,
    ImportacaoOsabView, ImportacaoOsabDetailView,
    ImportacaoChurnView, ImportacaoChurnDetailView,
    ImportacaoCicloPagamentoView,
    PerformanceVendasView,
    ImportacaoLegadoView,
    ImportacaoAgendamentoView,
    ImportacaoRecompraView,
    LogsImportacaoLegadoView,
    LogsImportacaoAgendamentoView,
    LogsImportacaoFPDView,
    LogsImportacaoOSABView,
    LogsImportacaoDFVView,
    
    # NOVAS VIEWS (Mapas, ZAP, Performance)
    api_verificar_whatsapp,
    api_verificar_email,
    enviar_comissao_whatsapp,
    enviar_resultado_campanha_whatsapp,
    ImportarKMLView,        
    ImportarDFVView,
    WebhookWhatsAppView,  
    listar_grupos_whatsapp_api,
    VerificarPermissaoGestaoView,
    
    # Performance (API e Exportação)
    PainelPerformanceView,
    ExportarPerformanceExcelView,
    EnviarImagemPerformanceView, 
    ConfigurarAutomacaoView,
    
    # View da Página HTML (Render)
    page_painel_performance,
    
    # Relatório Campanha
    relatorio_resultado_campanha,

    # --- NOVAS VIEWS DE CONFIRMAÇÃO E REVERSÃO DE DESCONTOS ---
    PendenciasDescontoView,
    ConfirmarDescontosEmMassaView,
    HistoricoDescontosAutoView,
    ReverterDescontoMassaView,

    # --- CDOI (Record Vertical) ---
    CdoiCreateView,  # Criação
    CdoiListView,    # Listagem (NOVO)
    CdoiUpdateView,  # Edição/Status (NOVO)
    page_cdoi_novo,  # Página HTML
    
    # --- BÔNUS M-10 & FPD ---
    SafraM10ListView,
    DashboardM10View,
    DashboardFPDView,
    ContratoM10DetailView,
    ImportarFPDView,
    ImportarChurnView,
    AtualizarFaturasView,
    ExportarM10View,
    page_bonus_m10,
    NioDividasView,
)

# Importar módulo de views de análise de buscas
from . import views_analise_busca

router = DefaultRouter()
router.register(r'vendas', VendaViewSet, basename='venda')
router.register(r'clientes', ClienteViewSet, basename='cliente')
router.register(r'comissoes-operadora', ComissaoOperadoraViewSet, basename='comissao-operadora')
router.register(r'comunicados', ComunicadoViewSet, basename='comunicados')
router.register(r'grupos-disparo', GrupoDisparoViewSet, basename='grupos-disparo')
router.register(r'lancamentos-financeiros', LancamentoFinanceiroViewSet, basename='lancamentos-financeiros')

urlpatterns = [
    path('', include(router.urls)),
    path('duplicar-venda/', duplicar_venda, name='duplicar-venda'),
        # --- Endpoint para busca automática de fatura NIO (Bonus M-10) ---
        path('bonus-m10/buscar-fatura-nio/', buscar_fatura_nio_bonus_m10, name='buscar-fatura-nio-bonus-m10'),
    
    # --- ROTA DA NOVA CENTRAL DE IMPORTAÇÕES (MENU) ---
    path('importacoes/', TemplateView.as_view(template_name='importacoes.html'), name='central-importacoes'),

    # --- Auth ---
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/definir-senha/', DefinirNovaSenhaView.as_view(), name='definir-senha'),

    # --- Cadastros Gerais ---
    path('operadoras/', OperadoraListCreateView.as_view(), name='operadora-list'),
    path('operadoras/<int:pk>/', OperadoraDetailView.as_view(), name='operadora-detail'),
    
    path('planos/', PlanoListCreateView.as_view(), name='plano-list'),
    path('planos/<int:pk>/', PlanoDetailView.as_view(), name='plano-detail'),

    path('formas-pagamento/', FormaPagamentoListCreateView.as_view(), name='forma-pagamento-list'),
    path('formas-pagamento/<int:pk>/', FormaPagamentoDetailView.as_view(), name='forma-pagamento-detail'),

    path('campanhas/', CampanhaListCreateView.as_view(), name='campanha-list'),
    path('campanhas/<int:pk>/', CampanhaDetailView.as_view(), name='campanha-detail'),
    
    path('campanhas/<int:campanha_id>/resultado/', relatorio_resultado_campanha, name='resultado-campanha'),
    path('campanhas/enviar-resultado-whatsapp/', enviar_resultado_campanha_whatsapp, name='enviar-resultado-campanha-whatsapp'),

    path('status/', StatusCRMListCreateView.as_view(), name='status-list'),
    path('status/<int:pk>/', StatusCRMDetailView.as_view(), name='status-detail'),
    
    path('motivos-pendencia/', MotivoPendenciaListCreateView.as_view(), name='motivo-list'),
    path('motivos-pendencia/<int:pk>/', MotivoPendenciaDetailView.as_view(), name='motivo-detail'),

    path('regras-comissao/', RegraComissaoListCreateView.as_view(), name='regra-list'),
    path('regras-comissao/<int:pk>/', RegraComissaoDetailView.as_view(), name='regra-detail'),

    # --- Dashboards e Utilitários ---
    path('dashboard-resumo/', DashboardResumoView.as_view(), name='dashboard-resumo'),
    path('vendas-status-count/', VendasStatusCountView.as_view(), name='vendas-status-count'),
    path('lista-vendedores/', ListaVendedoresView.as_view(), name='lista-vendedores'),
    
    # --- Comissionamento ---
    path('comissionamento/', ComissionamentoView.as_view(), name='comissionamento'),
    path('fechar-pagamento/', FecharPagamentoView.as_view(), name='fechar-pagamento'),
    path('reabrir-pagamento/', ReabrirPagamentoView.as_view(), name='reabrir-pagamento'),
    path('gerar-relatorio-pdf/', GerarRelatorioPDFView.as_view(), name='gerar-relatorio-pdf'),
    path('enviar-extrato-email/', EnviarExtratoEmailView.as_view(), name='enviar-extrato-email'),
    path('comissionamento/whatsapp/', enviar_comissao_whatsapp, name='enviar-whatsapp-comissao'),
    
    # --- NOVAS ROTAS DE CONFIRMAÇÃO E REVERSÃO ---
    path('comissionamento/pendencias-desconto/', PendenciasDescontoView.as_view(), name='pendencias-desconto'),
    path('comissionamento/confirmar-descontos/', ConfirmarDescontosEmMassaView.as_view(), name='confirmar-descontos'),
    path('comissionamento/historico-auto/', HistoricoDescontosAutoView.as_view(), name='historico-auto'),
    path('comissionamento/reverter-auto/', ReverterDescontoMassaView.as_view(), name='reverter-auto'),

    # --- Importações ---
    path('import/osab/', ImportacaoOsabView.as_view(), name='importacao-osab'),
    path('import/osab/<int:pk>/', ImportacaoOsabDetailView.as_view(), name='importacao-osab-detail'),
    path('import/churn/', ImportacaoChurnView.as_view(), name='importacao-churn'),
    path('import/churn/<int:pk>/', ImportacaoChurnDetailView.as_view(), name='importacao-churn-detail'),
    path('import/ciclo-pagamento/', ImportacaoCicloPagamentoView.as_view(), name='importacao-ciclo-pagamento'),
    
    # --- Mapas e ZAP ---
    path('importar-kml/', ImportarKMLView.as_view(), name='importar-kml'),
    path('importar-dfv/', ImportarDFVView.as_view(), name='importar-dfv'),
    # Webhook WhatsApp - URL para configurar no Z-API:
    # Produção: https://www.recordpap.com.br/api/crm/webhook-whatsapp/
    # Alternativa: https://site-record-production.up.railway.app/api/crm/webhook-whatsapp/
    path('webhook-whatsapp/', WebhookWhatsAppView.as_view(), name='webhook-whatsapp'),
    
    # Validação WhatsApp (Duas rotas para compatibilidade)
    path('verificar-zap/<str:telefone>/', api_verificar_whatsapp, name='verificar-zap-path'), # Rota antiga
    path('whatsapp/verificar/', api_verificar_whatsapp, name='verificar-zap-query'),          # Rota nova do CDOI
    
    # Validação E-mail
    path('verificar-email/<str:email>/', api_verificar_email, name='verificar-email'),
    
    # --- Performance ---
    path('relatorios/performance-vendas/', PerformanceVendasView.as_view(), name='performance-vendas'),
    path('performance-painel/', PainelPerformanceView.as_view(), name='api-performance-painel'),
    path('performance-painel/exportar/', ExportarPerformanceExcelView.as_view(), name='exportar-performance-excel'),
    path('performance-painel/enviar-whatsapp/', EnviarImagemPerformanceView.as_view(), name='enviar-performance-zap'),
    path('integracao/listar-grupos/', listar_grupos_whatsapp_api, name='listar-grupos-zapi'),
    path('verificar-permissao-gestao/', VerificarPermissaoGestaoView.as_view(), name='verificar-permissao-gestao'),
    path('import/legado/', ImportacaoLegadoView.as_view(), name='importacao-legado'),
    path('import/agendamento/', ImportacaoAgendamentoView.as_view(), name='importacao-agendamento'),
    path('import/recompra/', ImportacaoRecompraView.as_view(), name='importacao-recompra'),
    
    # --- Logs de Importações ---
    path('logs-legado/', LogsImportacaoLegadoView.as_view(), name='logs-legado'),
    path('logs-agendamento/', LogsImportacaoAgendamentoView.as_view(), name='logs-agendamento'),
    path('logs-fpd/', LogsImportacaoFPDView.as_view(), name='logs-fpd'),
    path('logs-osab/', LogsImportacaoOSABView.as_view(), name='logs-osab'),
    path('logs-dfv/', LogsImportacaoDFVView.as_view(), name='logs-dfv'),
    
    # --- ROTAS EXTRAS ---
    path('grupos-disparo-api/', listar_grupos_whatsapp_api, name='listar_grupos_api'),
    path('automacao-performance/', ConfigurarAutomacaoView.as_view(), name='automacao_performance'),
    path('enviar-imagem-performance/', EnviarImagemPerformanceView.as_view(), name='enviar_imagem_performance'),
    
    # --- CDOI (Record Vertical) ---
    path('cdoi/novo/', CdoiCreateView.as_view(), name='api-cdoi-novo'),
    path('cdoi/listar/', CdoiListView.as_view(), name='api-cdoi-listar'),
    path('cdoi/editar/<int:pk>/', CdoiUpdateView.as_view(), name='api-cdoi-editar'),

    # --- Integração Nio (dívidas/PIX/barras) ---
    path('nio/dividas/', NioDividasView.as_view(), name='nio-dividas'),
    
    # --- Análise de Buscas de Faturas ---
    path('analise-buscas/', views_analise_busca.AnaliseBuscasView.as_view(), name='analise-buscas'),
    path('analise-buscas/metricas-tempo-real/', views_analise_busca.MetricasTempoRealView.as_view(), name='metricas-tempo-real'),
]