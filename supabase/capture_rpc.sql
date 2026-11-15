-- Entrada da extensão: função pública que só insere na capture_queue após validar token e formatos.
create extension if not exists pgcrypto;

create table if not exists capture_tokens (
  token_hash text primary key,
  label text not null,
  created_at timestamptz not null default now()
);
alter table capture_tokens enable row level security;
alter table capture_queue add column if not exists breadcrumb text;
alter table capture_queue add column if not exists available boolean;

create or replace function public.capture_offer(
  p_token text, p_external_id text, p_title text, p_price numeric, p_image_url text,
  p_page_url text, p_affiliate_link text, p_breadcrumb text, p_available boolean
) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare v_id bigint;
begin
  if not exists (select 1 from capture_tokens where token_hash = encode(digest(coalesce(p_token,''), 'sha256'), 'hex')) then
    raise exception 'token inválido' using errcode = '28000';
  end if;
  if p_external_id !~ '^MLB[0-9]{5,15}$' then raise exception 'ID MLB inválido'; end if;
  if p_affiliate_link !~ '^https://meli\.la/[A-Za-z0-9]{4,20}$' then raise exception 'link de afiliado inválido'; end if;
  if p_page_url !~ '^https://([a-z]+\.)?mercadolivre\.com\.br/' then raise exception 'página fora do Mercado Livre'; end if;
  if p_image_url is not null and p_image_url !~ '^https://[a-z0-9.-]*mlstatic\.com/' then raise exception 'imagem fora do CDN do Mercado Livre'; end if;
  if p_price is null or p_price <= 0 or p_price > 100000 then raise exception 'preço inválido'; end if;
  if length(coalesce(p_title,'')) not between 3 and 300 then raise exception 'título inválido'; end if;

  insert into capture_queue(source, external_id, title, price, image_url, page_url, affiliate_link, breadcrumb, available)
  values ('mercadolivre', p_external_id, p_title, p_price, p_image_url, split_part(p_page_url, '#', 1),
          p_affiliate_link, left(p_breadcrumb, 300), p_available)
  on conflict (source, external_id, affiliate_link) do update
    set price = excluded.price, title = excluded.title, image_url = excluded.image_url, captured_at = now(),
        available = excluded.available,
        status = case when capture_queue.status in ('aguardando','retida') then 'aguardando' else capture_queue.status end
  returning id into v_id;
  return jsonb_build_object('ok', true, 'id', v_id);
end $$;

revoke all on function public.capture_offer(text,text,text,numeric,text,text,text,text,boolean) from public;
grant execute on function public.capture_offer(text,text,text,numeric,text,text,text,text,boolean) to anon;
