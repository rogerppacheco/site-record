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
# Biometria enviada há menos que isso ainda pode ser concluída pelo cliente: não repescar.
PRAZO_BIO = timedelta(hours=48)
# CONSTA PEDIDO: pedido de outro PDV no PAP precisa ter mais que isso para liberar a repescagem.
PRAZO_CONSTA_PEDIDO = timedelta(days=30)
# Janela da Consulta OS no PAP ao buscar o pedido que originou o CONSTA PEDIDO.
JANELA_CONSULTA_CONSTA_PAP = timedelta(days=180)
# Não reconsultar o PAP de novo antes disso se a última busca não achou pedido.
TTL_SEM_PEDIDO_PAP = timedelta(hours=6)
ORIGEM_CACHE_CONSTA = 'repescagem_bio_consta'

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


_lock_consulta_consta = threading.Lock()
_consultas_consta_em_andamento: set[str] = set()


def _eh_consta_pedido(status_tratamento: str) -> bool:
    return 'CONSTA PEDIDO' in _sem_acento(status_tratamento)


def _eh_duplicidade(status_tratamento: str) -> bool:
    return 'DUPLICIDADE' in _sem_acento(status_tratamento)


def _texto_dias(n: int) -> str:
    n = max(0, int(n))
    return '1 dia' if n == 1 else f'{n} dias'


