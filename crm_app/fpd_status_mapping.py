"""
Mapeamento padronizado de status FPD para status interno do sistema
Baseado na especificação do usuário

Mapeamento de DS_STATUS_FATURA (do FPD) → STATUS NO CRM:
- Paga → Paga
- Paga_aguardando_repasse → Paga
- Aguardando_arrecadacao → Não Pago
- Ajustada → Paga
- Erro_nao_recobravel → Não Pago
"""

# Mapeamento de DS_STATUS_FATURA (do FPD) para status interno do sistema
FPD_STATUS_MAP = {
    # Status do FPD → Status interno (segundo mapeamento do usuário)
    'PAGA': 'PAGO',
    'PAGA_AGUARDANDO_REPASSE': 'PAGO',
    'AGUARDANDO_ARRECADACAO': 'NAO_PAGO',
    'AJUSTADA': 'PAGO',
    'ERRO_NAO_RECOBRAVEL': 'NAO_PAGO',
    
    # Variações e casos especiais (retrocompatibilidade)
    'PAGO': 'PAGO',
    'NAO_PAGO': 'NAO_PAGO',
    'ABERTO': 'NAO_PAGO',
    'VENCIDO': 'ATRASADO',
    'AGUARDANDO': 'AGUARDANDO',
}

def normalizar_status_fpd(status_str):
    """
    Normaliza um status vindo do FPD para o sistema interno.
    
    Args:
        status_str: String com o status do FPD
        
    Returns:
        String com status normalizado (PAGO, NAO_PAGO, AGUARDANDO, ATRASADO, OUTROS)
    """
    if not status_str:
        return 'NAO_PAGO'  # Padrão se vazio
    
    # Normalizar: remover espaços, converter para maiúsculas
    status_normalizado = status_str.strip().upper()
    
    # Buscar no mapa
    status_interno = FPD_STATUS_MAP.get(status_normalizado, 'OUTROS')
    
    return status_interno
