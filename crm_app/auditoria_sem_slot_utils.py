"""Utilitários para comunicação GC — agenda disponível não atende o cliente (auditoria)."""
import base64
import logging

from django.contrib.auth import get_user_model

from .models import AnteciparInstalacaoConfig, AuditoriaSemSlotGC
from .whatsapp_service import WhatsAppService


def _get_config_gc():
    config = AnteciparInstalacaoConfig.objects.first()
    if not config:
        config = AnteciparInstalacaoConfig.objects.create(telefone_gc='', nome_gc='')
    return config


def _imagem_para_data_url_e_bytes(uploaded):
    if not uploaded:
        return None, None, None, 'Imagem do print do PAP é obrigatória.'
    raw = uploaded.read()
    if len(raw) > 6 * 1024 * 1024:
        return None, None, None, 'Imagem muito grande (máx. 6 MB).'
    ct = (uploaded.content_type or '').lower().split(';')[0].strip()
    if ct not in ('image/jpeg', 'image/jpg', 'image/png', 'image/webp'):
        return None, None, None, 'Use imagem JPG, PNG ou WEBP.'
    if 'png' in ct:
        mime = 'image/png'
    elif 'webp' in ct:
        mime = 'image/webp'
    else:
        mime = 'image/jpeg'
    b64 = base64.b64encode(raw).decode('ascii')
    data_url = f"data:{mime};base64,{b64}"
    nome = getattr(uploaded, 'name', 'print_pap.jpg') or 'print_pap.jpg'
    return data_url, raw, nome, None

logger = logging.getLogger(__name__)

TURNO_LABEL = {'MANHA': 'Manhã', 'TARDE': 'Tarde'}

PERFIS_AUDITORIA = ['Diretoria', 'Admin', 'BackOffice', 'Supervisor', 'Auditoria', 'Qualidade']


def endereco_completo_venda(venda):
    """Monta endereço no mesmo padrão da aba 3 da auditoria."""
    parts = []
    if venda.logradouro:
        parts.append((venda.logradouro or '').strip().title())
    if venda.numero_residencia:
        parts.append(str(venda.numero_residencia).strip())
    comp = (venda.complemento or '').strip()
    if comp:
        parts.append(comp.title())
    bairro = (venda.bairro or '').strip()
    cidade = (venda.cidade or '').strip()
    uf = (venda.estado or '').strip().upper()
    cep = (venda.cep or '').strip()
    if bairro or cidade:
        loc = bairro.title() if bairro else ''
        if cidade:
            loc = f"{loc}, {cidade.title()}" if loc else cidade.title()
        if uf:
            loc = f"{loc} - {uf}"
        parts.append(loc)
    elif uf:
        parts.append(uf)
    if cep:
        parts.append(cep)
    ref = (venda.ponto_referencia or '').strip()
    if ref:
        parts.append(ref.title())
    return ', '.join(p for p in parts if p)


def endereco_completo_dict(dados):
    """Monta endereço a partir do dict coletado no frontend (auditoria)."""

    class _End:
        pass

    v = _End()
    v.logradouro = dados.get('logradouro', '')
    v.numero_residencia = dados.get('numero') or dados.get('numero_residencia', '')
    v.complemento = dados.get('complemento', '')
    v.bairro = dados.get('bairro', '')
    v.cidade = dados.get('cidade', '')
    v.estado = dados.get('estado') or dados.get('uf', '')
    v.cep = dados.get('cep', '')
    v.ponto_referencia = dados.get('referencia', '')
    return endereco_completo_venda(v)


def formatar_telefones_contato(tel1, tel2):
    t1 = (tel1 or '').strip()
    t2 = (tel2 or '').strip()
    if t1 and t2:
        return f"{t1} e {t2}"
    return t1 or t2 or ''


def montar_mensagem_sem_slot(uf, ordem_servico, endereco, data_desejada, turno_desejado, telefones):
    turno_txt = TURNO_LABEL.get((turno_desejado or '').upper(), turno_desejado or '')
    if hasattr(data_desejada, 'strftime'):
        data_txt = data_desejada.strftime('%d/%m/%Y')
    else:
        data_txt = str(data_desejada or '')
    return (
        f"Sem SLOT em {(uf or '').upper()}\n\n"
        f"Pedido: {ordem_servico}\n"
        f"Endereço: {endereco}\n"
        f"Data e turno que o cliente deseja: {data_txt} - {turno_txt}\n"
        f"Tel. de contato: {telefones}"
    )


def destinatarios_gc_e_diretoria():
    """Telefone do GC (config) + WhatsApp de usuários ativos do perfil Diretoria."""
    config = _get_config_gc()
    telefone_gc = (config.telefone_gc or '').strip()
    User = get_user_model()
    diretoria_users = User.objects.filter(
        groups__name='Diretoria', is_active=True,
    ).distinct()
    diretoria_tels = []
    vistos = set()
    if telefone_gc:
        vistos.add(''.join(c for c in telefone_gc if c.isdigit()))
    for u in diretoria_users:
        tel = (getattr(u, 'tel_whatsapp', None) or '').strip()
        if not tel:
            continue
        key = ''.join(c for c in tel if c.isdigit())
        if key and key not in vistos:
            vistos.add(key)
            diretoria_tels.append(tel)
    return telefone_gc, diretoria_tels


