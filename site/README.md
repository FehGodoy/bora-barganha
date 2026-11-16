# Vitrine Bora Barganha na Vercel

A página é HTML/CSS/JS estático. Não precisa de Next.js. A função `api/offers.py` lê ofertas recentes no Supabase pelo `SUPABASE_DB_URL` configurado na Vercel e devolve apenas os campos públicos. A resposta fica em cache por até cinco minutos na CDN. O navegador busca novos dados a cada cinco minutos e esconde ofertas vencidas.

## Prévia local da página

```powershell
python build_site.py --empty
python -m http.server 8765 --directory site/dist
```

Abra `http://localhost:8765`. Sem a API da Vercel, a página usa o `offers.json` local como fallback. `--empty` evita acesso ao banco.

## Publicação

1. Peça o commit e push quando estiver pronto. A regra do projeto impede essas ações sem seu pedido explícito.
2. Na Vercel, importe `FehGodoy/bora-barganha` com a raiz do projeto como **Root Directory**. O `vercel.json` configura o build e a pasta de saída.
3. Em **Settings → Environment Variables**, cadastre `SUPABASE_DB_URL` para **Production** usando o Session pooler do projeto Bora Barganha. O valor deve ser inserido por você; nunca vai para o repositório ou navegador.
4. Faça o deploy e verifique a página e `/api/offers`. Se a variável for cadastrada depois do primeiro deploy, faça um novo deploy para aplicá-la.

O GitHub Actions `worker.yml` foi ajustado para `--collect-only`: coleta Shopee e importa a fila do Mercado Livre, sem preparar artes nem enviar mensagens ao WhatsApp. Isso só entra em vigor após commit e push. Para pausar envios **imediatamente**, defina `BORA_OFFER_SEND_ENABLED=false` em **GitHub → Settings → Secrets and variables → Actions → Variables**.

O exportador inclui apenas candidatas com imagem, preço positivo, link HTTPS de afiliado permitido e última observação dentro de 2 horas (Shopee) ou 6 horas (Mercado Livre). Preço e estoque devem ser confirmados na loja.
