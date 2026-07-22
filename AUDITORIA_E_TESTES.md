# Auditoria funcional, técnica e de segurança

Data da consolidação: 22/07/2026

Projeto: Divulgaí IA

Escopo: frontend, backend, banco de dados, migrations, autenticação, autorização, integrações, filas, uploads, webhooks, documentação e testes.

Este documento descreve o estado observado no working tree ao fim da auditoria. Ele não é um laudo de pentest nem certifica aprovações de terceiros. Nenhum token, senha, chave privada ou credencial real é reproduzido aqui.

## Legenda

- **Validado**: existe evidência automatizada ou verificação em navegador registrada nesta auditoria.
- **Implementado**: o fluxo existe e foi inspecionado, mas depende da execução final consolidada ou de infraestrutura externa.
- **Simulado/mockado**: a lógica foi exercitada sem chamada real a serviços externos.
- **Externo**: depende de credencial, conta, permissão, aprovação ou infraestrutura não disponível neste ambiente.
- **Pendente final**: deve ser preenchido depois da última execução, já com todas as alterações integradas.

## Resumo executivo

O projeto deixou de ser apenas uma interface demonstrativa e passou a possuir fluxos persistentes para autenticação, contatos, consentimentos, listas, campanhas, conteúdo assistido, integrações por empresa, histórico, configurações e administração. O modo simulado é explícito e não registra uma chamada externa bloqueada como sucesso real.

As principais correções concentraram-se em:

- isolamento multi-tenant e credenciais criptografadas por empresa;
- revogação/rotação de sessão e eliminação do takeover por `ADMIN_EMAIL`;
- falha segura de configuração em produção;
- consentimento, opt-out e bloqueio permanente;
- idempotência e estados duráveis de campanhas/tarefas;
- validação de uploads, CSV e webhooks;
- templates WhatsApp confirmados pela Meta;
- endpoints reais de configurações, listas, administração e histórico;
- contratos entre HTML e JavaScript, responsividade, modais e feedback de interface;
- documentação reproduzível para PowerShell, Linux/macOS, Docker, migrations e testes.

Há evidência de **46 testes aprovados em baterias direcionadas distintas** (26 + 19 + 1 E2E), além de uma validação Edge/CDP de administração e histórico sem erro JavaScript ou HTTP. Esses números não substituem a execução final da suíte completa, pois as baterias ocorreram em momentos diferentes do trabalho.

> **TOTAL FINAL DA SUÍTE:** `[PREENCHER APÓS python -m pytest -q: ___ aprovados, ___ reprovados, ___ ignorados, duração ___]`

> **STARTUP SMOKE FINAL:** `[PREENCHER: comando, porta, GET /health, status HTTP, resposta resumida e encerramento do processo]`

> **BROWSER/CDP FINAL APÓS A ÚLTIMA ALTERAÇÃO:** `[PREENCHER OU MARCAR N/A: navegador, páginas, viewport mobile, console, rede e resultado]`

## Escopo efetivamente inspecionado

- Estrutura de pastas e arquivos de inicialização.
- Configuração Pydantic, `.env.example`, dependências e ambientes.
- FastAPI, middleware, handlers, health check, CORS e cabeçalhos.
- Models SQLAlchemy, relacionamentos, índices, unicidade e cascatas.
- Cadeia Alembic `001` a `004`.
- Schemas e validadores Pydantic.
- Todas as rotas em `app/routes/`.
- Serviços de IA, WhatsApp, Facebook, Instagram, consentimento, tracking, rate limit e credenciais.
- Celery worker, beat, despacho, retries e reconciliação.
- Templates, componentes, CSS, JavaScript, estados vazios, toasts, modais e navegação.
- Dockerfile, Docker Compose e `.dockerignore` por inspeção estática.
- Testes preexistentes e novos testes de regressão/integração.

## Checklist de funcionalidades e promessas

