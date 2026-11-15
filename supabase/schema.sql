-- Bora Barganha: schema inicial (espelha data/offers.sqlite3 + fila de captura manual).
-- RLS ligado em todas as tabelas e sem políticas: só a service_role (worker) acessa.

create table if not exists listings (
  listing_key text primary key,            -- shopee:<shop>:<item> | mlb:<id>
  source text not null default 'shopee',
  canonical_key text not null,
  title text not null,
  image_url text,
  offer_link text,
  product_link text,
  price_min numeric,
  price_max numeric,
  rating numeric,
  sales integer,
  commission_rate text,
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  lowest_seen numeric,
  status text not null,
  hold_reason text
);
create index if not exists listings_canonical_idx on listings(canonical_key);
create index if not exists listings_status_idx on listings(status);

create table if not exists price_history (
  id bigint generated always as identity primary key,
  listing_key text not null references listings(listing_key) on delete cascade,
  observed_at timestamptz not null default now(),
  price_min numeric not null,
  price_max numeric not null
);

create table if not exists publications (
  id bigint generated always as identity primary key,
  canonical_key text not null,
  channel text not null,                   -- whatsapp | instagram
  published_at timestamptz not null default now(),
  price numeric not null,
  external_id text not null,
  unique(channel, external_id)
);
create index if not exists publications_lookup_idx on publications(channel, canonical_key, published_at);

create table if not exists publication_jobs (
  draft_id text primary key,
  listing_key text not null,
  canonical_key text not null,
  channel text not null,
  status text not null,                    -- reserved | sent
  reserved_at timestamptz not null default now(),
  external_id text
);

create table if not exists state (
  key text primary key,
  value text not null
);

create table if not exists drafts (
  listing_key text primary key,
  data jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists capture_queue (       -- ofertas capturadas pela extensão (Mercado Livre)
  id bigint generated always as identity primary key,
  source text not null default 'mercadolivre',
  external_id text not null,               -- MLB...
  title text not null,
  price numeric,
  image_url text,
  page_url text not null,
  affiliate_link text not null,
  captured_at timestamptz not null default now(),
  status text not null default 'aguardando',
  hold_reason text,
  unique(source, external_id, affiliate_link)
);

create table if not exists worker_runs (
  id bigint generated always as identity primary key,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  mode text not null,
  outcome text,
  detail text
);

create table if not exists worker_steps (
  id bigint generated always as identity primary key,
  run_id bigint not null references worker_runs(id) on delete cascade,
  at timestamptz not null default now(),
  step text not null,
  ok boolean not null,
  detail text
);

do $$
declare t text;
begin
  foreach t in array array['listings','price_history','publications','publication_jobs','state','drafts','capture_queue','worker_runs','worker_steps']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('grant all on %I to service_role', t);
  end loop;
end $$;
grant usage, select on all sequences in schema public to service_role;

insert into storage.buckets (id, name, public) values ('artes', 'artes', true)
on conflict (id) do nothing;
