"""Integração restrita ao grupo Bora Barganha na instância Evolution existente.

Sem configuração de envio, este módulo só lista grupos ou mostra uma prévia.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
GROUP_JID = re.compile(r"^[0-9]{10,25}@g\.us$")
ENV_KEYS = {"EVOLUTION_BASE_URL", "EVOLUTION_INSTANCE", "EVOLUTION_API_KEY", "BORA_GROUP_JID", "BORA_SEND_ENABLED", "BORA_OFFER_SEND_ENABLED"}


def load_evolution_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ENV_KEYS:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def settings() -> tuple[str, str, str, str]:
    load_evolution_env(ROOT / ".env.local")
    base = os.environ.get("EVOLUTION_BASE_URL", "").strip().rstrip("/")
    instance = os.environ.get("EVOLUTION_INSTANCE", "").strip()
    api_key = os.environ.get("EVOLUTION_API_KEY", "").strip()
    group = os.environ.get("BORA_GROUP_JID", "").strip()
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("EVOLUTION_BASE_URL deve ser uma URL HTTPS válida, sem credenciais ou parâmetros")
    if not instance or "/" in instance or "?" in instance or "#" in instance:
        raise ValueError("EVOLUTION_INSTANCE ausente ou inválida")
    if not api_key:
        raise ValueError("EVOLUTION_API_KEY ausente")
    return base, instance, api_key, group


def request_json(base: str, instance: str, api_key: str, method: str, endpoint: str, payload: dict | None = None, query: str = "") -> object:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = Request(
        f"{base}{endpoint}/{quote(instance, safe='')}{query}",
        data=body,
        method=method,
        headers={"apikey": api_key, "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Evolution respondeu HTTP {exc.code} em {endpoint}") from None
    except URLError as exc:
        raise RuntimeError(f"Não foi possível acessar a Evolution: {exc.reason}") from None


def list_groups(base: str, instance: str, api_key: str) -> list[dict]:
    data = request_json(base, instance, api_key, "GET", "/group/fetchAllGroups", None, "?getParticipants=false")
    if not isinstance(data, list):
        raise RuntimeError("A Evolution não devolveu uma lista de grupos")
    return [group for group in data if isinstance(group, dict)]


def send_test(base: str, instance: str, api_key: str, configured_group: str, recipient: str) -> str:
    if not GROUP_JID.fullmatch(configured_group):
        raise ValueError("BORA_GROUP_JID ausente ou inválido")
    if recipient != configured_group:
        raise ValueError("Destino recusado: somente BORA_GROUP_JID é permitido")
    if os.environ.get("BORA_SEND_ENABLED", "").strip().lower() != "true":
        raise ValueError("Envio desativado. Configure BORA_SEND_ENABLED=true para o teste")
    matches = [item for item in list_groups(base, instance, api_key) if item.get("id") == recipient]
    if len(matches) != 1 or "bora barganha" not in str(matches[0].get("subject") or "").casefold():
        raise ValueError("O grupo configurado não foi confirmado como Bora Barganha na Evolution")
    message = "Teste de conexão do Bora Barganha ✅\nEste grupo receberá ofertas de beleza e autocuidado. Nenhuma publicação automática foi ativada ainda."
    data = request_json(base, instance, api_key, "POST", "/message/sendText", {"number": recipient, "text": message})
    if not isinstance(data, dict):
        raise RuntimeError("Resposta de envio inesperada")
    key = data.get("key")
    if not isinstance(key, dict) or key.get("remoteJid") != recipient or not key.get("id"):
        raise RuntimeError("Envio sem confirmação inequívoca do destino pela Evolution")
    return str(key["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Consulta grupos e envia um teste controlado pela Evolution")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list-groups", action="store_true", help="Lista apenas JID e nome dos grupos")
    action.add_argument("--send-test", action="store_true", help="Envia um único texto de teste ao grupo configurado")
    parser.add_argument("--recipient", help="JID explícito do grupo; deve corresponder ao BORA_GROUP_JID")
    args = parser.parse_args()
    try:
        base, instance, api_key, group = settings()
        if args.list_groups:
            for item in list_groups(base, instance, api_key):
                jid = item.get("id", "")
                if isinstance(jid, str) and GROUP_JID.fullmatch(jid):
                    print(f"{item.get('subject') or '(sem nome)'} | {jid}")
        else:
            if not args.recipient:
                raise ValueError("Informe --recipient com o JID do grupo")
            print(f"Teste confirmado; ID da mensagem: {send_test(base, instance, api_key, group, args.recipient)}")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
