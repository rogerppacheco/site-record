"""
Cliente Sonax PABX: click2call e download de gravação (pega_gravacao).

Documentação: https://conteudo.sonax.net.br/kb/pt-br/article/159253/api-de-integracao-de-voz
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings

PROTOCOLO_RE = re.compile(r"PROTOCOLO\s*(\d+)", re.IGNORECASE)


class SonaxVoiceService:
    def __init__(self) -> None:
        self.click2call_url = getattr(
            settings,
            "SONAX_CLICK2CALL_URL",
            "https://click2call.sonax.net.br/sonax-click2call.php",
        ).rstrip("/")
        if not self.click2call_url.endswith(".php"):
            self.click2call_url = self.click2call_url.rstrip("/")

        self.dbdial_base = getattr(
            settings,
            "SONAX_DBDIAL_BASE_URL",
            "https://api.sonax.net.br/a2billing_v2/admin/Public/dbdial_webapi.php",
        ).rstrip("?")
        self.client_id = str(getattr(settings, "SONAX_ID_CLIENTE", "") or "").strip()
        self.token = str(getattr(settings, "SONAX_CLICK2CALL_TOKEN", "") or "").strip()
        self.integration_token = str(
            getattr(settings, "SONAX_INTEGRATION_TOKEN", "") or self.token
        ).strip()
        self.timeout_seconds = int(getattr(settings, "SONAX_TIMEOUT_SECONDS", 30))

    @property
    def is_click2call_configured(self) -> bool:
        return bool(self.token)

    @property
    def is_recording_download_configured(self) -> bool:
        return bool(self.client_id and self.integration_token)

    def _dbdial_params(self) -> Dict[str, str]:
        return {"id_cliente": self.client_id, "token": self.integration_token}

    def click_to_call(
        self,
        *,
        destination_digits: str,
        ramal: str,
        var_tags: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not self.is_click2call_configured:
            raise ValueError("Sonax click2call não configurado: defina SONAX_CLICK2CALL_TOKEN.")

        params: Dict[str, Any] = {
            "numero": destination_digits,
            "ramal": str(ramal).strip(),
            "token": self.token,
            "resposta": "json",
        }
        if var_tags:
            idx = 1
            for key, val in var_tags.items():
                if idx > 5:
                    break
                if val is not None and str(val) != "":
                    params[f"var_{idx}"] = str(val)
                    idx += 1

        url = self.click2call_url
        if not url.endswith("sonax-click2call.php"):
            url = f"{url}/sonax-click2call.php" if ".php" not in url else url

        response = requests.get(url, params=params, timeout=self.timeout_seconds)
        snippet = response.text[:800] if response.text else ""
        if response.status_code >= 400:
            raise RuntimeError(f"Sonax click2call HTTP {response.status_code}: {snippet}")
        if "404 not found" in (response.text or "").lower():
            raise RuntimeError(f"Sonax recusou a chamada: {snippet}")

        parsed = self._parse_click2call_response(response)
        call_id = parsed.get("id_chamada") or parsed.get("protocolo") or parsed.get("id")
        if call_id is None:
            call_id = self._extract_protocol_from_text(response.text or "")
        out: Dict[str, Any] = {"raw_text": response.text, "parsed": parsed}
        if call_id is not None:
            out["id_chamada"] = str(call_id).strip()
        return out

    @staticmethod
    def _extract_protocol_from_text(text: str) -> Optional[str]:
        m = PROTOCOLO_RE.search(text or "")
        if m:
            return m.group(1)
        m2 = re.search(r"\b(\d{5,12})\b", text or "")
        if m2 and "PROTOCOLO" in (text or "").upper():
            return m2.group(1)
        return None

    def _parse_click2call_response(self, response: requests.Response) -> Dict[str, Any]:
        text = (response.text or "").strip()
        if not text:
            return {}
        ct = (response.headers.get("content-type") or "").lower()
        if "json" in ct or text.startswith("{") or text.startswith("["):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    return data
                if isinstance(data, list) and data:
                    return {"lista": data}
            except json.JSONDecodeError:
                pass
        return {"mensagem": text[:2000]}

    def download_recording(self, id_chamada: str) -> Tuple[bytes, str]:
        """
        Baixa gravação via acao=pega_gravacao. Retorna (bytes, extensão .wav ou .mp3).
        """
        if not self.is_recording_download_configured:
            raise ValueError(
                "Download de gravação Sonax: defina SONAX_ID_CLIENTE e SONAX_INTEGRATION_TOKEN "
                "(ou o mesmo valor em SONAX_CLICK2CALL_TOKEN)."
            )
        params = {
            **self._dbdial_params(),
            "acao": "pega_gravacao",
            "id_chamada": str(id_chamada).strip(),
        }
        response = requests.get(self.dbdial_base, params=params, timeout=self.timeout_seconds * 2)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Sonax pega_gravacao HTTP {response.status_code}: {(response.text or '')[:500]}"
            )
        body = response.content or b""
        if not body:
            raise RuntimeError("Sonax pega_gravacao retornou corpo vazio.")
        if (response.text or "").strip().lower().startswith("404") or b"404 not found" in body[:80].lower():
            raise RuntimeError(f"Sonax pega_gravacao recusou: {(response.text or '')[:500]}")

        ct = (response.headers.get("content-type") or "").lower()

        if body[:2] == b"PK" or "zip" in ct:
            return unpack_recording_zip(body)

        if "mpeg" in ct or "mp3" in ct:
            return body, ".mp3"
            return body, ".wav"


def unpack_recording_zip(data: bytes) -> Tuple[bytes, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(zf.namelist())
        for name in names:
            lower = name.lower()
            if lower.endswith(".wav"):
                return zf.read(name), ".wav"
            if lower.endswith(".mp3"):
                return zf.read(name), ".mp3"
        if names:
            return zf.read(names[0]), ".wav"
    raise RuntimeError("ZIP de gravação Sonax sem arquivos.")