| Área/promessa | Estado | Evidência ou ressalva |
|---|---|---|
| Landing page, login, cadastro, privacidade e termos | Implementado | Rotas e templates existem; `test_pages.py` verifica HTML, marcadores e assets. Resultado final fica no total consolidado. |
| Navegação autenticada, sidebar, menu mobile e contexto do usuário | Implementado | Páginas privadas validam cookie/sessão e redirecionam anônimos; contratos DOM foram adicionados. |
| Cadastro e login | Validado parcialmente | Casos válidos, validações, duplicidade, senha incorreta e bloqueio possuem testes. |
| Refresh, logout e revogação de sessão | Validado em bateria direcionada | JWT distingue access/refresh, usa versão da sessão e rotação; cookies antigos de refresh são removidos. Revalidar na suíte final após as últimas alterações. |
| Recuperação de senha | Limitação explícita | Endpoint informa `configured=false`; envio de e-mail ainda não está implementado e a interface não promete sucesso. |
| Dashboard sem números inventados | Implementado | Métricas, gráfico e atividades consultam tabelas da empresa autenticada. |
| Contatos, busca, filtros, edição e exclusão | Validado parcialmente | Normalização, duplicidade, rollback, escopo por empresa e exclusão/anonymização foram cobertos. |
| Consentimento, revogação, opt-out e bloqueio permanente | Validado | E2E e regressões confirmam bloqueio de novo envio, idempotência e isolamento por empresa. |
| Listas de contatos e membros | Validado em bateria direcionada | CRUD, inclusão/remoção idempotente e isolamento multi-tenant. |
| Importação/exportação CSV | Implementado e testado por regressão | UTF-8, tamanho, cabeçalhos, linhas inválidas, rollback e neutralização de fórmulas de planilha. |
| Exportação LGPD | Implementado | Exporta dados do contato; exclusão preserva histórico por anonimização quando necessário. |
| CRUD, duplicação, prévia, envio e cancelamento de campanhas | Implementado e parcialmente validado | Estados processados preservam histórico; reenvio duplicado é bloqueado; botões possuem handlers. |
| Upload de imagem/vídeo | Validado por regressão | JPG, PNG, WebP e MP4; tamanho, assinatura, cota por empresa, substituição e bloqueio após processamento. |
| Agendamento e fuso horário | Validado no modo eager | Datas passadas são recusadas sem persistência parcial; E2E processa tarefa simulada. Worker/Redis reais permanecem externos. |
| Prevenção de execução duplicada | Implementado | Claim condicional de destinatário, idempotency key, estados de tarefa e reconciliação de campanhas presas. |
| Histórico, filtros, paginação e detalhe | Validado | Bateria final de administração/histórico e Edge/CDP confirmaram filtros combinados, 25/5 itens e modal. |
| Geração de conteúdo por IA | Simulado/mockado | Simulação é identificada; modo real exige integração ativa da empresa. Chaves e limites por tenant foram testados com mocks. |
| Edição e aprovação humana de conteúdo | Validado no E2E | Conteúdo gerado foi editado, aprovado e usado no fluxo de campanha simulada. |
| Integrações e credenciais | Validado com mocks | Criptografia, máscara, atualização, teste, remoção e isolamento por empresa. Nenhum segredo volta ao navegador. |
| WhatsApp Business Cloud API | Simulado/mockado | Serviço oficial implementado; consentimento, template, idempotência, eventos e opt-out cobertos sem disparo real. |
| Templates WhatsApp | Simulado/mockado | Sincronização oficial mockada, escopo por empresa e exigência de template `approved`; template local permanece `pending`. |
| Facebook Pages | Implementado, externo | Publicação por Graph API e estados simulados implementados; nenhuma publicação real foi feita. |
| Instagram profissional | Implementado, externo | Contêiner de mídia, polling de vídeo e publicação implementados; exige URL HTTPS pública e conta profissional. |
| Webhook Meta | Validado com payloads assinados/mocks | Verificação, HMAC, limite de 2 MB, tenant, monotonicidade, deduplicação e opt-out. |
| Tracking de links e cliques | Validado com testes | Token assinado, redirecionamento e deduplicação diária por campanha/fingerprint. |
| Configurações de perfil/empresa/senha | Validado em bateria direcionada | GET/PATCH, e-mail, fuso IANA, preferências, limites, senha atual e revogação da sessão. |
| Administração global | Validado | Autorização, usuários, bloqueio, empresas, limites, campanhas, logs e erros de integração. |
| Auditoria e tratamento de erros | Implementado | Ações importantes geram `AuditLog`; erros externos viram resposta controlada e falhas inesperadas não expõem stack trace. |
| Responsividade/acessibilidade básica | Validado parcialmente em Edge/CDP | Administração e histórico passaram em desktop/mobile e o foco de modal foi corrigido. Revalidação global final permanece indicada. |
| Docker Compose completo | Inspeção estática | CLI Docker não existe neste ambiente; imagem e serviços não puderam ser construídos/executados. |
| PostgreSQL e Redis reais | Externo | Código/configuração preparados; testes automatizados usam SQLite/eager e não certificam a infraestrutura real. |

## Inventário de páginas e rotas

Páginas encontradas:

- Públicas: `/`, `/login`, `/cadastro`, `/privacidade`, `/termos`.
- Autenticadas: `/dashboard`, `/contatos`, `/campanhas`, `/conteudo-ia`, `/integracoes`, `/historico`, `/configuracoes`.
- Restrita a administrador: `/administracao`.

Grupos de API encontrados:

- `/api/auth`: cadastro, login, refresh, logout e aviso de recuperação de senha.
- `/api/dashboard`: métricas e atividades da empresa.
- `/api/contacts`: contatos, consentimentos, listas, CSV e exportação do titular.
- `/api/campaigns`: CRUD, duplicação, upload, envio, cancelamento, histórico, detalhe e tarefas.
- `/api/content`: geração e aprovação de conteúdo.
- `/api/integrations`: credenciais, teste oficial, remoção e templates WhatsApp.
- `/api/settings`: leitura/atualização do perfil e alteração de senha.
- `/api/admin`: overview, usuários, empresas, limites, campanhas, logs e erros.
- `/webhooks/meta`: verificação e eventos da Meta.
- `/track/{token}`: tracking assinado e redirecionamento.
- `/health`: disponibilidade do banco e indicação do ambiente/modo.

## Erros encontrados, causas e correções

