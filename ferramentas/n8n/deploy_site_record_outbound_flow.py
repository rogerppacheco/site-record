#!/usr/bin/env python3
"""
Importa o fluxo outbound site-record no n8n e exibe a URL do webhook.

Variáveis de ambiente:
  N8N_API_URL=https://seu-n8n.up.railway.app
  N8N_API_KEY=<api key do n8n, se habilitada>

  EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE_NAME=site_record_zap
  (configure também no n8n como variáveis de ambiente)

Uso:
  python ferramentas/n8n/deploy_site_record_outbound_flow.py
  python ferramentas/n8n/deploy_site_record_outbound_flow.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

FLOW_FILE = Path(__file__).resolve().parent / "site-record-n8n-outbound-flow.json"
WEBHOOK_PATH = "site-record-enviar-mensagem"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _headers(api_key: str) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["X-N8N-API-KEY"] = api_key
    return h


def load_flow() -> Dict[str, Any]:
    with FLOW_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


def deploy_flow(base_url: str, api_key: str, flow: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/workflows"
    resp = requests.post(url, headers=_headers(api_key), json=flow, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:800]}")
    return resp.json()


def activate_workflow(base_url: str, api_key: str, workflow_id: str) -> None:
    url = f"{base_url.rstrip('/')}/api/v1/workflows/{workflow_id}/activate"
    resp = requests.post(url, headers=_headers(api_key), timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Ativação falhou HTTP {resp.status_code}: {resp.text[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy fluxo n8n outbound site-record")
    parser.add_argument("--dry-run", action="store_true", help="Só exibe URL esperada")
    args = parser.parse_args()

    n8n_url = _env("N8N_API_URL")
    n8n_key = _env("N8N_API_KEY")
    webhook_base = _env("N8N_WEBHOOK_BASE_URL", n8n_url)
    expected_webhook = f"{webhook_base.rstrip('/')}/webhook/{WEBHOOK_PATH}"

    print("Fluxo:", FLOW_FILE.name)
    print("Webhook esperado (N8N_OUTBOUND_WEBHOOK_URL):")
    print(f"  {expected_webhook}")
    print()
    print("Variáveis Railway site-record:")
    print(f"  N8N_OUTBOUND_WEBHOOK_URL={expected_webhook}")
    print("  WHATSAPP_PROVIDER=evolution")
    print()

    if args.dry_run:
        return 0

    if not n8n_url:
        print("Defina N8N_API_URL para importar o fluxo.", file=sys.stderr)
        return 1

    flow = load_flow()
    data = deploy_flow(n8n_url, n8n_key, flow)
    wf_id = str(data.get("id") or "")
    if wf_id:
        activate_workflow(n8n_url, n8n_key, wf_id)
        print(f"Workflow importado e ativado: id={wf_id}")
    else:
        print("Workflow importado (sem id na resposta).")
    print(f"\nConfigure: N8N_OUTBOUND_WEBHOOK_URL={expected_webhook}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