def _parse_data_hora_pap(valor) -> Optional[datetime]:
    """Aceita ISO da API ou 'dd/mm/yyyy HH:MM' da Consulta OS."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return timezone.make_aware(valor) if timezone.is_naive(valor) else valor
    s = str(valor).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
    except ValueError:
        pass
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
        try:
            return timezone.make_aware(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


def _numero_cache_sem_pedido(cpf: str) -> str:
    return f'BIO-SEM-{normalizar_documento(cpf)}'


def _cpf_do_payload(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ''
    return normalizar_documento(payload.get('cpf') or (payload.get('dadosCliente') or {}).get('cpf'))


def infos_pedido_pap_por_cpf(cpfs: Iterable[str], agora: Optional[datetime] = None) -> dict[str, dict]:
    """Lê o cache (HistoricoPapPedido) e devolve, por CPF, data do pedido / sem pedido / ainda não consultado.

    Cada valor: {consultado, data_criacao, de_outro_pdv, numero_os, em_andamento}.
    """
    from django.db.models import Q

    from crm_app.models import HistoricoPapPedido

    agora = agora or timezone.now()
    alvos = {normalizar_documento(c) for c in cpfs if normalizar_documento(c)}
    vazios = {
        cpf: {
            'consultado': False,
            'data_criacao': None,
            'de_outro_pdv': None,
            'numero_os': '',
            'em_andamento': cpf in _consultas_consta_em_andamento,
        }
        for cpf in alvos
    }
    if not alvos:
        return {}

    # Evita payload__icontains (varre o JSON e deixa a listagem lenta a cada filtro).
    # Usa a chave cpf do JSON + cache desta aba + marcadores BIO-SEM-*.
    from django.db.models.expressions import RawSQL

    numeros_sem = [_numero_cache_sem_pedido(cpf) for cpf in alvos]
    qs = (
        HistoricoPapPedido.objects.annotate(
            cpf_digits=RawSQL(
                "regexp_replace(coalesce(payload->>'cpf', payload->'dadosCliente'->>'cpf', ''), '[^0-9]', '', 'g')",
                (),
            ),
        )
        .filter(
            Q(numero_pedido__in=numeros_sem)
            | Q(origem=ORIGEM_CACHE_CONSTA)
            | Q(cpf_digits__in=list(alvos))
        )
        .values_list('numero_pedido', 'data_criacao_pap', 'payload', 'capturado_em')
    )

    for numero, data_criacao, payload, capturado_em in qs:
        payload = payload if isinstance(payload, dict) else {}
        cpf = _cpf_do_payload(payload)
        if not cpf and str(numero).startswith('BIO-SEM-'):
            cpf = normalizar_documento(str(numero)[len('BIO-SEM-'):])
        if cpf not in alvos:
            continue
        if payload.get('semPedido'):
            quando = capturado_em or agora
            if agora - quando <= TTL_SEM_PEDIDO_PAP:
                vazios[cpf] = {
                    'consultado': True,
                    'data_criacao': None,
                    'de_outro_pdv': None,
                    'numero_os': '',
                    'em_andamento': False,
                    'sem_pedido': True,
                }
            continue
        if not data_criacao:
            data_criacao = _parse_data_hora_pap(payload.get('dataCriacao'))
        if not data_criacao:
            continue
        atual = vazios[cpf]
        # Pedido mais antigo costuma ser o que bloqueou a venda (CONSTA PEDIDO).
        if not atual.get('consultado') or (
            atual.get('data_criacao') and data_criacao < atual['data_criacao']
        ) or (atual.get('consultado') and atual.get('sem_pedido')):
            outro = payload.get('nao_pertence_pdv')
            if outro is None and payload.get(ORIGEM_CACHE_CONSTA):
                outro = True
            vazios[cpf] = {
                'consultado': True,
                'data_criacao': data_criacao,
                'de_outro_pdv': bool(outro) if outro is not None else None,
                'numero_os': str(payload.get('numeroOs') or payload.get('osInstalacao') or '')[:40],
                'em_andamento': False,
                'sem_pedido': False,
            }
    return vazios


def _gravar_cache_pedido_pap(cpf: str, detalhes: list[dict]) -> None:
    """Grava o resultado da Consulta OS no HistoricoPapPedido para a próxima listagem."""
    from crm_app.models import HistoricoPapPedido

    cpf = normalizar_documento(cpf)
    if not cpf:
        return
    if not detalhes:
        HistoricoPapPedido.objects.update_or_create(
            numero_pedido=_numero_cache_sem_pedido(cpf),
            defaults={
                'tipo_venda': HistoricoPapPedido.TIPO_VENDA,
                'pdv': '',
                'status': 'SEM_PEDIDO',
                'data_criacao_pap': None,
                'origem': ORIGEM_CACHE_CONSTA,
                'payload': {
                    'cpf': cpf,
                    'semPedido': True,
                    ORIGEM_CACHE_CONSTA: True,
                    'consultadoEm': timezone.now().isoformat(),
                },
            },
        )
        return

    for item in detalhes:
        data_criacao = _parse_data_hora_pap(item.get('data_hora') or item.get('dataCriacao'))
        numero_os = re.sub(r'\D', '', str(item.get('numero_os') or item.get('numeroOs') or ''))
        numero_pedido = (
            str(item.get('numeroPedido') or '').strip()
            or (f'OS-{numero_os}' if numero_os else f'BIO-{cpf}-{int((data_criacao or timezone.now()).timestamp())}')
        )[:40]
        outro = bool(item.get('nao_pertence_pdv'))
        payload = {
            'cpf': cpf,
            'numeroPedido': numero_pedido,
            'numeroOs': numero_os,
            'dataCriacao': data_criacao.isoformat() if data_criacao else None,
            'status': item.get('status') or '',
            'plano': item.get('plano') or '',
            'nao_pertence_pdv': outro,
            ORIGEM_CACHE_CONSTA: True,
        }
        HistoricoPapPedido.objects.update_or_create(
            numero_pedido=numero_pedido,
            defaults={
                'tipo_venda': HistoricoPapPedido.TIPO_VENDA,
                'pdv': 'OUTRO' if outro else '',
                'status': str(item.get('status') or '')[:80],
                'data_criacao_pap': data_criacao,
                'origem': ORIGEM_CACHE_CONSTA,
                'payload': payload,
            },
        )
    HistoricoPapPedido.objects.filter(numero_pedido=_numero_cache_sem_pedido(cpf)).delete()


def _consultar_consta_no_pap(cpf: str) -> None:
    """Thread: Consulta OS no PAP Nio por CPF e grava o cache. Só para CONSTA PEDIDO sem data."""
    from django.conf import settings

    from crm_app.pool_bo_pap import liberar_bo, obter_login_bo
    from crm_app.services_pap_nio import PAPNioAutomation

    cpf = normalizar_documento(cpf)
    telefone_lock = f'{TELEFONE_POOL}_consta_{cpf}'
    bo = None
    automacao = None
    try:
        close_old_connections()
        bo, erro = obter_login_bo(telefone_lock, None, tipo_automacao='pedido')
        if not bo:
            logger.warning('[RepescagemBio] CONSTA PAP sem login BO para %s: %s', cpf, erro)
            return
        automacao = PAPNioAutomation(
            matricula_pap=bo.matricula_pap,
            senha_pap=bo.senha_pap,
            vendedor_nome='RepescagemBio-CONSTA',
            headless=getattr(settings, 'PAP_HEADLESS', True),
            capture_screenshots=False,
            optimize_for_credit=True,
        )
        data_inicio = (timezone.localdate() - JANELA_CONSULTA_CONSTA_PAP)
        sucesso, msg, detalhes, _ = automacao.consulta_os_por_cpf_com_resultado(
            cpf, data_inicio=data_inicio,
        )
        if not sucesso:
            logger.warning('[RepescagemBio] CONSULTA OS falhou para %s: %s', cpf, msg)
            return
        _gravar_cache_pedido_pap(cpf, detalhes or [])
        logger.info(
            '[RepescagemBio] CONSTA PAP %s: %s pedido(s)',
            cpf, len(detalhes or []),
        )
    except Exception:
        logger.exception('[RepescagemBio] Erro na consulta PAP CONSTA %s', cpf)
    finally:
        if automacao:
            try:
                automacao._fechar_sessao()
            except Exception:
                pass
        if bo:
            liberar_bo(bo.id, telefone_lock)
        with _lock_consulta_consta:
            _consultas_consta_em_andamento.discard(cpf)
        close_old_connections()


def disparar_consultas_consta_pap(cpfs: Iterable[str], limite: int = 1) -> list[str]:
    """Dispara no máximo `limite` consultas PAP por request. Devolve os CPFs enfileirados.

    Cada Consulta OS abre o navegador e compete pelo login BO; vários de uma vez
    deixam a listagem e o restante do sistema pesados.
    """
    candidatos = []
    for cpf in {normalizar_documento(c) for c in cpfs if normalizar_documento(c)}:
        with _lock_consulta_consta:
            if cpf in _consultas_consta_em_andamento:
                continue
            if limite > 0 and len(_consultas_consta_em_andamento) >= limite:
                break
            _consultas_consta_em_andamento.add(cpf)
            candidatos.append(cpf)
        if len(candidatos) >= limite:
            break
    for cpf in candidatos:
        threading.Thread(
            target=_consultar_consta_no_pap, args=(cpf,), name=f'repescagem-consta-{cpf}', daemon=True,
        ).start()
    return candidatos


def avaliar_repescagem(situacao: str, data_venda: Optional[datetime], ordem_servico: str = '',
                       status_tratamento: str = '', agora: Optional[datetime] = None,
                       ultimo_envio: Optional[datetime] = None,
                       data_pedido_pap: Optional[datetime] = None,
                       info_pedido_pap: Optional[dict] = None) -> tuple[bool, str]:
    """Repescável: biometria no GED há mais de PRAZO_BIO, sem risco, sem O.S. (ou sem venda) há mais de
    PRAZO_OS; se o tratamento for CONSTA PEDIDO, o pedido no PAP precisa ter mais de PRAZO_CONSTA_PEDIDO.

    data_venda é a da venda vinculada à biometria (vincular_venda). Devolve (repescavel, motivo).
    """
    agora = agora or timezone.now()
    if situacao in (SEM_BIOMETRIA, NAO_VERIFICADO):
        return False, 'Sem registro no GED'
    if situacao == RISCO:
        return False, 'Biometria reprovada/risco'
    if _eh_duplicidade(status_tratamento):
        return False, 'Venda com tratamento DUPLICIDADE'
    os_venda = (ordem_servico or '').strip() if data_venda else ''
    if os_venda:
        return False, f'Venda com O.S. {os_venda}'
    if ultimo_envio and agora - ultimo_envio <= PRAZO_BIO:
        horas = int((agora - ultimo_envio).total_seconds() // 3600)
        return False, f'Aguardando 48h da biometria (enviada há {horas}h)'
    if _eh_consta_pedido(status_tratamento):
        info = info_pedido_pap or {}
        data_pap = info.get('data_criacao') or data_pedido_pap
        if info.get('em_andamento'):
            return False, 'CONSTA PEDIDO: consultando pedido no PAP…'
        if not info.get('consultado'):
            return False, 'CONSTA PEDIDO: aguardando consulta do pedido no PAP'
        if info.get('sem_pedido') or not data_pap:
            return False, 'CONSTA PEDIDO: nenhum pedido encontrado no PAP'
        idade_pedido = agora - data_pap
        if idade_pedido <= PRAZO_CONSTA_PEDIDO:
            return False, (
                f'CONSTA PEDIDO: pedido no PAP há {_texto_dias(idade_pedido.days)} (aguarda 30 dias)'
            )
        # Pedido com mais de 30 dias: segue as demais regras (sem O.S. etc.).
    if not data_venda:
        return True, f'Biometria sem venda no CRM ({ROTULOS_SITUACAO.get(situacao, situacao)})'
    idade = agora - data_venda
    if idade <= PRAZO_OS:
        return False, f'Aguardando cadastro da O.S. (venda há {int(idade.total_seconds() // 3600)}h)'
    motivo = f'Venda sem O.S. há {_texto_dias(idade.days)}'
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

    # CONSTA PEDIDO: só avalia com data do pedido no PAP. Cache primeiro; o que faltar dispara Consulta OS.
    cpfs_consta = {
        cpf for cpf, venda in venda_por_cpf.items()
        if _eh_consta_pedido(venda.get('status_tratamento__nome') or '')
    }
    info_pap_por_cpf = infos_pedido_pap_por_cpf(cpfs_consta, agora)
    # Só consulta o PAP quando a bio no GED existe e ainda não há O.S.: senão a regra já fecha sozinha.
    faltando = []
    for cpf in cpfs_consta:
        if info_pap_por_cpf.get(cpf, {}).get('consultado'):
            continue
        venda = venda_por_cpf.get(cpf) or {}
        if (venda.get('ordem_servico') or '').strip():
            continue
        if cpf not in cpfs_ged and cpf not in etapas_por_cpf:
            continue
        faltando.append(cpf)
    if faltando:
        # Uma consulta por request: várias Consultas OS ao mesmo tempo deixam o funil lento.
        disparados = disparar_consultas_consta_pap(faltando, limite=1)
        for cpf in disparados:
            info_pap_por_cpf.setdefault(cpf, {
                'consultado': False, 'data_criacao': None, 'de_outro_pdv': None,
                'numero_os': '', 'em_andamento': True,
            })
            info_pap_por_cpf[cpf]['em_andamento'] = True
        # Os demais aguardam a próxima carga da lista (sem marcar "consultando" em massa).
        for cpf in faltando:
            if cpf in disparados:
                continue
            info_pap_por_cpf.setdefault(cpf, {
                'consultado': False, 'data_criacao': None, 'de_outro_pdv': None,
                'numero_os': '', 'em_andamento': False,
            })

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
        info_pap = info_pap_por_cpf.get(cpf)
        repescavel, motivo = avaliar_repescagem(
            cruzamento['situacao'], venda['data_criacao'] if venda else None,
            (venda['ordem_servico'] or '') if venda else '', status_tratamento, agora,
            ultima['data_envio'] if ultima else None,
            (info_pap or {}).get('data_criacao'),
            info_pap,
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