| Problema encontrado | Causa raiz | Correção realizada |
|---|---|---|
| Variáveis `NOME=valor` falhavam quando coladas no PowerShell | Sintaxe de shell Unix usada no PowerShell | README agora usa `$env:NOME = "valor"`, explica a diferença para `.env` e inclui Linux/macOS. |
| Cadastro público poderia promover o e-mail configurado como administrador | Confiança em `ADMIN_EMAIL` no fluxo público | Todo cadastro cria `Role.user`; criação/promoção administrativa ocorre somente por `python -m app.utils.create_admin`. |
| Logout/bloqueio/senha não revogavam necessariamente tokens já emitidos | JWT era autocontido sem versão de sessão | `token_version` no usuário, migration `002`, rotação no refresh e incremento em logout, senha e bloqueio administrativo. |
| Refresh podia aceitar tipo de token incorreto ou deixar cookies legados conflitantes | Validação/caminhos de cookie incompletos | Claim `type`, `jti`, `iat`, expiração, rotação e remoção dos caminhos atual e legado. |
| `sub` JWT malformado poderia gerar erro interno | Conversão direta sem tratamento | Conversão protegida e resposta 401 genérica. |
| Produção aceitava configuração insuficiente | Verificação limitada aos valores de desenvolvimento | Falha de startup para segredos vazios/fracos/iguais, Fernet inválida, CORS vazio/coringa e `DEBUG=true`. |
| Ambiente de teste podia tentar rede se houvesse credencial global | Modo simulado dependia apenas do nome do ambiente/credencial | `ENVIRONMENT=test` força eager e `EXTERNAL_SERVICES_ENABLED=false`; regressão proíbe instanciar cliente HTTP. |
| Tentativas de login podiam ser contabilizadas de forma pouco precisa | Bucket atualizado antes de conhecer o resultado | Bucket por IP registra falhas/validações, expira em 15 minutos e responde 429 com `Retry-After`; bloqueio por conta também permanece. |
| SQLite não garantia chaves estrangeiras | `PRAGMA foreign_keys` não era habilitado em cada conexão | Listener SQLAlchemy ativa o pragma; testes verificam órfão recusado e cascade. |
| Credenciais globais poderiam misturar empresas | Serviços dependiam do `.env` para tokens dos canais | Persistência criptografada por integração/empresa e loader `load_company_integration`; rotas operacionais passam a credencial do tenant. |
| Integrações/credenciais duplicadas eram possíveis sob concorrência | Ausência de restrição composta | Migration `003` consolida duplicatas existentes e cria unicidade por empresa/provedor e integração/chave. |
| Teste de integração podia sugerir sucesso sem confirmação oficial | Apenas presença de configuração era verificada | Teste real consulta a API oficial, exige identificador na resposta e só então ativa; modo bloqueado retorna `connected=false` e `simulation=true`. |
| Template local podia ser marcado como aprovado sem a Meta | Status enviado pelo cliente era confiado | Criação local sempre fica `pending`; sincronização oficial atualiza `approved/pending/rejected` por empresa. |
| Campanha WhatsApp podia não usar template oficial correto | Não havia FK/seleção e validação completas | Migration `004`, `message_template_id`, template da mesma empresa, status `approved`, variável `{{1}}` e texto de opt-out. |
| IA podia usar chave global e não limitar gerações por empresa | Credencial/contagem não estavam resolvidas por tenant | Chave descriptografada da empresa, integração ativa no modo real e cotas por minuto/dia por `company_id`. |
| Webhook podia afetar tenant errado, regredir status ou duplicar evento | Busca apenas por telefone/external ID e falta de ordenação de estados | Resolução por `phone_number_id`, escopo pela campanha, ordem monotônica, unicidade/deduplicação e opt-out idempotente. |
| Webhook aceitava corpo grande/JSON inválido sem resposta específica | Leitura e parse sem limites/tratamento | Limite de 2 MB, validação de HMAC e respostas 400/401/413 controladas. |
| Agendamento passado podia persistir campanha/tarefa parcialmente | Commit ocorria antes de todas as validações | Validação anterior ao commit, `flush` transacional e rollback integral. |
| Reenvio/execução concorrente podia duplicar processamento | Estados terminais e claim não eram suficientemente protegidos | Guards 409, tarefa identificada, lock/claim condicional, idempotency key e reconciliação periódica. |
| Falha ao enfileirar podia deixar campanha como `sending` | Estado alterado antes de `delay` sem restauração | Restaura status anterior, marca tarefa como falha e registra erro controlado. |
| Campanhas processadas podiam ser alteradas/apagadas e quebrar histórico | Regras de imutabilidade incompletas | Edição, upload, cancelamento e exclusão são bloqueados nos estados processados; duplicação cria nova versão. |
| Upload confiava apenas no MIME, não tinha cota e deixava mídia anterior | Validação/limpeza incompletas | Magic bytes, limite por arquivo/empresa, pasta do tenant, nome aleatório, rollback do arquivo, limpeza segura e campo oposto zerado. |
| CSV inválido podia produzir resultado parcial e exportação podia gerar fórmula | Tratamento por linha/célula incompleto | Cabeçalhos/tamanho/UTF-8, savepoint por linha e prefixo seguro para células iniciadas por `=`, `+`, `-` ou `@`. |
| Contato bloqueado permanentemente podia ser reativado ou receber novo consentimento | Regra de irreversibilidade ausente | Bloqueio revoga consentimentos, desativa contato e recusa reativação/regrant com 409. |
| Listas, configurações, histórico e administração tinham lacunas funcionais | Interface apresentava controles sem todos os endpoints correspondentes | CRUD de listas, GET/PATCH de configurações, senha, histórico/detalhe e endpoints administrativos implementados. |
| Cliques repetidos inflavam métrica | Cada acesso criava evento aleatório | Fingerprint assinado/hasheado por campanha, dia, origem e user-agent; evento duplicado não é reinserido. |
| Health check podia não refletir falha do banco | Ausência de consulta real | `/health` executa `SELECT 1` e devolve 503 quando o banco está indisponível. |
| Erros inesperados podiam vazar detalhe técnico ou produzir mensagens inconsistentes | Falta de handlers centrais | Handler específico de integração, handler genérico com mensagem segura e detalhes apenas em log. |
| Frontend tinha risco de contratos DOM/botões divergirem e foco não retornar após modal | JS monolítico e modais programáticos sem restauração completa | IDs/nomes alinhados, componentes reutilizáveis, testes de contratos/assets e correção de foco em `navigation.js`. |
| Dependências de teste estavam misturadas ao runtime | Um único requirements para produção/desenvolvimento | Runtime fixado em `requirements.txt`; Pytest, pytest-asyncio e pip-audit em `requirements-dev.txt`. |

