"""Thin PayPal REST client (sandbox) with an on-disk cache for demo mode.

DEMO_MODE=1 serves responses from data/cache/ only, so the hosted demo runs
without credentials or network.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from . import mcp_paypal

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
load_dotenv(ROOT / ".env")


class PayPal:
    def __init__(self):
        self.base = os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
        self.demo = os.environ.get("DEMO_MODE") == "1"
        self._token: str | None = None
        self._exp = 0.0
        self.via: dict[str, str] = {}  # path -> how it was fetched (rest | paypal-mcp:<tool> | cache)
        CACHE.mkdir(parents=True, exist_ok=True)

    def _auth(self) -> str:
        if not self._token or time.time() > self._exp:
            r = requests.post(f"{self.base}/v1/oauth2/token",
                              auth=(os.environ["PAYPAL_CLIENT_ID"],
                                    os.environ["PAYPAL_CLIENT_SECRET"]),
                              data={"grant_type": "client_credentials"}, timeout=30)
            r.raise_for_status()
            self._token = r.json()["access_token"]
            self._exp = time.time() + r.json().get("expires_in", 3000) - 60
        return self._token

    @staticmethod
    def _key(path: str) -> Path:
        return CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") + ".json")

    def get(self, path: str) -> dict:
        """GET an API path like /v2/payments/captures/ID (also accepts full URLs)."""
        path = re.sub(r"^https://api(-m)?\.sandbox\.paypal\.com", "", path)
        key = self._key(path)
        if self.demo or (key.exists() and '"_synthetic": true' in key.read_text(encoding="utf-8")):
            # demo mode, or a SYNTHETIC seeded case that has no real PayPal record
            self.via[path] = "cache"
            return json.loads(key.read_text(encoding="utf-8"))
        m = re.fullmatch(r"/v1/customer/disputes/([A-Za-z0-9_-]+)", path)
        if m and mcp_paypal.enabled():
            try:  # PayPal Agent Toolkit MCP server: get_dispute tool
                body, _ = mcp_paypal.call("get_dispute", {"dispute_id": m.group(1)}, self.base)
                self.via[path] = "paypal-mcp:get_dispute"
                key.write_text(json.dumps(body, indent=2), encoding="utf-8")
                return body
            except Exception:
                pass  # fall back to REST below
        r = requests.get(f"{self.base}{path}", timeout=30,
                         headers={"Authorization": f"Bearer {self._auth()}"})
        r.raise_for_status()
        self.via[path] = "rest"
        body = r.json()
        key.write_text(json.dumps(body, indent=2), encoding="utf-8")
        return body