def validar_endereco_completo_venda(venda):
    campos = [
        ('CEP', venda.cep),
        ('Logradouro', venda.logradouro),
        ('Número', venda.numero_residencia),
        ('Bairro', venda.bairro),
        ('Cidade', venda.cidade),
        ('UF', venda.estado),
    ]
    faltando = [nome for nome, val in campos if not (val and str(val).strip())]
    return faltando


def processar_envio_sem_slot(
    *,
    usuario,
    venda,
    ordem_servico,
    uf,
    endereco,
    data_agendamento_cadastrada,
    turno_agendamento_cadastrado,
    data_desejada_cliente,
    turno_desejado_cliente,
    telefone_contato,
    imagem_upload,
):
    """
    Envia imagem com legenda (texto completo) ao GC e à Diretoria via Z-API.
    Se a mensagem exceder o limite da legenda, envia texto e imagem separados.
    Persiste AuditoriaSemSlotGC. Retorna (registro, sucesso_parcial, mensagem_resumo).
    """
    from django.core.files.base import ContentFile

    img_data_url, img_bytes, img_nome, img_err = _imagem_para_data_url_e_bytes(imagem_upload)
    if img_err:
        return None, False, img_err

    mensagem = montar_mensagem_sem_slot(
        uf, ordem_servico, endereco, data_desejada_cliente,
        turno_desejado_cliente, telefone_contato,
    )
    telefone_gc, tels_diretoria = destinatarios_gc_e_diretoria()
    destinos = []
    if telefone_gc:
        destinos.append(('gc', telefone_gc))
    for i, tel in enumerate(tels_diretoria):
        destinos.append((f'diretoria_{i}', tel))

    if not destinos:
        return None, False, 'Nenhum destino configurado (telefone GC ou Diretoria com WhatsApp).'

    enviado_gc = False
    enviados_diretoria = []
    erros = []
    # WhatsApp limita legenda da imagem (~1024 caracteres)
    caption_max = 1024
    usar_legenda_completa = len(mensagem) <= caption_max
    caption_img = mensagem if usar_legenda_completa else f"Print PAP — Pedido {ordem_servico}"

    try:
        svc = WhatsAppService()
        for tipo, telefone in destinos:
            if not img_data_url:
                erros.append(f'{tipo}: imagem ausente')
                continue
            if not usar_legenda_completa:
                ok_txt, resp_txt = svc.enviar_mensagem_texto(telefone, mensagem)
                if not ok_txt:
                    erros.append(f'{tipo}: texto — {resp_txt}')
            ok_img = svc.enviar_imagem_b64(telefone, img_data_url, caption=caption_img)
            if not ok_img:
                erros.append(f'{tipo}: imagem — falha no envio')
                continue
            if tipo == 'gc':
                enviado_gc = True
            elif tipo.startswith('diretoria'):
                enviados_diretoria.append(telefone)
    except Exception as e:
        logger.exception("Erro ao enviar WhatsApp sem slot: %s", e)
        erros.append(str(e))

    create_kw = dict(
        usuario=usuario,
        venda=venda,
        ordem_servico=ordem_servico or '',
        uf=(uf or '').upper()[:2],
        endereco_completo=endereco or '',
        data_agendamento_cadastrada=data_agendamento_cadastrada,
        turno_agendamento_cadastrado=turno_agendamento_cadastrado or '',
        data_desejada_cliente=data_desejada_cliente,
        turno_desejado_cliente=turno_desejado_cliente,
        telefone_contato=telefone_contato or '',
        mensagem_enviada=mensagem[:4000],
        enviado_gc=enviado_gc,
        enviados_diretoria=enviados_diretoria,
        erros=erros,
    )
    if img_bytes is not None:
        create_kw['imagem_anexo'] = ContentFile(img_bytes, name=img_nome or 'print_pap.jpg')
    registro = AuditoriaSemSlotGC.objects.create(**create_kw)

    sucesso = enviado_gc or bool(enviados_diretoria)
    if sucesso and erros:
        msg = 'Enviado com avisos: ' + '; '.join(erros[:3])
    elif sucesso:
        msg = (
            'Comunicação enviada ao GC e à Diretoria (texto na legenda da imagem).'
            if usar_legenda_completa
            else 'Comunicação enviada ao GC e à Diretoria (texto e imagem em mensagens separadas — legenda muito longa).'
        )
    else:
        msg = 'Falha no envio: ' + ('; '.join(erros) if erros else 'erro desconhecido')
    return registro, sucesso, msg