## Testes adicionados

| Arquivo novo | Cobertura principal |
|---|---|
| `tests/test_audit_regressions.py` | rede bloqueada em teste, rollback de agendamento, reenvio, simulação social, opt-out tenant/idempotente, uploads e CSV seguro. |
| `tests/test_auth_settings_hardening.py` | takeover por `ADMIN_EMAIL`, cookies/refresh/logout, segredos de produção, perfil, fuso e senha. |
| `tests/test_database_integrity.py` | foreign keys SQLite, órfãos e cascade. |
| `tests/test_integrations_contacts_lists.py` | criptografia/máscara/teste/remoção de integração, tenant, edição/bloqueio de contato e listas. |
| `tests/test_end_to_end_flow.py` | fluxo completo de marketing responsável em modo simulado, sem rede. |
| `tests/test_pages.py` | renderização das páginas, redirecionamentos, permissão admin, contratos DOM e assets. |
| `tests/test_admin_and_history_final.py` | autorização admin, bloqueio, limites, visão global, filtros/paginação/detalhe e isolamento do histórico. |
| `tests/test_tracking_templates_ai_webhooks_final.py` | tracking, templates, campanha WhatsApp real mockada, cotas/chaves de IA e robustez do webhook. |

Testes preexistentes mantidos e ampliados pelo comportamento do código:

- `tests/test_auth.py`
- `tests/test_campaigns.py`
- `tests/test_contacts.py`
- `tests/test_permissions_and_limits.py`
- `tests/test_tracking.py`
- `tests/test_webhooks_and_integrations.py`

`tests/conftest.py` passou a fixar SQLite de teste, `ENVIRONMENT=test`, eager e serviços externos desligados, removendo credenciais herdadas do ambiente antes de importar a aplicação.

## Evidências de execução

| Execução | Resultado observado | Observação |
|---|---|---|
| Hardening de auth/settings + integrações/contatos/listas + integridade SQLite | **26 passed em 20,55 s** | Três arquivos direcionados; nenhuma falha funcional. |
| Fluxo E2E simulado isolado | **1 passed em 2,54 s** | Cadastro, logout/login, empresa, contato, consentimento, lista, IA simulada, aprovação, campanha, agendamento eager, histórico, opt-out e bloqueio de novo envio. |
| Administração/histórico + tracking/templates/IA/webhooks | **19 passed em 21,79 s** | Dois arquivos, serviços externos mockados. |
| Edge/CDP em administração e histórico | **Aprovado** | Tabelas, busca, bloqueio, confirmação, limite, filtros, paginação 25/5, modal e responsividade. Zero exceções JS, erros de console, HTTP 4xx/5xx ou falhas de carregamento. |
| Suíte completa, uma única vez, no estado final | **`[PREENCHER]`** | Não somar baterias parciais como substituto. Executar depois que nenhum agente estiver alterando o código. |
| Startup smoke final | **`[PREENCHER]`** | Deve incluir `/health`, pelo menos uma página pública e uma rota protegida. |
| Build e subida por Docker Compose | **Não executado** | O comando `docker` não está instalado/disponível neste ambiente. |

Avisos conhecidos durante as baterias:

- depreciação do `TestClient/httpx` indicando futura migração para `httpx2`;
- `PytestCacheWarning` por diretórios temporários sem permissão no workspace;
- Edge Tracking Prevention avisou sobre recursos do jsDelivr, sem quebrar a interface;
- `pip-audit` precisou de `PYTHONUTF8=1` no Windows por causa do caminho com caractere acentuado; a auditoria completa das dependências ainda deve ter seu resultado final preenchido.

### Resultado final a preencher

```text
Comando: python -m pytest -q
Data/hora: [PREENCHER]
Python: [PREENCHER]
Banco de teste: [PREENCHER]
Aprovados: [PREENCHER]
Reprovados: [PREENCHER]
Ignorados/xfailed: [PREENCHER]
Duração: [PREENCHER]
Warnings relevantes: [PREENCHER]
```

## Fluxo E2E comprovado

O teste `test_complete_simulated_marketing_flow` executou, sem rede externa:

