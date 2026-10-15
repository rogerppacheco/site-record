"""Repescagem Bio: base de quem fez ou não a biometria, a partir do relatório detalhado do GED360 (Br Pronto)."""

from __future__ import annotations

import csv
import io
import logging
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from django.db import close_old_connections, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

RELATORIO_URL = 'https://ged360.niointernet.com.br/brprontopdv/relatorios/relatorio-detalhado-de-digitalizacoes'
ORIGEM_POOL = 'repescagem_bio'
TELEFONE_POOL = 'repescagem_bio'
MAX_DIAS_POR_DOWNLOAD = 15
MAX_DIAS_PERIODO = 92
IMPORTACAO_SEM_PROGRESSO_MAX = timedelta(minutes=10)

APTO = 'APTO'
EM_ANALISE = 'EM_ANALISE'
LINK_ENVIADO = 'LINK_ENVIADO'
REFAZER = 'REFAZER'
RISCO = 'RISCO'
SEM_BIOMETRIA = 'SEM_BIOMETRIA'
NAO_VERIFICADO = 'NAO_VERIFICADO'
SITUACOES = (APTO, EM_ANALISE, LINK_ENVIADO, REFAZER, RISCO, SEM_BIOMETRIA, NAO_VERIFICADO)
ROTULOS_SITUACAO = {
    APTO: 'apto',
    EM_ANALISE: 'em análise',
    LINK_ENVIADO: 'link enviado',
    REFAZER: 'refazer',
}

# Venda sem O.S. por mais que isso, com biometria no GED, vira repescagem.
PRAZO_OS = timedelta(hours=48)

# A biometria costuma ser feita minutos antes da venda; envios mais antigos que isso são de outra tentativa.
JANELA_BIO_ANTES_VENDA = timedelta(days=7)
# Para afirmar "sem biometria", o GED precisa ter sido buscado desde este tempo antes da venda até a venda.
COBERTURA_ANTES_VENDA = timedelta(days=1)
# Venda anterior ao último envio por mais que isso não é a venda daquela biometria (é uma tentativa nova).
DISTANCIA_MAX_VENDA_BIO = timedelta(days=30)

COLUNAS_CSV = {
    'protocolo': 'Protocolo',
    'cpf': 'CPF/CNPJ',
    'msisdn': 'MSISDN',
    'data_digitalizacao': 'Data de Digitalização',
    'data_envio': 'Data de Envio',
    'data_conferencia': 'Data de Conferência',
    'codigo_pdv': 'Código PDV',
    'login_digitalizacao': 'Login Digitalização',
    'tipo_servico': 'Tipo de Serviço',
    'origem_digitalizacao': 'Origem da Digitalização',
    'resultado_analise': 'Resultado da Análise',
    'origem_pedido': 'Origem do Pedido de Venda',
    'selfie_capturada': 'Selfie Capturada',
}

_lock_inicio = threading.Lock()


def normalizar_documento(valor) -> str:
    return re.sub(r'\D', '', str(valor or ''))


