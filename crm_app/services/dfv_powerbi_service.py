# -*- coding: utf-8 -*-
"""
Consulta ao vivo de fachadas por CEP no Power BI público (DFV_SUDESTE).

Independente da base local `crm_app.models.DFV` usada pelo comando FACHADA.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from typing import Any, Optional

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

ENTITY = "BASE_HP_F"

# Colunas mínimas para montar a resposta do WhatsApp
SELECT_COLS: list[str] = [
    "CEP",
    "NO_FACHADA",
    "COMPLEMENTO1",
    "COMPLEMENTO2",
    "COMPLEMENTO3",
    "LOGRADOURO",
    "BAIRRO",
    "MUNICIPIO",
    "UF",
    "VIABILIDADE_ATUAL",
    "CODIGO_CDO",
]

CACHE_KEY_PREFIX = "dfv_pbi:cep:"
_local_cache_lock = threading.Lock()
_local_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


class DfvPowerBiError(Exception):
    """Erro na consulta ao Power BI (rede, parse, API)."""


class DfvPowerBiTimeout(DfvPowerBiError):
    """Timeout ao consultar o Power BI."""


class DfvPowerBiDisabled(DfvPowerBiError):
    """Feature flag DFV_POWERBI_ENABLED desligada."""


def limpar_cep(cep: str) -> str:
    """Mantém só dígitos e normaliza para 8 posições (zero à esquerda)."""
    digitos = re.sub(r"\D", "", str(cep or ""))
    if not digitos:
        return ""
    if len(digitos) > 8:
        digitos = digitos[-8:]
    return digitos.zfill(8)


def _cfg(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


def _feature_enabled() -> bool:
    return bool(_cfg("DFV_POWERBI_ENABLED", True))


def _sem_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _eh_viavel(status: Optional[str]) -> bool:
    s = _sem_acentos(status or "").upper().strip()
    # "INVIAVEL" contém "VIAVEL" — excluir primeiro
    if "INVIAVEL" in s:
        return False
    return "VIAVEL" in s


def _montar_complemento(row: dict[str, Any]) -> str:
    partes = []
    for key in ("COMPLEMENTO1", "COMPLEMENTO2", "COMPLEMENTO3"):
        val = row.get(key)
        if val is None:
            continue
        texto = str(val).strip()
        if texto and texto.lower() not in ("none", "null", "nan"):
            partes.append(texto)
    return " | ".join(partes)


def _headers() -> dict[str, str]:
    resource_key = str(_cfg("DFV_POWERBI_RESOURCE_KEY", "") or "")
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
        "Origin": "https://app.powerbi.com",
        "Referer": "https://app.powerbi.com/",
        "Content-Type": "application/json;charset=UTF-8",
    }


def _null_mask(item: dict[str, Any]) -> int:
    if "\u00d8" in item:
        return int(item["\u00d8"])
    if "Ø" in item:
        return int(item["Ø"])
    return 0


def parse_dsr_rows(
    data_obj: dict[str, Any],
    n_cols: int,
) -> tuple[list[list[Any]], bool, Optional[list[Any]]]:
    """
    Parse DSR com ValueDicts, bitmask R (repeat) e Ø (null).

    Returns:
        (rows, incomplete, restart_tokens)
    """
    try:
        result = data_obj["results"][0]["result"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DfvPowerBiError(f"Resposta Power BI sem results: {exc}") from exc

    if "data" not in result:
        # Sem dados / CEP inexistente — tratar como lista vazia
        err = result.get("error") or result.get("errorCode")
        if err:
            raise DfvPowerBiError(f"Erro no Power BI: {err}")
        return [], False, None

    try:
        ds = result["data"]["dsr"]["DS"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise DfvPowerBiError(f"DSR inválido: {exc}") from exc

    value_dicts = ds.get("ValueDicts", {}) or {}
    dm0 = ds.get("PH", [{}])[0].get("DM0", []) or []
    if not dm0:
        return [], False, None

    col_dn: dict[int, str] = {}
    rows: list[list[Any]] = []
    prev: list[Any] = [None] * n_cols

    for item in dm0:
        if "S" in item:
            col_dn = {}
            for sdef in item["S"]:
                name = sdef.get("N", "")
                dn = sdef.get("DN")
                if name.startswith("G") and dn:
                    col_dn[int(name[1:])] = dn

        c_vals = list(item.get("C", []) or [])
        r_mask = int(item.get("R", 0) or 0)
        n_mask = _null_mask(item)
        row: list[Any] = [None] * n_cols
        ci = 0
        for col in range(n_cols):
            if n_mask & (1 << col):
                row[col] = None
                continue
            if r_mask & (1 << col):
                row[col] = prev[col]
                continue
            if ci >= len(c_vals):
                row[col] = None
                continue
            raw = c_vals[ci]
            ci += 1
            dn = col_dn.get(col)
            if dn and dn in value_dicts and isinstance(raw, int):
                vd = value_dicts[dn]
                if 0 <= raw < len(vd):
                    row[col] = vd[raw]
                else:
                    row[col] = raw
            else:
                row[col] = raw
        prev = row
        rows.append(row)

    incomplete = not bool(ds.get("IC", True))
    rt = ds.get("RT")
    return rows, incomplete, rt


def _build_cmd(cep: str, restart_tokens: Optional[list[Any]] = None) -> dict[str, Any]:
    window_count = int(_cfg("DFV_POWERBI_WINDOW_COUNT", 5000) or 5000)
    select = [
        {
            "Column": {
                "Expression": {"SourceRef": {"Source": "b"}},
                "Property": col,
            },
            "Name": f"{ENTITY}.{col}",
        }
        for col in SELECT_COLS
    ]
    window_obj: dict[str, Any] = {"Count": window_count}
    if restart_tokens is not None:
        window_obj["RestartTokens"] = restart_tokens

    return {
        "SemanticQueryDataShapeCommand": {
            "Query": {
                "Version": 2,
                "From": [{"Name": "b", "Entity": ENTITY, "Type": 0}],
                "Select": select,
                "Where": [
                    {
                        "Condition": {
                            "Comparison": {
                                "ComparisonKind": 0,
                                "Left": {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "b"}},
                                        "Property": "CEP",
                                    }
                                },
                                "Right": {"Literal": {"Value": f"'{cep}'"}},
                            }
                        }
                    }
                ],
            },
            "Binding": {
                "Primary": {"Groupings": [{"Projections": list(range(len(SELECT_COLS)))}]},
                "DataReduction": {
                    "DataVolume": 4,
                    "Primary": {"Window": window_obj},
                },
                "Version": 1,
            },
        }
    }


def _query_page(cmd: dict[str, Any]) -> dict[str, Any]:
    cluster = str(_cfg("DFV_POWERBI_CLUSTER", "") or "").rstrip("/")
    model_id = int(_cfg("DFV_POWERBI_MODEL_ID", 0) or 0)
    timeout = float(_cfg("DFV_POWERBI_TIMEOUT_SECONDS", 18) or 18)
    if not cluster or not model_id:
        raise DfvPowerBiError("Configuração Power BI incompleta (cluster/model id).")

    payload = {
        "version": "1.0.0",
        "queries": [{"Query": {"Commands": [cmd]}}],
        "cancelQueries": [],
        "modelId": model_id,
    }
    url = f"{cluster}/public/reports/querydata?synchronous=true"
    try:
        response = requests.post(
            url,
            headers=_headers(),
            data=json.dumps(payload),
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise DfvPowerBiTimeout("Timeout ao consultar o Power BI.") from exc
    except requests.RequestException as exc:
        raise DfvPowerBiError(f"Falha de rede no Power BI: {exc}") from exc

    if response.status_code >= 400:
        raise DfvPowerBiError(
            f"Power BI HTTP {response.status_code}: {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise DfvPowerBiError("Resposta Power BI não é JSON válido.") from exc


def _rows_to_dicts(rows: list[list[Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = {
            SELECT_COLS[i]: (row[i] if i < len(row) else None)
            for i in range(len(SELECT_COLS))
        }
        # Normaliza CEP vindo como número (ex.: 3013000 -> 03013000)
        cep_raw = item.get("CEP")
        if cep_raw is not None:
            item["CEP"] = limpar_cep(str(cep_raw))
        out.append(item)
    return out


def _cache_get(cep: str) -> Optional[list[dict[str, Any]]]:
    ttl = int(_cfg("DFV_POWERBI_CACHE_TTL_SECONDS", 600) or 0)
    if ttl <= 0:
        return None
    key = f"{CACHE_KEY_PREFIX}{cep}"
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        logger.debug("[DFV-PBI] cache Django indisponível; usando memória local", exc_info=True)

    now = time.time()
    with _local_cache_lock:
        entry = _local_cache.get(cep)
        if not entry:
            return None
        expires_at, data = entry
        if expires_at < now:
            _local_cache.pop(cep, None)
            return None
        return data


def _cache_set(cep: str, data: list[dict[str, Any]]) -> None:
    ttl = int(_cfg("DFV_POWERBI_CACHE_TTL_SECONDS", 600) or 0)
    if ttl <= 0:
        return
    key = f"{CACHE_KEY_PREFIX}{cep}"
    try:
        cache.set(key, data, timeout=ttl)
        return
    except Exception:
        logger.debug("[DFV-PBI] falha ao gravar cache Django", exc_info=True)

    with _local_cache_lock:
        _local_cache[cep] = (time.time() + ttl, data)
        # Evita crescimento indefinido em memória
        if len(_local_cache) > 500:
            oldest = sorted(_local_cache.items(), key=lambda kv: kv[1][0])[:100]
            for k, _ in oldest:
                _local_cache.pop(k, None)


def consultar_fachadas_por_cep(cep: str) -> list[dict[str, Any]]:
    """
    Consulta fachadas do CEP diretamente na API pública do Power BI.

    Returns:
        Lista de dicts com as colunas de SELECT_COLS.

    Raises:
        DfvPowerBiDisabled: feature flag desligada
        DfvPowerBiTimeout: timeout HTTP
        DfvPowerBiError: demais falhas (sem fallback para base local)
    """
    if not _feature_enabled():
        raise DfvPowerBiDisabled("Consulta DFV Power BI desabilitada.")

    cep_limpo = limpar_cep(cep)
    if len(cep_limpo) != 8:
        raise DfvPowerBiError("CEP inválido.")

    resource_key = str(_cfg("DFV_POWERBI_RESOURCE_KEY", "") or "")
    if not resource_key:
        raise DfvPowerBiError("DFV_POWERBI_RESOURCE_KEY não configurada.")

    cached = _cache_get(cep_limpo)
    if cached is not None:
        logger.info("[DFV-PBI] cache hit CEP=%s (%s registros)", cep_limpo, len(cached))
        return cached

    started = time.monotonic()
    all_rows: list[dict[str, Any]] = []
    restart: Optional[list[Any]] = None
    page = 0
    max_pages = int(_cfg("DFV_POWERBI_MAX_PAGES", 20) or 20)

    try:
        while page < max_pages:
            page += 1
            data = _query_page(_build_cmd(cep_limpo, restart_tokens=restart))
            rows, incomplete, rt = parse_dsr_rows(data, len(SELECT_COLS))
            all_rows.extend(_rows_to_dicts(rows))
            logger.info(
                "[DFV-PBI] CEP=%s page=%s +%s total=%s incomplete=%s",
                cep_limpo,
                page,
                len(rows),
                len(all_rows),
                incomplete,
            )
            if not incomplete or not rt or not rows:
                break
            restart = rt
    except DfvPowerBiError:
        raise
    except Exception as exc:
        logger.exception("[DFV-PBI] erro inesperado CEP=%s", cep_limpo)
        raise DfvPowerBiError(str(exc)) from exc

    elapsed = time.monotonic() - started
    logger.info(
        "[DFV-PBI] CEP=%s concluído: %s registros em %.1fs",
        cep_limpo,
        len(all_rows),
        elapsed,
    )
    _cache_set(cep_limpo, all_rows)
    return all_rows


def _ordenar_chave_fachada(num: Any) -> tuple[int, str]:
    texto = str(num or "").strip()
    digitos = "".join(ch for ch in texto if ch.isdigit())
    try:
        return (int(digitos) if digitos else 10**9, texto)
    except ValueError:
        return (10**9, texto)


def _filtrar_e_deduplicar(
    registros: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """
    Prefere viáveis; se não houver, mantém todos.
    Deduplica por (número + complementos).

    Returns:
        (lista_processada, usou_somente_viaveis)
    """
    viaveis = [r for r in registros if _eh_viavel(r.get("VIABILIDADE_ATUAL"))]
    usou_viaveis = bool(viaveis)
    base = viaveis if usou_viaveis else list(registros)

    vistos: set[tuple[str, str]] = set()
    unicos: list[dict[str, Any]] = []
    for row in base:
        num = str(row.get("NO_FACHADA") or "").strip()
        compl = _montar_complemento(row)
        chave = (num, compl)
        if chave in vistos:
            continue
        vistos.add(chave)
        enriched = dict(row)
        enriched["_complemento"] = compl
        enriched["_linha"] = f"{num} ({compl})" if compl else num
        unicos.append(enriched)

    unicos.sort(key=lambda r: _ordenar_chave_fachada(r.get("NO_FACHADA")))
    return unicos, usou_viaveis


def _split_mensagem(texto: str, max_len: int = 3800) -> list[str]:
    if len(texto) <= max_len:
        return [texto]
    partes: list[str] = []
    atual = ""
    for linha in texto.split("\n"):
        candidato = f"{atual}\n{linha}" if atual else linha
        if len(candidato) <= max_len:
            atual = candidato
            continue
        if atual:
            partes.append(atual)
        if len(linha) <= max_len:
            atual = linha
        else:
            for i in range(0, len(linha), max_len):
                pedaco = linha[i : i + max_len]
                if len(pedaco) == max_len:
                    partes.append(pedaco)
                else:
                    atual = pedaco
            if not atual:
                atual = ""
    if atual:
        partes.append(atual)
    return partes or [texto[:max_len]]


def formatar_resposta_dfv_powerbi(
    cep: str,
    registros: list[dict[str, Any]],
) -> list[str]:
    """
    Formata a resposta WhatsApp do comando DFV (Power BI ao vivo).

    Returns:
        Uma ou mais mensagens (fatiadas ~3800 chars).
    """
    cep_limpo = limpar_cep(cep)
    if not registros:
        return [
            (
                f"❌ *NENHUMA FACHADA ENCONTRADA (Power BI)*\n\n"
                f"Não encontramos fachadas para o CEP *{cep_limpo}* no DFV ao vivo "
                f"(cobertura ES/MG/RJ).\n"
                f"Tente *Fachada* (base local) ou *Viabilidade*."
            )
        ]

    filtrados, so_viaveis = _filtrar_e_deduplicar(registros)
    primeiro = filtrados[0] if filtrados else registros[0]
    logradouro = str(primeiro.get("LOGRADOURO") or "—").strip() or "—"
    bairro = str(primeiro.get("BAIRRO") or "—").strip() or "—"
    municipio = str(primeiro.get("MUNICIPIO") or "—").strip() or "—"
    uf = str(primeiro.get("UF") or "").strip()
    cidade_uf = f"{municipio}/{uf}" if uf else municipio

    cdos = sorted(
        {
            str(r.get("CODIGO_CDO")).strip()
            for r in filtrados
            if r.get("CODIGO_CDO") not in (None, "")
        }
    )
    cdos_str = ", ".join(cdos) if cdos else "—"

    linhas_num = [r["_linha"] for r in filtrados if r.get("_linha")]
    lista_str = "\n".join(linhas_num)

    aviso_status = ""
    if not so_viaveis:
        statuses = sorted(
            {
                str(r.get("VIABILIDADE_ATUAL") or "").strip()
                for r in filtrados
                if r.get("VIABILIDADE_ATUAL")
            }
        )
        status_txt = ", ".join(statuses) if statuses else "não informado"
        aviso_status = (
            f"\n⚠️ *Sem fachadas viáveis* neste CEP — exibindo status: {status_txt}\n"
        )

    cabecalho = (
        f"🏢 *DFV (Power BI ao vivo)*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"🏙️ *Bairro:* {bairro} | *Cidade/UF:* {cidade_uf}\n"
        f"📡 *CDO(s):* {cdos_str}\n"
        f"✅ *Total de fachadas:* {len(filtrados)}"
        f"{aviso_status}\n"
        f"🔢 *Números + complementos:*\n"
        f"{lista_str}"
    )
    return _split_mensagem(cabecalho)