1. criação de usuário e empresa;
2. logout e novo login;
3. atualização de perfil, empresa, fuso, limite e preferências;
4. criação de contato sem consentimento implícito;
5. registro explícito de consentimento WhatsApp;
6. criação de lista e inclusão do contato;
7. geração de conteúdo marcada como simulação;
8. edição e aprovação humana do conteúdo;
9. criação/edição de campanha em rascunho;
10. agendamento futuro e despacho eager controlado;
11. persistência de campanha, tarefa, destinatário e evento como `simulated`;
12. consulta ao histórico com contagens vindas do banco;
13. revogação do consentimento;
14. tentativa de novo envio bloqueada;
15. confirmação de que nenhum destinatário foi materializado após o opt-out.

O teste substitui `httpx.AsyncClient` por uma classe que falha imediatamente se qualquer acesso externo for tentado.

## Validação do frontend e navegador

Resultado Edge/CDP já obtido:

- administração: overview, tabelas, busca de usuário, bloqueio com confirmação, atualização de limite e responsividade;
- histórico: primeira/segunda página (25/5), busca, filtros combinados, detalhe em modal e responsividade;
- restauração do foco após fechar modal revalidada no botão **Ver**;
- zero erro JavaScript, erro de console, resposta HTTP 4xx/5xx ou recurso ausente nesse roteiro;
- somente avisos de Tracking Prevention do Edge para CDN, sem impacto funcional.

Pendências menores identificadas no frontend:

- a paginação do histórico pode permitir uma página vazia extra quando o total for múltiplo exato de 25;
- contatos aceitam `limit/offset` na API, mas a tabela ainda não oferece controles de paginação e carrega apenas o limite solicitado/padrão;
- a tela administrativa carrega 100 registros por coleção e ainda não expõe paginação completa na UI, embora os endpoints aceitem `limit/offset`;
- a ação visual de autobloqueio do administrador ainda aparece, mas o backend recusa a operação com 409;
- uma passagem final por todas as páginas, após o último merge local, deve preencher o bloco abaixo.

```text
Navegador/versão: [PREENCHER]
Páginas verificadas: [PREENCHER]
Viewports: [PREENCHER]
Erros JavaScript: [PREENCHER]
Erros HTTP/rede: [PREENCHER]
Acessibilidade por teclado/foco: [PREENCHER]
Resultado final: [PREENCHER]
```

## Modo simulado versus modo real

### Simulado

O sistema está em simulação quando:

- `ENVIRONMENT=test`; ou
- `EXTERNAL_SERVICES_ENABLED=false`.

Nesse modo:

- não há chamada real à Meta nem ao provedor de IA;
- a IA devolve texto iniciado por identificação de simulação;
- campanhas persistem status `simulated`, não `sent`;
- integração testada devolve `connected=false` e `simulation=true`;
- sincronização oficial de templates informa que está bloqueada;
- a interface mostra o badge **Modo simulação**.

### Real

Para liberar chamadas reais, é necessário:

1. usar `ENVIRONMENT=development` ou `production`;
2. definir `EXTERNAL_SERVICES_ENABLED=true`;
3. cadastrar na tela **Integrações** os IDs e a credencial da empresa;
4. reiniciar app, worker e beat;
5. executar **Testar conexão** e obter confirmação oficial;
6. no WhatsApp, sincronizar templates e escolher um template `approved` compatível;
7. garantir consentimento, limites, mídia e permissões exigidos pelo canal.

Salvar a credencial não ativa o canal automaticamente. O teste oficial é a transição que marca a integração como ativa.

## Credenciais e dependências externas

Credenciais operacionais são isoladas por empresa e cadastradas na UI:

| Provedor | Dados por empresa | Dependência externa |
|---|---|---|
| WhatsApp | ID do número, ID WABA e access token | WABA, número ativo, permissões, qualidade/limites e templates aprovados. |
| Facebook | ID da Página e page access token | Página administrada, permissões aprovadas e token válido. |
| Instagram | ID da conta profissional e page access token | Conta comercial/criador ligada à Página, permissões e mídia HTTPS pública. |
| IA | API key | Conta/cota do provedor e modelo configurado pela instalação. |

Configuração global que permanece no ambiente:

- `META_APP_ID`;
- `META_APP_SECRET` para assinatura de webhook;
- `META_VERIFY_TOKEN` para o desafio do webhook;
- `META_GRAPH_VERSION`;
- `AI_API_URL`, `AI_MODEL` e limite de saída;
- segredos internos da aplicação, banco, Redis e origens permitidas.

Tokens/IDs tenant globais e `ADMIN_EMAIL` foram removidos do `.env.example`. As classes de serviço ainda preservam fallbacks globais internos por compatibilidade, mas as rotas de produção passam explicitamente a integração da empresa. Remover esses fallbacks numa futura quebra de compatibilidade reduziria ambiguidade.

## Aprovações e configuração Meta

Nenhum teste automático realizou publicação ou disparo real. Para validação real controlada, ainda são necessários:

- aplicativo empresarial no Meta for Developers;
- empresa/ativos configurados no Meta Business Manager;
- verificação empresarial e App Review quando exigidas;
- WABA e número remetente vinculados;
- token com acesso aos ativos corretos;
- Página administrada para Facebook;
- conta Instagram profissional ligada à Página;
- URL pública HTTPS `https://<DOMINIO>/webhooks/meta`;
- o mesmo verify token no painel e na aplicação;
- assinatura com o app secret;
- templates WhatsApp criados no painel, aprovados e sincronizados.

