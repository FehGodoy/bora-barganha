importScripts("config.js"); // gerado por build_extension.py a partir do .env.local (não vai para o Git)

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg?.type !== "capture") return false;
  const cfg = self.BORA_CONFIG;
  fetch(`${cfg.supabaseUrl}/rest/v1/rpc/capture_offer`, {
    method: "POST",
    headers: { apikey: cfg.publishableKey, "Content-Type": "application/json" },
    body: JSON.stringify({ p_token: cfg.captureToken, ...msg.payload }),
  })
    .then(async (r) => {
      const body = await r.json().catch(() => ({}));
      reply(r.ok ? { ok: true, id: body.id } : { ok: false, error: body.message || `HTTP ${r.status}` });
    })
    .catch(() => reply({ ok: false, error: "falha de rede" }));
  return true; // resposta assíncrona
});
