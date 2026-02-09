# crm_app/cadastro_venda_pap.py
"""
Cadastro de vendas PAP no CRM.
Usado pelo fluxo WhatsApp e pelo teste via terminal.
"""
import logging

logger = logging.getLogger(__name__)


def cadastrar_venda_pap_no_crm(dados: dict, numero_os: str, matricula_vendedor: str = None, vendedor=None) -> bool:
    """
    Cadastra a venda no CRM após conclusão no PAP.

    Args:
        dados: dados_pedido com cpf_cliente, nome_cliente, cep, numero, etc.
        numero_os: Número da O.S. extraído do modal Sucesso.
        matricula_vendedor: Matrícula PAP do vendedor (para buscar Usuario).
        vendedor: Usuario vendedor (se já disponível).

    Returns:
        True se cadastrou com sucesso.
    """
    try:
        from crm_app.models import Venda, Cliente, Plano, FormaPagamento, StatusCRM
        from usuarios.models import Usuario
        from django.utils import timezone

        logger.info(f"[CRM] Cadastrando venda PAP - OS: {numero_os}")

        if not vendedor and matricula_vendedor:
            vendedor = Usuario.objects.filter(
                matricula_pap=matricula_vendedor
            ).filter(is_active=True).first()
        if not vendedor:
            # Fallback: usar primeiro vendedor com matrícula PAP
            vendedor = Usuario.objects.filter(
                matricula_pap__isnull=False
            ).exclude(matricula_pap="").filter(is_active=True).first()
        if not vendedor:
            logger.warning("[CRM] Nenhum vendedor encontrado para cadastrar venda PAP")
            return False

        cpf = dados.get("cpf_cliente", "")
        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf,
            defaults={
                "nome_razao_social": dados.get("nome_cliente", f"Cliente {cpf}"),
                "telefone1": dados.get("celular", ""),
                "email": dados.get("email", ""),
            },
        )
        if not created and not cliente.email:
            cliente.email = dados.get("email", "")
            cliente.save()

        plano_map = {
            "1giga": "Nio Fibra Ultra 1 Giga",
            "700mega": "Nio Fibra Super 700 Mega",
            "500mega": "Nio Fibra Essencial 500 Mega",
        }
        plano_nome = plano_map.get(dados.get("plano", ""), "Nio Fibra Essencial 500 Mega")
        plano = Plano.objects.filter(
            nome__icontains=plano_nome.split()[2] if len(plano_nome.split()) > 2 else plano_nome
        ).first()

        forma_map = {
            "boleto": "Boleto",
            "cartao": "Cartão",
            "debito": "Débito",
        }
        forma_nome = forma_map.get(dados.get("forma_pagamento", ""), "Boleto")
        forma_pagamento = FormaPagamento.objects.filter(nome__icontains=forma_nome).first()

        status_agendada = StatusCRM.objects.filter(
            tipo="Esteira", nome__icontains="AGENDAD"
        ).first()

        data_nasc = None
        mes_nasc = dados.get("mes_nascimento")
        try:
            mn = int(mes_nasc) if mes_nasc is not None else None
        except (TypeError, ValueError):
            mn = None
        if mn is not None and 1 <= mn <= 12:
            from datetime import date

            data_nasc = date(1900, mn, 1)

        venda = Venda.objects.create(
            cliente=cliente,
            vendedor=vendedor,
            plano=plano,
            forma_pagamento=forma_pagamento,
            status_esteira=status_agendada,
            ordem_servico=numero_os,
            cep=dados.get("cep", ""),
            numero_residencia=dados.get("numero", ""),
            ponto_referencia=dados.get("referencia", ""),
            nome_mae=dados.get("nome_mae") or None,
            data_nascimento=data_nasc,
            tem_fixo=dados.get("tem_fixo", False),
            banco_dacc=dados.get("banco_dacc") or None,
            agencia_dacc=dados.get("agencia_dacc") or None,
            conta_dacc=dados.get("conta_dacc") or None,
            digito_dacc=dados.get("digito_dacc") or None,
            observacao=f"Venda realizada via PAP em {timezone.now().strftime('%d/%m/%Y %H:%M')}",
            ativo=True,
        )

        logger.info(f"[CRM] Venda cadastrada com sucesso! ID: {venda.id}, OS: {numero_os}")
        return True

    except Exception as e:
        logger.exception(f"[CRM] Erro ao cadastrar venda PAP: {e}")
        return False