O sistema não aprova templates. Um cadastro local permanece `pending`. No envio real, o template deve estar `approved`, pertencer à mesma empresa, conter ao menos `{{1}}` para o corpo revisado e informar como cancelar o recebimento.

Permissões, nomes de produtos e versões da Graph API mudam fora deste projeto. Devem ser reconfirmados nos painéis/documentação oficial no momento da implantação.

## Revisão de segurança

Controles presentes:

- senhas com bcrypt, nunca em texto puro;
- JWT com expiração, tipo, `jti`, versão revogável e validação de usuário ativo;
- cookies `HttpOnly`, `SameSite=strict` e `Secure` em HTTPS/produção;
- registro público sem caminho de promoção administrativa;
- bearer/cookie aceitos somente depois da validação do usuário e tenant;
- credenciais Fernet, dicas mascaradas e nenhuma devolução do valor completo na listagem;
- escopo `company_id` nas rotas de negócio e testes de IDOR multi-tenant;
- SQLAlchemy com parâmetros, sem concatenação de entrada nas consultas operacionais;
- validação de `HttpUrl`, telefone, e-mail, fuso IANA, tamanho e enumerações;
- origem verificada em métodos mutáveis, CORS explícito e cookies SameSite;
- cabeçalhos CSP, `nosniff`, `DENY`, Referrer/Permissions Policy, no-store em API e HSTS em produção;
- assinatura HMAC e limite de corpo no webhook;
- upload por assinatura de arquivo, tamanho, cota, pasta do tenant e nome aleatório;
- mensagens 500 genéricas e logs sem inclusão intencional de senha/token;
- logs de auditoria para autenticação, configuração, campanhas, consentimento, integrações e administração;
- fail-fast de produção para segredos/CORS/debug inseguros.

Riscos de segurança/operação ainda honestamente presentes:

- rate limiting por IP está em memória e não é compartilhado entre processos/instâncias; usar proxy/API gateway ou Redis;
- `/uploads` é servido publicamente, sem antivírus e sem storage de objetos; não armazenar conteúdo confidencial;
- CSP ainda permite CDN e `unsafe-inline` para estilos; endurecimento adicional exige remover dependências inline/externas;
- tokens também fazem parte da resposta JSON de autenticação para compatibilidade com clientes bearer, embora o frontend use cookies e não os grave em storage;
- rotação de `ENCRYPTION_KEY` ainda não tem ferramenta própria; perder/trocar a chave invalida credenciais persistidas;
- OAuth completo e renovação automática dos tokens Meta não estão implementados;
- recuperação de senha por e-mail não está configurada;
- um scan `pip-audit` final e testes contra a infraestrutura de produção ainda precisam ser registrados;
- diretórios temporários de pytest com permissão negada e eventual `test_divulgai.db-journal` foram observados durante execuções; confirmar limpeza antes de commit/build e impedir artefatos de banco no contexto.

## Banco de dados e migrations

Cadeia atual:

| Revision | Finalidade |
|---|---|
| `001_initial` | Esquema inicial. |
| `002_token_version` | Versão revogável das sessões JWT. |
| `003_integration_unique` | Consolida duplicatas e aplica unicidade de integração/credencial. |
| `004_campaign_template` | Relaciona campanha ao template WhatsApp oficial. |

Pontos revisados:

- foreign keys e cascatas nos models;
- unicidade de telefone por empresa, e-mail, destinatário por campanha, idempotency key e evento externo/tipo;
- unicidade de integração por empresa/provedor e credencial por chave;
- migrations `002` e `004` verificam existência antes de alterar;
- migration `003` preserva a configuração mais recente e move credenciais não conflitantes antes de remover duplicatas;
- SQLite ativa `PRAGMA foreign_keys=ON` em toda conexão;
- a aplicação só usa `create_all` em `development/test`; produção depende de Alembic.

Validações finais a registrar:

```text
SQLite limpo -> upgrade head: [PREENCHER]
SQLite existente 001 -> upgrade head: [PREENCHER]
PostgreSQL 16 limpo -> upgrade head: [PREENCHER OU NÃO DISPONÍVEL]
PostgreSQL existente/cópia sanitizada -> upgrade head: [PREENCHER OU NÃO DISPONÍVEL]
alembic current: [PREENCHER]
alembic heads: [PREENCHER]
```

Não usar o banco real do usuário para smoke de migration. Trabalhar com banco novo ou backup/cópia sanitizada.

## Dependências, Docker e inicialização

- Runtime está fixado em `requirements.txt`.
- Ferramentas de teste/auditoria estão em `requirements-dev.txt`, que inclui o runtime.
- JWT migrou para PyJWT; FastAPI/Starlette, Jinja, multipart, cryptography e psycopg foram fixados/atualizados.
- Dockerfile instala como root apenas durante build, cria usuário de sistema e executa a aplicação sem root.
- Docker Compose define app, PostgreSQL, Redis, worker, beat e volumes persistentes.
- O serviço app aplica `alembic upgrade head` antes do Uvicorn.
- `.dockerignore` exclui `.env`, bancos, caches e uploads locais, preserva `.env.example` e **não exclui este relatório**.

