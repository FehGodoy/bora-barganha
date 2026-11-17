const grid = document.querySelector('#offer-grid');
const empty = document.querySelector('#empty');
const updated = document.querySelector('#updated');
const emptyTitle = empty.querySelector('h3');
const emptyMessage = empty.querySelector('p');
const filters = [...document.querySelectorAll('.filter')];
const sort = document.querySelector('#sort');
const campaignGrid = document.querySelector('#campaign-grid');
const campaignEmpty = document.querySelector('#campaign-empty');
let offers = [];
let campaigns = [];
let activeSource = 'all';

function relativeTime(iso) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 2) return 'Atualizada agora';
  if (minutes < 60) return `Atualizada há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `Atualizada há ${hours} h`;
}

function card(offer) {
  const article = document.createElement('article');
  article.className = 'offer-card';
  const imageBox = document.createElement('div');
  imageBox.className = 'card-image';
  const image = document.createElement('img');
  image.src = offer.image;
  image.alt = offer.title;
  image.loading = 'lazy';
  image.referrerPolicy = 'no-referrer';
  const badge = document.createElement('span');
  badge.className = `store-badge ${offer.source === 'mercadolivre' ? 'ml' : ''}`;
  badge.textContent = offer.source === 'mercadolivre' ? 'Mercado Livre' : 'Shopee';
  imageBox.append(image, badge);
  const body = document.createElement('div');
  body.className = 'card-body';
  const fresh = document.createElement('div');
  fresh.className = 'card-fresh';
  fresh.textContent = relativeTime(offer.observed_at);
  const title = document.createElement('h3');
  title.className = 'card-title';
  title.textContent = offer.title;
  const label = document.createElement('div');
  label.className = 'card-price-label';
  label.textContent = 'Por';
  const price = document.createElement('div');
  price.className = 'card-price';
  price.textContent = new Intl.NumberFormat('pt-BR', {style:'currency', currency:'BRL'}).format(Number(offer.price));
  const link = document.createElement('a');
  link.className = 'card-link';
  link.href = offer.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer sponsored';
  link.textContent = 'Ver oferta na loja ↗';
  link.setAttribute('aria-label', `Ver ${offer.title} na ${badge.textContent}`);
  body.append(fresh, title, label, price, link);
  article.append(imageBox, body);
  return article;
}

function campaignCard(campaign) {
  const article = document.createElement('article');
  article.className = 'campaign-card';
  const copy = document.createElement('div');
  copy.className = 'campaign-copy';
  const label = document.createElement('span');
  label.className = 'campaign-label';
  label.textContent = campaign.kind;
  const title = document.createElement('h3');
  title.textContent = campaign.title;
  const link = document.createElement('a');
  link.className = 'campaign-link';
  link.href = campaign.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer sponsored';
  link.textContent = 'Explorar especial ↗';
  link.setAttribute('aria-label', `Explorar ${campaign.title} na Shopee`);
  const imageBox = document.createElement('div');
  imageBox.className = 'campaign-image';
  const image = document.createElement('img');
  image.src = campaign.image;
  image.alt = '';
  image.loading = 'lazy';
  image.referrerPolicy = 'no-referrer';
  copy.append(label, title, link);
  imageBox.append(image);
  article.append(copy, imageBox);
  return article;
}

function render() {
  campaignGrid.replaceChildren(...campaigns.map(campaignCard));
  campaignEmpty.hidden = campaigns.length > 0;
  const sources = new Set(offers.map(offer => offer.source));
  if (activeSource !== 'all' && !sources.has(activeSource)) activeSource = 'all';
  filters.forEach(button => {
    button.hidden = button.dataset.source !== 'all' && !sources.has(button.dataset.source);
    const selected = button.dataset.source === activeSource;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  const selected = offers.filter(offer => activeSource === 'all' || offer.source === activeSource);
  const ordered = [...selected].sort((a,b) => sort.value === 'low' ? Number(a.price)-Number(b.price) : sort.value === 'high' ? Number(b.price)-Number(a.price) : new Date(b.observed_at)-new Date(a.observed_at));
  grid.replaceChildren(...ordered.map(card));
  empty.hidden = ordered.length > 0;
  document.querySelector('#count-all').textContent = offers.length ? `(${offers.length})` : '';
}

async function loadOffers() {
  try {
    let response = await fetch('/api/offers');
    if (response.status === 404) response = await fetch(`offers.json?t=${Date.now()}`, {cache:'no-store'});
    if (!response.ok) throw new Error('Falha ao carregar ofertas');
    const data = await response.json();
    campaigns = (Array.isArray(data.campaigns) ? data.campaigns : []).filter(campaign => {
      const age = Date.now() - new Date(campaign.observed_at).getTime();
      return age >= -5 * 60 * 1000 && age <= 24 * 60 * 60 * 1000;
    });
    offers = (Array.isArray(data.offers) ? data.offers : []).filter(offer => {
      const age = Date.now() - new Date(offer.observed_at).getTime();
      const maxAge = offer.source === 'mercadolivre' ? 6 : 2;
      return age >= -5 * 60 * 1000 && age <= maxAge * 60 * 60 * 1000;
    });
    emptyTitle.textContent = 'Nenhum achadinho fresquinho por aqui.';
    emptyMessage.textContent = 'Estamos atualizando a seleção. Volte em alguns minutos para ver as próximas ofertas.';
    updated.textContent = `Seleção atualizada ${relativeTime(data.updated_at).toLowerCase().replace('atualizada ', '')}`;
  } catch {
    offers = [];
    campaigns = [];
    updated.textContent = 'Não foi possível atualizar agora';
    emptyTitle.textContent = 'Não conseguimos carregar as ofertas.';
    emptyMessage.textContent = 'Tente atualizar novamente em alguns instantes.';
  }
  render();
}

filters.forEach(button => button.addEventListener('click', () => {
  activeSource = button.dataset.source;
  filters.forEach(item => {const selected = item === button; item.classList.toggle('active', selected); item.setAttribute('aria-pressed', String(selected));});
  render();
}));
sort.addEventListener('change', render);
document.querySelector('#retry').addEventListener('click', loadOffers);
loadOffers();
setInterval(loadOffers, 5 * 60 * 1000);
