# Bora Barganha — plano técnico inicial

## Objetivo
Executar ciclos automáticos de descoberta, seleção, conferência e publicação de ofertas de beleza. Cada oferta tem produto, preço observado, imagem de origem, link de afiliado, arte/vídeo, texto para Instagram e texto para WhatsApp. Nenhum dado deve ser digitado manualmente para as ofertas da Shopee após a integração estar ativa.

## Fluxo
1. Agendador inicia uma rodada em intervalos configuráveis.
2. Adaptadores consultam fontes autorizadas: Shopee Affiliate Open API e Mercado Livre Developers API.
3. Normalização: identificador, título, preço, disponibilidade, loja/vendedor, imagem, URL e data da coleta.
4. Filtros: categoria de beleza, preço máximo, vendedor, disponibilidade, repetição e qualidade da imagem.
5. Histórico de preços, pontuação e identificação do produto evitam promoções falsas e repetição entre anúncios e lojas.
6. O link de afiliado é gerado/verificado antes de qualquer publicação. Sem link válido, a oferta fica pendente.
7. A API da OpenAI cria textos estruturados a partir dos fatos verificados, sem inventar preço, desconto, qualidade ou resultado de uso.
8. Validador visual rejeita imagens do vendedor com preço, cupom, data vencida ou banner promocional. Só depois o renderizador gera arte de feed e Reel a partir de imagem fiel do produto, preferencialmente recortada, texto e animação.
9. Imagem/vídeo ficam em armazenamento com URL pública temporária para a API do Instagram.
10. Publicadores independentes enviam ao Instagram e ao grupo. O estado de cada canal é gravado separadamente para permitir retomada sem duplicar posts.
11. Logs e alertas registram falhas, publicação, preço observado e links usados.

## Integrações
- Shopee: priorizar a Affiliate Open API para descobrir ofertas e gerar links rastreáveis. Confirmar operações, quotas e credenciais no painel da conta reativada.
- Mercado Livre: a Developers API fornece tendências e dados de produtos. O programa de afiliados documenta geração de links pelo portal/barra; não foi encontrada uma API pública de geração de links de afiliado. Enquanto não houver integração autorizada, as ofertas do Mercado Livre ficam em fila pendente de link. Não usar scraping/curl da página como base: os termos de Developers proíbem robôs/scraping para acessar conteúdo fora da API.
- Instagram: conta profissional e app Meta com permissão de publicação. Fluxo: criar contêiner de mídia, aguardar processamento, publicar e salvar ID retornado.
- WhatsApp: reutilizar a instância Evolution Manager 2.3.7 já conectada ao mesmo número, conforme escolha do proprietário. O outro grupo recebe mensagens apenas a cada 13 dias. O Bora Barganha tem configuração própria e um único JID de grupo permitido; o publicador recusa qualquer destino diferente e não envia mensagens individuais. O teste manual está em `evolution_publisher.py`, desativado por padrão e condicionado ao nome do grupo na API. Em 15/11/2026, a consulta retornou `Bora Barganha #10` e `Financeiro OHEL`; o JID do primeiro foi configurado somente no `.env.local` e uma única mensagem de teste foi confirmada pela Evolution (ID registrado no resultado local da execução). O envio automático segue desligado. Antes do agendamento de ofertas, implementar teto diário, intervalo entre ofertas, idempotência e pausa de emergência. O grupo tem entrada livre pelo link público da bio.
- OpenAI API: gerar legenda e mensagem em JSON estruturado; informações comerciais vêm somente dos dados verificados.
- `prepare_offer.py` implementa o primeiro preparo em modo rascunho: escolhe candidata recente sem publicação no WhatsApp em sete dias, usa visão da OpenAI para reprovar foto promocional com preço/data ou produto divergente, gera frases curtas sem fatos comerciais e insere título/preço/link diretamente dos dados Shopee. Salva JSON e arte em `drafts/`, sem publicar. A foto reprovada marca o anúncio como retido; a mesma imagem continua retida após nova coleta. Em 15/11/2026, uma imagem Hidrabene divergente foi retida e um rascunho Perfect Corpus foi criado. `revalidate_shopee.py` consultou o `itemId` e `shopId` exatos na API antes da publicação e confirmou preço e link. `publish_whatsapp.py` confere grupo, preço, link e impressão digital da imagem; exige `--send` mais `BORA_OFFER_SEND_ENABLED=true`. A fila local reserva tentativas, limita a três ofertas por dia, mantém três horas entre ofertas e impede repetição do produto em sete dias; tentativas incertas exigem reconciliação manual. Uma única oferta Perfect Corpus foi enviada ao grupo Bora Barganha #10 via `/message/sendMedia` e confirmada pela Evolution (ID `3EB01A293E84EB2A3E5F02`); o job ficou `sent` e `publications` tem um registro WhatsApp. O flag persistente segue `false`. Nenhuma oferta foi enviada ao Instagram.