### Limitação do ambiente Docker

A tentativa de validar `docker compose --env-file .env.example config --quiet` não pôde ser executada porque a CLI `docker` não está instalada/disponível no host (`CommandNotFoundException`). Portanto:

- o YAML e os comandos foram revisados estaticamente;
- o build da imagem não foi comprovado;
- health checks/ordem dos serviços não foram comprovados em runtime;
- persistência dos volumes não foi comprovada em runtime;
- worker/beat/Redis/PostgreSQL em Compose não foram executados.

Preencher após validar em uma máquina com Docker:

```text
docker compose config: [PREENCHER]
docker compose build: [PREENCHER]
docker compose up/health: [PREENCHER]
app logs: [PREENCHER]
worker logs: [PREENCHER]
beat logs: [PREENCHER]
persistência após down/up: [PREENCHER]
```

## Arquivos novos

Infraestrutura/documentação:

- `.dockerignore`
- `requirements-dev.txt`
- `AUDITORIA_E_TESTES.md`

Migrations/backend:

- `alembic/versions/002_user_token_version.py`
- `alembic/versions/003_integration_uniqueness.py`
- `alembic/versions/004_campaign_template.py`
- `app/services/integration_credentials.py`

Frontend:

- `app/static/css/animations.css`
- `app/static/css/base.css`
- `app/static/css/components.css`
- `app/static/css/dashboard.css`
- `app/static/css/forms.css`
- `app/static/css/layout.css`
- `app/static/css/pages.css`
- `app/static/css/responsive.css`
- `app/static/css/tables.css`
- `app/static/css/variables.css`
- `app/static/images/favicon.svg`
- `app/static/js/animations.js`
- `app/static/js/init.js`
- `app/static/js/navigation.js`
- `app/templates/components/confirm_modal.html`
- `app/templates/components/sidebar.html`
- `app/templates/components/toast.html`
- `app/templates/components/topbar.html`

Testes:

- `tests/test_admin_and_history_final.py`
- `tests/test_audit_regressions.py`
- `tests/test_auth_settings_hardening.py`
- `tests/test_database_integrity.py`
- `tests/test_end_to_end_flow.py`
- `tests/test_integrations_contacts_lists.py`
- `tests/test_pages.py`
- `tests/test_tracking_templates_ai_webhooks_final.py`

## Arquivos alterados

Configuração/infraestrutura:

- `.env.example`, `README.md`, `Dockerfile`, `requirements.txt`, `pyproject.toml`, `tests/conftest.py`.

Backend:

- `app/config.py`, `app/database.py`, `app/main.py`;
- `app/models/entities.py`, `app/schemas/api.py`, `app/security/auth.py`;
- todas as rotas em `app/routes/` relevantes ao produto;
- serviços de IA, campanhas, consentimento, Facebook, Instagram, rate limit e WhatsApp;
- `app/tasks/celery_app.py` e `app/tasks/campaign_tasks.py`.

Frontend:

- `app/static/js/app.js`, `app/static/css/lists.css`;
- templates `admin`, `base`, `campaigns`, `contacts`, `content`, `dashboard`, `history`, `integrations`, `landing`, `login`, `privacy`, `register`, `settings` e `terms`.

Removido/substituído:

- `app/static/css/app.css`, substituído pelos módulos CSS listados acima.

## Limitações e riscos restantes

1. **Suíte final ainda precisa ser registrada.** Baterias parciais passaram, mas o critério de conclusão exige uma execução única após a última alteração.
2. **Serviços externos não foram exercitados com contas reais.** A lógica foi mockada; tokens expirados, revisão do app, limites e particularidades dos ativos só podem ser confirmados num sandbox/conta autorizada.
3. **Docker, PostgreSQL e Redis não foram executados neste host.** A ausência da CLI Docker impede afirmar que a pilha sobe integralmente.
4. **Migrations precisam do smoke final em bancos descartáveis.** Em especial, validar upgrade de instalação existente e PostgreSQL.
5. **Recuperação de senha é informativa, não transacional.** Falta provedor de e-mail e fluxo de token de recuperação.
6. **OAuth/renovação Meta não existem.** A operação depende da gestão manual dos tokens por empresa.
7. **Uploads locais são públicos e não passam por antivírus.** Produção deve usar object storage/CDN, retenção e scanning.
8. **Rate limiting não é distribuído.** Múltiplas instâncias exigem controle no proxy/gateway ou Redis.
9. **Pequenas lacunas de UX permanecem.** Página vazia extra no limite da paginação do histórico, paginação de contatos/admin não exposta e botão de autobloqueio visível.
10. **Dependências CDN podem gerar avisos de privacidade/rede.** Considerar self-host de Bootstrap Icons/Chart.js para ambientes restritos.
11. **Auditoria de dependências precisa de resultado final.** Executar `pip-audit` com rede e cache funcionais.
12. **Artefatos temporários devem ser limpos antes da entrega.** Não versionar banco/journal/cache de teste.

## Comandos para executar o projeto

### Windows PowerShell, modo local simulado

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env

