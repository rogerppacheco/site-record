"""Serviço de resolução de reCAPTCHA v2.

Por padrão usa CapSolver (melhor latência e taxa de sucesso que 2Captcha em v2 checkbox).
A API é simples para permitir troca de provedor.
"""
from __future__ import annotations

import os
import time
from typing import Literal, Optional

import requests

CaptchaProvider = Literal["capsolver", "2captcha"]


class RecaptchaSolver:
    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: CaptchaProvider = "capsolver",
        timeout: int = 120,
        poll_interval: int = 3,
    ) -> None:
        self.api_key = api_key or os.getenv("CAPTCHA_API_KEY")
        self.provider = provider or os.getenv("CAPTCHA_PROVIDER", "capsolver")
        self.timeout = timeout
        self.poll_interval = poll_interval

    def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        if not self.api_key:
            raise RuntimeError("CAPTCHA_API_KEY ausente")
        if self.provider == "capsolver":
            return self._solve_capsolver(site_key, page_url)
        if self.provider == "2captcha":
            return self._solve_2captcha(site_key, page_url)
        raise ValueError(f"Provedor de captcha não suportado: {self.provider}")

    # CapSolver
    def _solve_capsolver(self, site_key: str, page_url: str) -> Optional[str]:
        create_payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": site_key,
            },
        }
        task_id = self._post_json("https://api.capsolver.com/createTask", create_payload).get("taskId")
        if not task_id:
            return None
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            time.sleep(self.poll_interval)
            res = self._post_json(
                "https://api.capsolver.com/getTaskResult",
                {"clientKey": self.api_key, "taskId": task_id},
            )
            if res.get("status") == "ready":
                return res.get("solution", {}).get("gRecaptchaResponse")
        return None

    # 2Captcha (mantido para fallback/testes A/B)
    def _solve_2captcha(self, site_key: str, page_url: str) -> Optional[str]:
        params = {
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }
        create = requests.get("https://2captcha.com/in.php", params=params, timeout=15)
        data = create.json()
        if data.get("status") != 1:
            return None
        request_id = data.get("request")
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            time.sleep(self.poll_interval)
            poll = requests.get(
                "https://2captcha.com/res.php",
                params={"key": self.api_key, "action": "get", "id": request_id, "json": 1},
                timeout=15,
            ).json()
            if poll.get("status") == 1:
                return poll.get("request")
            if poll.get("request") not in {"CAPCHA_NOT_READY", None}:
                break
        return None

    @staticmethod
    def _post_json(url: str, payload: dict) -> dict:
        try:
            resp = requests.post(url, json=payload, timeout=20)
            return resp.json()
        except Exception:
            return {}