## Shopee Open API — verificado no painel autenticado em 15/11/2026
- Status da conta: "Meu API: Válido". Credenciais estão somente no `.env.local` ignorado pelo Git.
- Endpoint GraphQL documentado: `https://open-api.affiliate.shopee.com.br/graphql`.
- Autenticação: header `Authorization` com `Credential`, `Timestamp` e assinatura SHA-256 de `AppID + Timestamp + corpo JSON exato + Secret`. O relógio do cliente deve estar a menos de 10 minutos do servidor.
- Limite indicado no guia: 8.000 chamadas por hora. Consultas sem `scrollId` têm intervalo mínimo documentado de 30 segundos; `scrollId` expira em 30 segundos.
- `productOfferV2` devolve `itemId`, `shopId`, `productName`, `imageUrl`, `priceMin`, `priceMax`, `ratingStar`, `sales`, `priceDiscountRate`, `productLink`, `offerLink` e prazo da oferta. O `offerLink` já é o link da oferta para divulgação.
- `generateShortLink` converte URL de produto em link rastreável com até cinco `subIds` quando necessário.
- Como `priceMin` e `priceMax` podem representar variantes diferentes, a primeira versão só publica valor fechado quando forem iguais. Caso contrário, usa "a partir de" ou retém a oferta até validar a variante exata.
- Consulta real executada em 15/11/2026: `productOfferV2` retornou cinco ofertas com `offerLink` e preços; houve também respostas intermitentes de erro interno 10000. O coletor respeita intervalo de 31 segundos entre consultas iniciais e mantém a publicação desativada.
## Política de canais
- Shopee permite divulgar links no WhatsApp; identificar conteúdo com comissão como publicidade.
- Mercado Livre informa que links de afiliado em WhatsApp/Telegram são aceitos somente em canais públicos e abertos e veda grupos fechados. Confirmar no programa se o grupo do Bora Barganha, com entrada livre pela bio, é elegível antes de habilitar publicação automática de links do Mercado Livre nele.
- Não postar preço antigo calculado ou economia percentual sem fonte confiável. Conferir preço, estoque e link imediatamente antes da publicação.