$env:DATABASE_URL = "sqlite:///./divulgai.db"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:ENVIRONMENT = "development"
$env:DEBUG = "false"
$env:EXTERNAL_SERVICES_ENABLED = "false"
$env:CELERY_TASK_ALWAYS_EAGER = "true"

python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Os três segredos devem ser gerados e preenchidos no `.env`; não use placeholders em produção:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Linux/macOS, modo local simulado

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env

export DATABASE_URL='sqlite:///./divulgai.db'
export REDIS_URL='redis://localhost:6379/0'
export ENVIRONMENT='development'
export DEBUG='false'
export EXTERNAL_SERVICES_ENABLED='false'
export CELERY_TASK_ALWAYS_EAGER='true'

python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

### Redis, worker e beat locais

Redis por Docker, quando a CLI estiver disponível:

```text
docker run --name divulgai-redis --publish 6379:6379 --detach redis:7-alpine
```

Windows:

```powershell
$env:CELERY_TASK_ALWAYS_EAGER = "false"
python -m celery -A app.tasks.celery_app:celery_app worker --loglevel=info --pool=solo
python -m celery -A app.tasks.celery_app:celery_app beat --loglevel=info
```

Linux/macOS:

```bash
export CELERY_TASK_ALWAYS_EAGER='false'
python -m celery -A app.tasks.celery_app:celery_app worker --loglevel=info
python -m celery -A app.tasks.celery_app:celery_app beat --loglevel=info
```

### Docker Compose

```text
docker compose --env-file .env config
docker compose up --build --detach
docker compose logs --follow app worker beat
docker compose down
```

Esses comandos estão documentados, mas não foram executados neste host por ausência da CLI Docker.

### Administrador por CLI

O cadastro público nunca cria administrador. Depois das migrations, usando o mesmo banco da aplicação:

```text
python -m app.utils.create_admin admin@exemplo.invalid --name "Administrador" --company "Empresa Exemplo"
```

O comando promove um usuário existente ou pede uma senha interativamente para criar um novo. Nunca coloque a senha na linha de comando ou neste relatório.

## Comandos para migrations e testes

```powershell
python -m pip install -r requirements-dev.txt
python -m alembic heads
python -m alembic current
python -m alembic upgrade head
python -m pytest -q
```

Teste E2E isolado:

```powershell
python -m pytest -q tests\test_end_to_end_flow.py
```

Auditoria de dependências no Windows com caminho acentuado:

```powershell
$env:PYTHONUTF8 = "1"
python -m pip_audit -r requirements.txt
```

Smoke de startup a registrar:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Invoke-RestMethod http://127.0.0.1:8000/health
```

Resultado:

```text
Processo iniciou sem traceback: [PREENCHER]
GET /health HTTP: [PREENCHER]
database: [PREENCHER]
environment: [PREENCHER]
simulation_mode: [PREENCHER]
Processo foi encerrado: [PREENCHER]
```

## Roteiro de verificação manual final

1. Abrir `/`, testar menu, CTAs, login, cadastro, privacidade e termos.
2. Cadastrar usuário comum e confirmar que `/administracao` redireciona/recusa.
3. Sair, entrar novamente, forçar refresh e confirmar logout/revogação.
4. Atualizar perfil, empresa, e-mail, fuso, preferências e senha.
5. Criar dois contatos, editar, pesquisar, etiquetar, exportar e testar duplicidade.
6. Importar CSV válido/inválido e conferir mensagens/rollback.
7. Registrar e revogar consentimento; confirmar bloqueio permanente.
8. Criar/editar lista e alterar membros.
9. Gerar, editar e aprovar conteúdo em modo simulado.
10. Criar, editar, duplicar, pré-visualizar e agendar campanha.
11. Executar tarefa em modo eager, consultar histórico/detalhe e tentar reenvio.
12. Testar upload válido, tipo falso, limite e substituição de mídia.
13. Cadastrar integração de teste e confirmar que nenhum token reaparece na UI.
14. Com conta sandbox autorizada, habilitar serviços externos, testar conexão e sincronizar templates sem enviar para destinatário real não autorizado.
15. Criar admin por CLI e testar busca, bloqueio, limite, campanhas, logs e erros.
16. Repetir em viewport mobile e somente com teclado; conferir foco, modais e menu.
17. Manter Console e Network abertos e registrar qualquer JS, 404, 422 inesperado ou 500.
18. Verificar app, worker e beat nos logs; confirmar que nenhuma credencial completa foi registrada.

## Critério de encerramento

Antes de declarar a auditoria concluída, preencher e confirmar:

- [ ] Suíte completa: `[TOTAL FINAL]` aprovados e zero falha inesperada.
- [ ] E2E completo aprovado no estado final.
- [ ] Startup smoke aprovado e processo encerrado corretamente.
- [ ] `alembic upgrade head` aprovado em banco descartável limpo.
- [ ] Upgrade de uma instalação existente validado em cópia/backup.
- [ ] Páginas principais sem erro JS/HTTP no browser final.
- [ ] Nenhum segredo ou banco/journal de teste no diff final.
- [ ] Docker validado em outro host ou explicitamente aceito como não validado.
- [ ] Dependências auditadas e achados avaliados.
- [ ] Recursos reais continuam desabilitados até credenciais e aprovações oficiais.

Resultado global final: **`[PREENCHER: APROVADO / APROVADO COM RESSALVAS / REPROVADO]`**.