def _sem_acento(texto: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', str(texto or '')) if not unicodedata.combining(c)).upper()


def classificar_resultado(resultado: str) -> str:
    """Situação de uma etapa a partir do 'Resultado da Análise' do GED."""
    r = _sem_acento(resultado)
    if 'NAO APTO' in r or 'RISCO' in r or 'REPROVADO' in r or 'NAO PASSIVEL' in r:
        return RISCO
    if 'APTO PARA VENDA' in r or r.strip() == 'APROVADO':
        return APTO
    if 'DIGITALIZAR NOVAMENTE' in r or 'AUSENTE' in r or 'ILEGIVEL' in r or 'INCOMPLETO' in r:
        return REFAZER
    if 'LINK ENVIADO' in r:
        return LINK_ENVIADO
    return EM_ANALISE


def consolidar_situacao(etapas: Iterable[dict]) -> str:
    """Situação do CPF: Apto se alguma etapa foi aprovada; senão, a etapa mais recente decide."""
    etapas = list(etapas)
    if not etapas:
        return SEM_BIOMETRIA
    if any(classificar_resultado(e['resultado_analise']) == APTO for e in etapas):
        return APTO
    ultima = max(etapas, key=lambda e: e['data_envio'])
    return classificar_resultado(ultima['resultado_analise'])


def _parse_datahora(valor: str) -> Optional[datetime]:
    s = (valor or '').strip()
    if not s:
        return None
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
        try:
            return timezone.make_aware(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


def _decodificar(conteudo: bytes) -> str:
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return conteudo.decode('latin-1')


def parse_csv(conteudo: bytes) -> list[dict]:
    """Linhas do CSV do GED (cp1252, separador ';') já no formato do RepescagemBioRegistro."""
    texto = _decodificar(conteudo)
    if not texto.strip():
        return []
    leitor = csv.DictReader(io.StringIO(texto), delimiter=';')
    faltando = [c for c in ('Protocolo', 'CPF/CNPJ', 'Data de Envio') if c not in (leitor.fieldnames or [])]
    if faltando:
        raise ValueError(f'CSV do GED sem as colunas {faltando}. Colunas recebidas: {leitor.fieldnames}')
    linhas = []
    for bruto in leitor:
        item = {campo: (bruto.get(coluna) or '').strip() for campo, coluna in COLUNAS_CSV.items()}
        item['cpf'] = normalizar_documento(item['cpf'])
        item['data_envio'] = _parse_datahora(item['data_envio'])
        item['data_digitalizacao'] = _parse_datahora(item['data_digitalizacao'])
        item['data_conferencia'] = _parse_datahora(item['data_conferencia'])
        if not item['protocolo'] or not item['cpf'] or not item['data_envio']:
            continue
        linhas.append(item)
    return linhas


def dividir_periodo(inicio: date, fim: date, dias: int = MAX_DIAS_POR_DOWNLOAD) -> list[tuple[date, date]]:
    partes = []
    atual = inicio
    while atual <= fim:
        parte_fim = min(atual + timedelta(days=dias - 1), fim)
        partes.append((atual, parte_fim))
        atual = parte_fim + timedelta(days=1)
    return partes


def _fora_do_loop(funcao, *args) -> None:
    """O Playwright síncrono mantém um loop async na thread; o ORM do Django recusa rodar dentro dele."""
    erros = []

    def alvo():
        try:
            funcao(*args)
        except Exception as exc:  # noqa: BLE001
            erros.append(exc)
        finally:
            close_old_connections()

    thread = threading.Thread(target=alvo, daemon=True)
    thread.start()
    thread.join()
    if erros:
        raise erros[0]


def baixar_relatorios_ged(login: str, senha: str, dominio: Optional[str], partes: list[tuple[date, date]],
                          ao_avancar=None, headless: bool = True) -> list[bytes]:
    """Faz login no GED uma vez e baixa um CSV por parte do período. Sempre sai da sessão."""
    from playwright.sync_api import sync_playwright

    from crm_app import services_brpronto as sb

    arquivos = []
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=headless)
        contexto = navegador.new_context(viewport={'width': 1400, 'height': 1000}, accept_downloads=True)
        pagina = contexto.new_page()
        pagina.set_default_timeout(120000)
        try:
            erro = sb._login_brpronto(pagina, login, senha, dominio, 60000)
            if erro:
                raise RuntimeError(erro)
            for indice, (inicio, fim) in enumerate(partes, start=1):
                if ao_avancar:
                    _fora_do_loop(ao_avancar, f'Baixando {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} ({indice} de {len(partes)})')
                pagina.goto(RELATORIO_URL, wait_until='domcontentloaded')
                pagina.locator('#dat_envio_inicial').wait_for(state='attached', timeout=30000)
                pagina.evaluate(
                    """([ini, fim]) => {
                        document.getElementById('dat_envio_inicial').value = ini;
                        document.getElementById('dat_envio_final').value = fim;
                    }""",
                    [f'{inicio:%d/%m/%Y}', f'{fim:%d/%m/%Y}'],
                )
                pagina.check('#visualizar-3')
                try:
                    with pagina.expect_download(timeout=180000) as download:
                        pagina.click("input[name='btnFiltrar']")
                    caminho = download.value.path()
                    with open(caminho, 'rb') as arquivo:
                        arquivos.append(arquivo.read())
                except Exception:
                    texto = (pagina.inner_text('body') or '').lower()
                    if 'nenhum registro' in texto or 'não foram encontrados' in texto or 'nao foram encontrados' in texto:
                        arquivos.append(b'')
                        continue
                    raise
        finally:
            try:
                logger.info('[RepescagemBio] Logoff GED: %s', sb._ensure_logout(pagina))
            except Exception as exc:  # noqa: BLE001
                logger.warning('[RepescagemBio] Falha no logoff GED: %s', exc)
            navegador.close()
    return arquivos


def gravar_registros(linhas: list[dict], importacao) -> tuple[int, int]:
    """Insere ou atualiza as etapas pela chave (protocolo, origem, data de envio). Devolve (novos, atualizados)."""
    from crm_app.models import RepescagemBioRegistro as R

    unicas = {}
    for linha in linhas:
        unicas[(linha['protocolo'], linha['origem_digitalizacao'], linha['data_envio'])] = linha
    if not unicas:
        return 0, 0

    protocolos = {chave[0] for chave in unicas}
    existentes = {
        (r.protocolo, r.origem_digitalizacao, r.data_envio): r
        for r in R.objects.filter(protocolo__in=protocolos)
    }
    novos, atualizar = [], []
    campos = [c for c in COLUNAS_CSV if c not in ('protocolo', 'origem_digitalizacao', 'data_envio')]
    for chave, linha in unicas.items():
        registro = existentes.get(chave)
        if registro is None:
            novos.append(R(importacao=importacao, **linha))
            continue
        for campo in campos:
            setattr(registro, campo, linha[campo])
        registro.importacao = importacao
        atualizar.append(registro)
    with transaction.atomic():
        R.objects.bulk_create(novos, batch_size=500)
        if atualizar:
            R.objects.bulk_update(atualizar, campos + ['importacao'], batch_size=500)
    return len(novos), len(atualizar)


def encerrar_importacoes_paradas() -> None:
    from crm_app.models import RepescagemBioImportacao as I

    limite = timezone.now() - IMPORTACAO_SEM_PROGRESSO_MAX
    I.objects.filter(status=I.STATUS_EM_ANDAMENTO, atualizado_em__lt=limite).update(
        status=I.STATUS_ERRO,
        mensagem='Interrompida (servidor reiniciou ou o GED parou de responder). Busque de novo.',
        finalizado_em=timezone.now(),
    )


def importacao_em_andamento():
    from crm_app.models import RepescagemBioImportacao as I

    encerrar_importacoes_paradas()
    return I.objects.filter(status=I.STATUS_EM_ANDAMENTO).order_by('-iniciado_em').first()


def iniciar_importacao(usuario, data_inicial: date, data_final: date):
    """Cria a importação e dispara a thread. Devolve (importacao, criada)."""
    from crm_app.models import RepescagemBioImportacao as I

    with _lock_inicio:
        atual = importacao_em_andamento()
        if atual:
            return atual, False
        importacao = I.objects.create(
            iniciado_por=usuario if getattr(usuario, 'is_authenticated', False) else None,
            data_inicial=data_inicial,
            data_final=data_final,
            etapa='Reservando login do GED…',
        )
    threading.Thread(
        target=_executar_importacao, args=(importacao.pk,), name=f'repescagem-bio-{importacao.pk}', daemon=True,
    ).start()
    return importacao, True


def _executar_importacao(importacao_id: int) -> None:
    from django.conf import settings

    from crm_app.models import RepescagemBioImportacao as I
    from crm_app.pool_brpronto import liberar_login_brpronto, obter_login_brpronto, renovar_login_brpronto

    close_old_connections()
    importacao = I.objects.get(pk=importacao_id)
    bo = None
    try:
        bo, erro_pool = obter_login_brpronto(TELEFONE_POOL, origem=ORIGEM_POOL)
        if not bo:
            raise RuntimeError(re.sub(r'[*_]', '', erro_pool or 'Nenhum login Br Pronto disponível.'))
        importacao.login_ged = bo.brpronto_login or ''
        importacao.etapa = 'Entrando no GED360…'
        importacao.save(update_fields=['login_ged', 'etapa', 'atualizado_em'])

        def ao_avancar(texto: str) -> None:
            importacao.etapa = texto
            importacao.save(update_fields=['etapa', 'atualizado_em'])
            renovar_login_brpronto(bo.id)

        partes = dividir_periodo(importacao.data_inicial, importacao.data_final)
        arquivos = baixar_relatorios_ged(
            bo.brpronto_login or '', bo.brpronto_senha or '', bo.brpronto_dominio or None, partes,
            ao_avancar=ao_avancar, headless=getattr(settings, 'BRPRONTO_HEADLESS', True),
        )
        importacao.etapa = 'Gravando na base…'
        importacao.save(update_fields=['etapa', 'atualizado_em'])
        linhas = [linha for conteudo in arquivos for linha in parse_csv(conteudo)]
        novos, atualizados = gravar_registros(linhas, importacao)
        importacao.linhas = len(linhas)
        importacao.novos = novos
        importacao.atualizados = atualizados
        importacao.cpfs = len({linha['cpf'] for linha in linhas})
        importacao.status = I.STATUS_CONCLUIDO
        importacao.etapa = ''
        importacao.mensagem = (
            f'{len(linhas)} linha(s) do GED: {novos} nova(s), {atualizados} atualizada(s), '
            f'{importacao.cpfs} CPF(s).'
        )
    except Exception as exc:  # noqa: BLE001 — qualquer falha encerra a importação com a mensagem
        logger.exception('[RepescagemBio] Importação %s falhou', importacao_id)
        importacao.status = I.STATUS_ERRO
        importacao.mensagem = f'Falha ao buscar no GED: {exc}'[:1000]
    finally:
        if bo:
            liberar_login_brpronto(bo.id, TELEFONE_POOL)
        importacao.finalizado_em = timezone.now()
        importacao.save()
        close_old_connections()


def serializar_importacao(importacao) -> Optional[dict]:
    if not importacao:
        return None
    return {
        'id': importacao.pk,
        'status': importacao.status,
        'data_inicial': importacao.data_inicial.isoformat(),
        'data_final': importacao.data_final.isoformat(),
        'etapa': importacao.etapa,
        'login_ged': importacao.login_ged,
        'linhas': importacao.linhas,
        'novos': importacao.novos,
        'atualizados': importacao.atualizados,
        'cpfs': importacao.cpfs,
        'mensagem': importacao.mensagem,
        'iniciado_em': importacao.iniciado_em.isoformat() if importacao.iniciado_em else None,
        'finalizado_em': importacao.finalizado_em.isoformat() if importacao.finalizado_em else None,
    }


def _inicio_do_dia(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, datetime.min.time()), timezone.get_current_timezone())