## Regra de repetição de produtos
- Identificar a oferta pelo ID do anúncio na origem e identificar o produto canônico por GTIN/EAN quando existir; na ausência dele, usar marca, modelo, volume/tamanho e variante normalizados. Tons de maquiagem, fragrâncias e tamanhos diferentes não devem ser confundidos.
- Deduplicar também entre Shopee e Mercado Livre. Se houver dois anúncios do mesmo produto na mesma rodada, escolher a melhor oferta válida e guardar o outro como alternativa; não publicar duas artes quase iguais.
- Padrão inicial configurável: o mesmo produto canônico não volta ao Instagram por 30 dias nem ao WhatsApp por 7 dias. Uma queda real de pelo menos 10% em relação ao último preço publicado pode antecipar a volta ao grupo, desde que tenham passado 24 horas. O Instagram continua com limite de 30 dias até termos dados para ajustá-lo.
- Cada produto e canal guarda último horário, último preço, ID externo publicado e motivo da republicação. Uma tentativa que falhou pode ser retomada; uma que já foi confirmada não é enviada de novo.
- Quando o identificador canônico estiver incerto, reter a oferta para revisão automática adicional ou deixar de publicá-la. Melhor perder um candidato do que repetir o mesmo item com outro título.
## Componentes do projeto
- worker: agendamento, execução e retomada.
- sources/shopee e sources/mercado_livre: coleta e normalização.
- scoring: filtros, histórico e deduplicação.
- affiliate_links: geração e validação por plataforma.
- copy: chamada à OpenAI e validação dos fatos retornados.
- creative: arte e vídeo com a identidade aprovada.
- publishers/instagram e publishers/evolution: publicações com idempotência.
- storage: banco de dados e arquivos gerados.
- admin: painel futuro para ajustar categorias, horários, limites e ver erros.

## Estados mínimos
`descoberta -> validada -> link_pronto -> criativo_pronto -> instagram_publicado -> whatsapp_publicado`
Cada transição guarda horário, erro e identificador externo. Uma falha em WhatsApp não refaz a postagem do Instagram.

## Infraestrutura inicial
O trabalho pode rodar em ciclos agendados, sem processo 24 horas. GitHub Actions oferece execução agendada no plano gratuito, mas horários podem atrasar e projetos privados têm cota mensal. Para persistência, usar banco e armazenamento externos gratuitos dedicados ao Bora Barganha. Antes de escolher o provedor final, confirmar onde o Evolution Manager já está hospedado: se houver VPS disponível, o worker pode rodar nela e simplificar a infraestrutura. Reels com FFmpeg exigem ambiente com CPU e armazenamento adequados; Cloudflare Workers Free tem CPU insuficiente para renderização de vídeo.

## Ordem de implementação
1. Shopee Afiliados: painel Abrir API indica acesso válido em 15/11/2026; chamada GraphQL real retornou cinco anúncios. Evolution: chave funcional, grupo identificado e teste único confirmado; falta automatizar publicações de ofertas com os limites e verificações previstos.
2. Criar projeto independente, configuração sem segredos no repositório e adaptadores com respostas simuladas.
3. Ciclo Shopee: coleta, filtro, link da API, texto, inspeção de imagem, arte, revalidação exata e um envio real controlado ao grupo implementados e exercitados. Fila de WhatsApp, limite diário, intervalo, idempotência e renderer final implementados; agendamento ainda desligado. Próximo: integração Instagram/Meta e hospedagem do agendador com banco persistente antes de ligar o ciclo completo.
4. Conectar publicações reais, primeiro em ambiente de teste/baixa frequência, com limite diário e pausa de emergência.
5. Adicionar Reels automáticos.
6. Integrar Mercado Livre via APIs oficiais; habilitar link/publicação apenas depois de confirmar um método autorizado de geração e canal elegível.

## Fontes consultadas em 15/11/2026
- https://help.shopee.com.br/portal/10/article/170264-%5BFAQ%5D%20Onde%20posso%20divulgar%20meus%20links%20de%20Afiliado%3F
- https://help.shopee.com.br/portal/10/article/163046-Saiba-Onde-Compartilhar-Seus-Links-de-Afiliado
- https://developers.mercadolivre.com.br/pt_br/termos-e-condicoes
- https://developers.mercadolivre.com.br/devcenter/tendencias
- https://developers.mercadolivre.com.br/pt_br/escolha-tipo-de-servico/mais-vendidos-no-mercado-livre
- https://www.mercadolivre.com.br/l/afiliados-gere-seus-links
- https://www.mercadolivre.com.br/l/afiliados-compartilhamento-de-publicacao
- https://www.postman.com/meta/instagram/collection/6yqw8pt/instagram-api
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://developers.cloudflare.com/workers/platform/limits/








