"""Gera extension/config.js a partir do .env.local (o arquivo gerado fica fora do Git)."""

import json
from pathlib import Path

ROOT = Path(__file__).parent
env = {}
for raw in (ROOT / ".env.local").read_text(encoding="utf-8").splitlines():
    if "=" in raw and not raw.lstrip().startswith("#"):
        key, value = raw.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")

config = {
    "supabaseUrl": env["SUPABASE_URL"],
    "publishableKey": env["SUPABASE_PUBLISHABLE_KEY"],
    "captureToken": env["CAPTURE_TOKEN"],
}
(ROOT / "extension" / "config.js").write_text("self.BORA_CONFIG = " + json.dumps(config) + ";\n", encoding="utf-8")
print("extension/config.js gerado. Recarregue a extensão em chrome://extensions.")