def cobertura_ged() -> list[tuple[datetime, datetime]]:
    """Intervalos já buscados no GED (importações concluídas), unidos. Vai até o início da busca, não além."""
    from crm_app.models import RepescagemBioImportacao as I

    intervalos = []
    for data_inicial, data_final, iniciado_em in I.objects.filter(status=I.STATUS_CONCLUIDO).values_list(
        'data_inicial', 'data_final', 'iniciado_em',
    ):
        fim = _inicio_do_dia(data_final + timedelta(days=1))
        if iniciado_em:
            fim = min(fim, iniciado_em)
        intervalos.append((_inicio_do_dia(data_inicial), fim))
    intervalos.sort()
    unidos: list[list[datetime]] = []
    for ini, fim in intervalos:
        if unidos and ini <= unidos[-1][1]:
            unidos[-1][1] = max(unidos[-1][1], fim)
        else:
            unidos.append([ini, fim])
    return [(ini, fim) for ini, fim in unidos]


def periodo_coberto(inicio: datetime, fim: datetime, cobertura: list[tuple[datetime, datetime]]) -> bool:
    return any(ini <= inicio and fim <= c_fim for ini, c_fim in cobertura)


def _texto_intervalo(delta: timedelta) -> str:
    minutos = int(abs(delta).total_seconds() // 60)
    if minutos < 60:
        return f'{minutos} min'
    if minutos < 48 * 60:
        return f'{minutos // 60} h'
    return f'{minutos // 1440} dias'


def vincular_venda(etapas: list[dict], data_venda: Optional[datetime],
                   cobertura: list[tuple[datetime, datetime]]) -> dict:
    """Cruza os envios do GED de um CPF com a venda do CRM.

    Devolve a situação, se a venda pertence a essas biometrias, os envios considerados e o texto do vínculo
    (ex.: 'apto 6 min antes da venda').
    """
    if data_venda and etapas:
        if data_venda < max(e['data_envio'] for e in etapas) - DISTANCIA_MAX_VENDA_BIO:
            data_venda = None
    if data_venda:
        etapas = [e for e in etapas if e['data_envio'] >= data_venda - JANELA_BIO_ANTES_VENDA]

    if not etapas:
        if data_venda and not periodo_coberto(data_venda - COBERTURA_ANTES_VENDA, data_venda, cobertura):
            return {'situacao': NAO_VERIFICADO, 'venda_vinculada': True, 'etapas': [], 'vinculo': ''}
        return {'situacao': SEM_BIOMETRIA, 'venda_vinculada': bool(data_venda), 'etapas': [], 'vinculo': ''}

    situacao = consolidar_situacao(etapas)
    vinculo = ''
    if data_venda:
        aptas = [e for e in etapas if classificar_resultado(e['resultado_analise']) == APTO]
        decisiva = min(aptas, key=lambda e: e['data_envio']) if aptas else max(etapas, key=lambda e: e['data_envio'])
        delta = data_venda - decisiva['data_envio']
        rotulo = 'apto' if aptas else 'último envio'
        vinculo = f"{rotulo} {_texto_intervalo(delta)} {'antes' if delta >= timedelta(0) else 'depois'} da venda"
    return {'situacao': situacao, 'venda_vinculada': bool(data_venda), 'etapas': etapas, 'vinculo': vinculo}


def avaliar_repescagem(situacao: str, data_venda: Optional[datetime], ordem_servico: str = '',
                       status_tratamento: str = '', agora: Optional[datetime] = None) -> tuple[bool, str]:
    """Repescável: CPF com biometria no GED, sem risco, e sem venda ou com venda sem O.S. há mais de PRAZO_OS.

    data_venda é a da venda vinculada à biometria (vincular_venda). Devolve (repescavel, motivo).
    """
    if situacao in (SEM_BIOMETRIA, NAO_VERIFICADO):
        return False, 'Sem registro no GED'
    if situacao == RISCO:
        return False, 'Biometria reprovada/risco'
    if not data_venda:
        return True, f'Biometria sem venda no CRM ({ROTULOS_SITUACAO.get(situacao, situacao)})'
    os_venda = (ordem_servico or '').strip()
    if os_venda:
        return False, f'Venda com O.S. {os_venda}'
    idade = (agora or timezone.now()) - data_venda
    if idade <= PRAZO_OS:
        return False, f'Aguardando cadastro da O.S. (venda há {int(idade.total_seconds() // 3600)}h)'
    motivo = f'Venda sem O.S. há {idade.days} dias'
    return True, f'{motivo} · tratamento: {status_tratamento}' if status_tratamento else motivo


def montar_base(data_inicial: date, data_final: date) -> list[dict]:
    """Uma linha por CPF: quem enviou biometria no período ou tem venda criada no período, cruzado com o CRM."""
    from crm_app.models import RepescagemBioRegistro as R
    from crm_app.models import Venda

    inicio = _inicio_do_dia(data_inicial)
    fim = _inicio_do_dia(data_final + timedelta(days=1))
    cobertura = cobertura_ged()
    agora = timezone.now()

    cpfs_ged = set(R.objects.filter(data_envio__gte=inicio, data_envio__lt=fim).values_list('cpf', flat=True))
    vendas_periodo = (
        Venda.objects.filter(ativo=True, data_criacao__gte=inicio, data_criacao__lt=fim)
        .exclude(cliente__isnull=True)
        .values_list('cliente__cpf_cnpj', flat=True)
    )
    cpfs = cpfs_ged | {normalizar_documento(c) for c in vendas_periodo if c}
    cpfs.discard('')
    if not cpfs:
        return []

    etapas_por_cpf: dict[str, list[dict]] = {}
    for etapa in R.objects.filter(cpf__in=cpfs).values(
        'cpf', 'protocolo', 'data_envio', 'resultado_analise', 'origem_digitalizacao', 'login_digitalizacao', 'msisdn',
    ):
        etapas_por_cpf.setdefault(etapa['cpf'], []).append(etapa)

    venda_por_cpf: dict[str, dict] = {}
    for venda in (
        Venda.objects.filter(ativo=True, cliente__cpf_cnpj__in=cpfs)
        .order_by('cliente__cpf_cnpj', '-data_criacao')
        .values(
            'id', 'cliente__cpf_cnpj', 'cliente__nome_razao_social', 'data_criacao', 'ordem_servico', 'telefone1',
            'vendedor__username', 'vendedor__first_name', 'status_esteira__nome', 'status_tratamento__nome',
        )
    ):
        venda_por_cpf.setdefault(normalizar_documento(venda['cliente__cpf_cnpj']), venda)

    base = []
    for cpf in cpfs:
        venda = venda_por_cpf.get(cpf)
        cruzamento = vincular_venda(etapas_por_cpf.get(cpf, []), venda['data_criacao'] if venda else None, cobertura)
        if not cruzamento['venda_vinculada']:
            venda = None
        etapas = cruzamento['etapas']
        ultima = max(etapas, key=lambda e: e['data_envio']) if etapas else None
        vendedor = ''
        if venda:
            vendedor = venda['vendedor__first_name'] or venda['vendedor__username'] or ''
        status_tratamento = (venda['status_tratamento__nome'] or '') if venda else ''
        repescavel, motivo = avaliar_repescagem(
            cruzamento['situacao'], venda['data_criacao'] if venda else None,
            (venda['ordem_servico'] or '') if venda else '', status_tratamento, agora,
        )
        base.append({
            'cpf': cpf,
            'situacao': cruzamento['situacao'],
            'repescavel': repescavel,
            'motivo_repescagem': motivo,
            'status_tratamento': status_tratamento,
            'vinculo': cruzamento['vinculo'],
            'nome_cliente': venda['cliente__nome_razao_social'] if venda else '',
            'venda_id': venda['id'] if venda else None,
            'data_venda': venda['data_criacao'].isoformat() if venda and venda['data_criacao'] else None,
            'ordem_servico': (venda['ordem_servico'] or '') if venda else '',
            'status_esteira': (venda['status_esteira__nome'] or '') if venda else '',
            'vendedor': vendedor,
            'telefone': (venda['telefone1'] if venda and venda['telefone1'] else (ultima['msisdn'] if ultima else '')) or '',
            'ultimo_resultado': ultima['resultado_analise'] if ultima else '',
            'ultimo_envio': ultima['data_envio'].isoformat() if ultima else None,
            'ultima_origem': ultima['origem_digitalizacao'] if ultima else '',
            'protocolo': ultima['protocolo'] if ultima else '',
            'login_ged': ultima['login_digitalizacao'] if ultima else '',
            'qtd_envios': len(etapas),
        })
    base.sort(key=lambda b: (b['data_venda'] or b['ultimo_envio'] or ''), reverse=True)
    return base
