-- Preço "de" (riscado) para a vitrine: Shopee calcula pelo desconto, Mercado Livre vem da extensão.
alter table listings add column if not exists original_price text;
alter table capture_queue add column if not exists original_price numeric;

drop function if exists public.capture_offer(text,text,text,numeric,text,text,text,text,boolean);

create or replace function public.capture_offer(
  p_token text, p_external_id text, p_title text, p_price numeric, p_image_url text,
  p_page_url text, p_affiliate_link text, p_breadcrumb text, p_available boolean,
  p_original_price numeric default null
) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare v_id bigint; v_original numeric;
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
  -- Preço antigo só vale se for maior que o atual e no máximo 10x (evita valor absurdo).
  v_original := case when p_original_price > p_price and p_original_price <= p_price * 10 then p_original_price end;

  insert into capture_queue(source, external_id, title, price, image_url, page_url, affiliate_link, breadcrumb, available, original_price)
  values ('mercadolivre', p_external_id, p_title, p_price, p_image_url, split_part(p_page_url, '#', 1),
          p_affiliate_link, left(p_breadcrumb, 300), p_available, v_original)
  on conflict (source, external_id, affiliate_link) do update
    set price = excluded.price, title = excluded.title, image_url = excluded.image_url, captured_at = now(),
        available = excluded.available, original_price = excluded.original_price,
        status = case when capture_queue.status in ('aguardando','retida') then 'aguardando' else capture_queue.status end
  returning id into v_id;
  return jsonb_build_object('ok', true, 'id', v_id);
end $$;

revoke all on function public.capture_offer(text,text,text,numeric,text,text,text,text,boolean,numeric) from public;
grant execute on function public.capture_offer(text,text,text,numeric,text,text,text,text,boolean,numeric) to anon;
