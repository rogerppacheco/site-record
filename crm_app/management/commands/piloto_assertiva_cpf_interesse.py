"""Piloto dry-run: tenta achar CPF via Assertiva para Interesses sem documento.

Não grava no Funil. Usa produção via `railway run`.

  railway run python manage.py piloto_assertiva_cpf_interesse --limite 100
"""
from __future__ import annotations

import csv
import re
import time
import unicodedata
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from crm_app.historico_pap import map_pedido_api
from crm_app.services.assertiva_localize_service import (
    AssertivaError,
    AssertivaLocalizeService,
)


_DOC_RE = re.compile(r"\D")


def _norm_nome(valor: str) -> str:
    s = unicodedata.normalize("NFKD", (valor or "").strip().upper())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s


def _tem_cpf(mapped: dict, payload: dict) -> bool:
    dig = _DOC_RE.sub("", str(mapped.get("cpf") or payload.get("cpf") or ""))
    if len(dig) == 11:
        return True
    dc = payload.get("dadosCliente") if isinstance(payload.get("dadosCliente"), dict) else {}
    dig = _DOC_RE.sub("", str(dc.get("cpf") or ""))
    return len(dig) == 11


def _extrair_pessoas(resposta) -> list[dict]:
    if not isinstance(resposta, dict):
        return []
    for chave in ("pessoas", "pessoasFisicas", "resultados", "lista", "items"):
        lista = resposta.get(chave)
        if isinstance(lista, list):
            return [x for x in lista if isinstance(x, dict)]
    # Algumas respostas trazem a pessoa direto.
    if resposta.get("cpf") or resposta.get("documento"):
        return [resposta]
    return []


def _cpf_de_pessoa(pessoa: dict) -> str:
    for chave in ("cpf", "documento", "numeroDocumento"):
        dig = _DOC_RE.sub("", str(pessoa.get(chave) or ""))
        if len(dig) == 11:
            return dig
    cad = pessoa.get("cadastroBasico") or pessoa.get("dadosCadastrais") or {}
    if isinstance(cad, dict):
        for chave in ("cpf", "documento"):
            dig = _DOC_RE.sub("", str(cad.get(chave) or ""))
            if len(dig) == 11:
                return dig
    return ""


def _nome_de_pessoa(pessoa: dict) -> str:
    for chave in ("nome", "nomeCompleto", "nomeCivil"):
        v = pessoa.get(chave)
        if isinstance(v, str) and v.strip():
            return v.strip()
    cad = pessoa.get("cadastroBasico") or pessoa.get("dadosCadastrais") or {}
    if isinstance(cad, dict):
        for chave in ("nome", "nomeCompleto", "nomeCivil"):
            v = cad.get(chave)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


