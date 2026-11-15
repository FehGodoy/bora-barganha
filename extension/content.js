// Captura iniciada pelo usuário: um clique no botão envia a oferta desta página para a fila.
(() => {
  const AFFILIATE_RE = /^https:\/\/meli\.la\/[A-Za-z0-9]{4,20}$/;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function ldBlocks() {
    return [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map((s) => { try { return JSON.parse(s.textContent); } catch { return null; } })
      .flatMap((j) => (Array.isArray(j) ? j : j?.["@graph"] || [j]))
      .filter(Boolean);
  }

  function product() {
    const p = ldBlocks().find((j) => j["@type"] === "Product");
    if (!p) return null;
    const offers = Array.isArray(p.offers) ? p.offers[0] : p.offers || {};
    const image = Array.isArray(p.image) ? p.image[0] : p.image;
    const crumbs = ldBlocks().find((j) => j["@type"] === "BreadcrumbList");
    const breadcrumb = (crumbs?.itemListElement || []).map((i) => i.name || i.item?.name).filter(Boolean).join(" > ");
    const id = (String(p.sku || "").match(/^MLB\d+$/) || location.pathname.match(/MLB-?\d+/) || [""])[0].replace("-", "");
    return {
      p_external_id: id,
      p_title: String(p.name || "").trim(),
      p_price: Number(offers.price),
      p_image_url: typeof image === "string" ? image : null,
      p_page_url: location.href.split("#")[0].split("?")[0],
      p_breadcrumb: breadcrumb,
      p_available: /InStock/i.test(String(offers.availability || "")),
    };
  }

  function affiliateLink() {
    const field = [...document.querySelectorAll("textarea, input")].find((e) => AFFILIATE_RE.test(e.value.trim()));
    return field ? field.value.trim() : null;
  }

  async function ensureAffiliateLink() {
    let link = affiliateLink();
    if (link) return link;
    // Abre o painel "Compartilhar" da própria barra de afiliados do Mercado Livre.
    const share = [...document.querySelectorAll("button, a")].find((b) => b.textContent.trim() === "Compartilhar"
      && b.getBoundingClientRect().top < 80);
    if (!share) return null;
    share.click();
    for (let i = 0; i < 20 && !link; i++) { await sleep(250); link = affiliateLink(); }
    return link;
  }

  function toast(text, error = false) {
    document.getElementById("bora-capture-toast")?.remove();
    const el = Object.assign(document.createElement("div"), { id: "bora-capture-toast", textContent: text });
    if (error) el.classList.add("err");
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 6000);
  }

  async function capture(btn) {
    btn.disabled = true;
    try {
      const data = product();
      if (!data || !data.p_external_id || !(data.p_price > 0)) return toast("Não encontrei os dados do produto nesta página.", true);
      if (!data.p_available) return toast("Produto aparece sem estoque; não enviado.", true);
      const link = await ensureAffiliateLink();
      if (!link) return toast("Não achei o link meli.la. Clique em “Compartilhar” na barra de afiliados e tente de novo.", true);
      const res = await chrome.runtime.sendMessage({ type: "capture", payload: { ...data, p_affiliate_link: link } });
      res?.ok ? toast(`Na fila ✅  ${data.p_title.slice(0, 50)} — R$ ${data.p_price.toFixed(2).replace(".", ",")}`)
              : toast(`Não enviado: ${res?.error || "erro desconhecido"}`, true);
    } finally {
      btn.disabled = false;
    }
  }

  function mount() {
    if (document.getElementById("bora-capture-btn") || !product()) return;
    const btn = Object.assign(document.createElement("button"), { id: "bora-capture-btn", textContent: "➕ Bora Barganha" });
    btn.addEventListener("click", () => capture(btn));
    document.body.appendChild(btn);
  }

  mount();
  new MutationObserver(() => mount()).observe(document.documentElement, { childList: true, subtree: true });
})();
