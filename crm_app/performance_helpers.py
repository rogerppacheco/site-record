"""Helpers compartilhados: cores e ordenação do relatório de performance (painel / WhatsApp)."""


def ordem_cluster_performance(cluster):
    """CLUSTER_1 → 1, CLUSTER_2 → 2, CLUSTER_3 → 3; demais por último."""
    if not cluster:
        return 99
    c = str(cluster).strip().upper().replace(' ', '_')
    if c in ('CLUSTER_1', 'CLUSTER1', '1'):
        return 1
    if c in ('CLUSTER_2', 'CLUSTER2', '2'):
        return 2
    if c in ('CLUSTER_3', 'CLUSTER3', '3'):
        return 3
    return 99


def cores_linha_performance(total):
    """
    Faixas de vendas (coluna principal):
    0 vermelho | 1-2 amarelo | 3-5 azul | 6+ verde escuro.
    Retorna (cor_fundo_rgb, cor_texto_rgb).
    """
    n = int(total or 0)
    if n == 0:
        return (248, 215, 218), (132, 32, 41)
    if n <= 2:
        return (255, 243, 205), (102, 77, 3)
    if n <= 5:
        return (207, 226, 255), (8, 66, 152)
    return (20, 108, 67), (255, 255, 255)


def ordenar_lista_performance(lista, key_cluster='cluster', key_nome='nome'):
    """Ordena por cluster (1→2→3) e, dentro do cluster, por nome."""
    return sorted(
        lista,
        key=lambda x: (
            ordem_cluster_performance(x.get(key_cluster)),
            str(x.get(key_nome, '')).upper(),
        ),
    )
