-- Dispara o worker do GitHub Actions no horário certo (o cron do GitHub atrasa ou pula execuções).
-- O token fica no Vault com o nome 'github_dispatch_token'; nunca vai para o código.
create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;

create or replace function public.dispatch_worker() returns bigint
language sql security definer set search_path = public, extensions as $$
  select net.http_post(
    url := 'https://api.github.com/repos/FehGodoy/bora-barganha/actions/workflows/worker.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'bora-barganha-cron'),
    body := '{"ref":"main"}'::jsonb);
$$;
revoke all on function public.dispatch_worker() from public, anon, authenticated;

-- 8h às 21h de Brasília (11h-00h UTC), nos minutos 7, 27 e 47.
select cron.unschedule(jobid) from cron.job where jobname = 'bora-worker';
select cron.schedule('bora-worker', '7,27,47 0,11-23 * * *', 'select public.dispatch_worker()');