class Command(BaseCommand):
    help = "Piloto Assertiva: match CPF por telefone/nome em Interesses sem documento (dry-run)."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=100)
        parser.add_argument(
            "--pausa-ms",
            type=int,
            default=250,
            help="Pausa entre chamadas Assertiva (ms).",
        )
        parser.add_argument(
            "--finalidade",
            type=int,
            default=1,
            help="idFinalidade Assertiva (1=confirmação de identidade).",
        )

    def handle(self, *args, **options):
        from crm_app.models import HistoricoPapPedido

        limite = max(1, min(int(options["limite"] or 100), 500))
        pausa = max(0, int(options["pausa_ms"] or 0)) / 1000.0
        finalidade = int(options["finalidade"] or 1)

        if not getattr(settings, "ASSERTIVA_CLIENT_ID", "") or not getattr(
            settings, "ASSERTIVA_CLIENT_SECRET", ""
        ):
            self.stderr.write(self.style.ERROR("ASSERTIVA_CLIENT_ID/SECRET ausentes."))
            return

        svc = AssertivaLocalizeService()

        # Interesses com nome e sem CPF óbvio no payload.
        qs = (
            HistoricoPapPedido.objects.filter(tipo_venda="INTERESSE")
            .exclude(Q(payload__cliente="") | Q(payload__cliente__isnull=True))
            .order_by("-capturado_em")
            .only("id", "numero_pedido", "payload", "capturado_em")
        )

        amostra = []
        for ped in qs.iterator(chunk_size=200):
            payload = ped.payload if isinstance(ped.payload, dict) else {}
            mapped = map_pedido_api(payload, "INTERESSE")
            nome = (mapped.get("cliente") or "").strip()
            if len(nome.split()) < 2:
                continue
            if _tem_cpf(mapped, payload):
                continue
            amostra.append((ped, mapped))
            if len(amostra) >= limite:
                break

        if not amostra:
            self.stdout.write(self.style.WARNING("Nenhum Interesse sem CPF com nome útil."))
            return

        self.stdout.write(
            f"[PILOTO] {len(amostra)} interesses sem CPF — Assertiva telefone→nome (finalidade={finalidade})"
        )

        rows = []
        stats = {
            "total": len(amostra),
            "com_telefone": 0,
            "match_telefone_unico": 0,
            "match_telefone_multi": 0,
            "match_nome_unico": 0,
            "match_nome_multi": 0,
            "sem_match": 0,
            "erro": 0,
            "consultas_api": 0,
        }

        for i, (ped, mapped) in enumerate(amostra, 1):
            nome = (mapped.get("cliente") or "").strip()
            tel = _DOC_RE.sub("", mapped.get("celular_principal") or mapped.get("celular_2") or "")
            if tel.startswith("55") and len(tel) in (12, 13):
                tel = tel[2:]
            uf = (mapped.get("uf") or "").strip().upper()[:2]
            cidade = (mapped.get("cidade") or "").strip()
            cep = _DOC_RE.sub("", mapped.get("cep") or "")

            resultado = {
                "pedido_id": ped.id,
                "protocolo": ped.numero_pedido,
                "nome_pap": nome,
                "telefone_pap": tel,
                "uf": uf,
                "cidade": cidade,
                "cep": cep,
                "via": "",
                "qtd_candidatos": 0,
                "cpf_sugerido": "",
                "nome_assertiva": "",
                "nome_bate": "",
                "status": "",
                "detalhe": "",
            }

            try:
                # 1) Telefone, se existir
                if len(tel) in (10, 11):
                    stats["com_telefone"] += 1
                    pessoas_tel, err_tel = self._consultar_telefone(svc, tel, finalidade)
                    stats["consultas_api"] += 1
                    if pausa:
                        time.sleep(pausa)
                    if err_tel:
                        resultado["detalhe"] = f"tel:{err_tel}"
                    else:
                        # Preferir quem tem nome igual; senão todos
                        iguais = [
                            p
                            for p in pessoas_tel
                            if _norm_nome(_nome_de_pessoa(p)) == _norm_nome(nome)
                        ]
                        candidatos = iguais or pessoas_tel
                        resultado["qtd_candidatos"] = len(candidatos)
                        if len(candidatos) == 1:
                            p0 = candidatos[0]
                            cpf = _cpf_de_pessoa(p0)
                            nome_a = _nome_de_pessoa(p0)
                            bate = _norm_nome(nome_a) == _norm_nome(nome) if nome_a else False
                            resultado.update(
                                {
                                    "via": "telefone",
                                    "cpf_sugerido": cpf,
                                    "nome_assertiva": nome_a,
                                    "nome_bate": "sim" if bate else "nao",
                                    "status": "match_unico" if cpf and bate else (
                                        "match_unico_nome_diferente" if cpf else "sem_cpf"
                                    ),
                                }
                            )
                            if cpf and bate:
                                stats["match_telefone_unico"] += 1
                                rows.append(resultado)
                                self._progresso(i, len(amostra), resultado)
                                continue
                        elif len(candidatos) > 1:
                            stats["match_telefone_multi"] += 1
                            resultado.update(
                                {
                                    "via": "telefone",
                                    "status": "multiplos",
                                    "detalhe": f"{len(candidatos)} candidatos",
                                }
                            )
                            # Ainda tenta nome se telefone deu múltiplos

                # 2) Nome exato (+ UF/cidade/CEP se houver)
                pessoas_nome, err_nome = self._consultar_nome(
                    svc, nome, finalidade, uf=uf, cidade=cidade, cep=cep
                )
                stats["consultas_api"] += 1
                if pausa:
                    time.sleep(pausa)
                if err_nome:
                    resultado["status"] = resultado["status"] or "erro"
                    resultado["detalhe"] = (resultado["detalhe"] + f" | nome:{err_nome}").strip(" |")
                    if resultado["status"] == "erro":
                        stats["erro"] += 1
                    else:
                        stats["sem_match"] += 1
                    rows.append(resultado)
                    self._progresso(i, len(amostra), resultado)
                    continue

                iguais = [
                    p
                    for p in pessoas_nome
                    if _norm_nome(_nome_de_pessoa(p)) == _norm_nome(nome)
                ]
                candidatos = iguais or []
                resultado["qtd_candidatos"] = len(candidatos) or len(pessoas_nome)
                if len(candidatos) == 1:
                    p0 = candidatos[0]
                    cpf = _cpf_de_pessoa(p0)
                    nome_a = _nome_de_pessoa(p0)
                    resultado.update(
                        {
                            "via": "nome_exato",
                            "cpf_sugerido": cpf,
                            "nome_assertiva": nome_a,
                            "nome_bate": "sim",
                            "status": "match_unico" if cpf else "sem_cpf",
                        }
                    )
                    if cpf:
                        stats["match_nome_unico"] += 1
                    else:
                        stats["sem_match"] += 1
                elif len(candidatos) > 1:
                    stats["match_nome_multi"] += 1
                    resultado.update(
                        {
                            "via": "nome_exato",
                            "status": "multiplos",
                            "detalhe": f"{len(candidatos)} com nome exato (total API={len(pessoas_nome)})",
                        }
                    )
                else:
                    stats["sem_match"] += 1
                    resultado.update(
                        {
                            "via": "nome_exato",
                            "status": "sem_match",
                            "detalhe": f"API retornou {len(pessoas_nome)} sem nome idêntico",
                        }
                    )
            except Exception as exc:
                stats["erro"] += 1
                resultado["status"] = "erro"
                resultado["detalhe"] = str(exc)[:200]

            rows.append(resultado)
            self._progresso(i, len(amostra), resultado)

        out_dir = Path(settings.BASE_DIR) / "relatorios"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"piloto_assertiva_cpf_interesse_{stamp}.csv"
        with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=[
                    "pedido_id",
                    "protocolo",
                    "nome_pap",
                    "telefone_pap",
                    "uf",
                    "cidade",
                    "cep",
                    "via",
                    "qtd_candidatos",
                    "cpf_sugerido",
                    "nome_assertiva",
                    "nome_bate",
                    "status",
                    "detalhe",
                ],
            )
            w.writeheader()
            w.writerows(rows)

        unicos = stats["match_telefone_unico"] + stats["match_nome_unico"]
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== RESUMO PILOTO (não gravou no Funil) ==="))
        self.stdout.write(f"Total amostrado:           {stats['total']}")
        self.stdout.write(f"Com telefone no PAP:       {stats['com_telefone']}")
        self.stdout.write(f"Match único por telefone:  {stats['match_telefone_unico']}")
        self.stdout.write(f"Telefone múltiplos:        {stats['match_telefone_multi']}")
        self.stdout.write(f"Match único por nome:      {stats['match_nome_unico']}")
        self.stdout.write(f"Nome múltiplos:            {stats['match_nome_multi']}")
        self.stdout.write(f"Sem match:                 {stats['sem_match']}")
        self.stdout.write(f"Erros:                     {stats['erro']}")
        self.stdout.write(f"Consultas Assertiva:       {stats['consultas_api']}")
        self.stdout.write(
            self.style.SUCCESS(
                f"CPFs sugeridos (únicos + nome bate): {unicos} "
                f"({100.0 * unicos / stats['total']:.1f}%)"
            )
        )
        self.stdout.write(f"CSV: {out_path}")

    def _progresso(self, i: int, total: int, row: dict) -> None:
        self.stdout.write(
            f"  [{i}/{total}] {row.get('protocolo')} via={row.get('via') or '-'} "
            f"status={row.get('status')} cpf={row.get('cpf_sugerido') or '-'}"
        )

    def _consultar_telefone(self, svc: AssertivaLocalizeService, telefone: str, finalidade: int):
        try:
            token = svc._obter_token()
            resp = svc.http.get(
                f"{svc.base_url}/localize/v3/telefone",
                params={"telefone": telefone, "idFinalidade": finalidade},
                headers={"Authorization": f"Bearer {token}"},
                timeout=svc.timeout_seconds,
            )
            if resp.status_code == 401:
                svc._invalidar_token()
                token = svc._obter_token()
                resp = svc.http.get(
                    f"{svc.base_url}/localize/v3/telefone",
                    params={"telefone": telefone, "idFinalidade": finalidade},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=svc.timeout_seconds,
                )
            payload = AssertivaLocalizeService._validar_resposta(resp, "consulta telefone")
            return _extrair_pessoas(payload.get("resposta")), None
        except AssertivaError as exc:
            return [], str(exc)
        except Exception as exc:
            return [], str(exc)

    def _consultar_nome(
        self,
        svc: AssertivaLocalizeService,
        nome: str,
        finalidade: int,
        *,
        uf: str = "",
        cidade: str = "",
        cep: str = "",
    ):
        params = {
            "buscarPor": "pessoas",
            "nomeOuRazaoSocial": nome,
            "nomeOuRazaoSocialExata": "true",
            "idFinalidade": finalidade,
        }
        if uf:
            params["uf"] = uf
        if cidade and uf:
            params["cidade"] = cidade
        if len(cep) == 8:
            params["cepOuNomeRua"] = cep
        try:
            token = svc._obter_token()
            resp = svc.http.get(
                f"{svc.base_url}/localize/v3/nome-endereco",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=svc.timeout_seconds,
            )
            if resp.status_code == 401:
                svc._invalidar_token()
                token = svc._obter_token()
                resp = svc.http.get(
                    f"{svc.base_url}/localize/v3/nome-endereco",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=svc.timeout_seconds,
                )
            payload = AssertivaLocalizeService._validar_resposta(resp, "consulta nome")
            return _extrair_pessoas(payload.get("resposta")), None
        except AssertivaError as exc:
            return [], str(exc)
        except Exception as exc:
            return [], str(exc)
