# Divulgaí IA

Plataforma FastAPI para criar, organizar, agendar e acompanhar campanhas responsáveis no WhatsApp, Facebook e Instagram. O projeto usa somente APIs oficiais, exige consentimento válido por canal e mantém geração de conteúdo por IA sob aprovação humana.

> Estado do projeto: MVP funcional. Sem credenciais, as integrações ficam desativadas e respostas de desenvolvimento são identificadas como **SIMULAÇÃO**; nenhuma publicação ou mensagem externa é fingida como sucesso.

## Recursos implementados

- Landing page, cadastro, login JWT com cookie HttpOnly, refresh token, logout e bloqueio após tentativas excessivas.
- Empresas, perfis de usuário e autorização administrativa.
- CRUD, busca, CSV, listas, etiquetas, exportação LGPD, bloqueio e consentimento por canal.
- Campanhas em WhatsApp, Facebook e Instagram; rascunho, duplicação, revisão, envio e cancelamento.
- Agendamento com Celery/Redis, tarefas rastreáveis, tentativas, resultado e erro.
- WhatsApp Business Cloud API com template aprovado, idempotência, eventos e opt-out por webhook.
- Facebook Pages e Instagram Professional pela Graph API; nenhum perfil pessoal.
- Conteúdo com IA em camada separada, resultado editável e aprovação humana obrigatória.
- Credenciais criptografadas, tokens mascarados, auditoria, CORS restrito e cabeçalhos de segurança.
- Limite diário, pausa por erros, bloqueio sem consentimento e confirmação de campanhas grandes.
- Dashboard, histórico, integrações, configurações, política de privacidade e termos.
- Links assinados para campanhas do Facebook e contagem de cliques no dashboard.
- PostgreSQL, Alembic, Redis, Docker Compose e testes Pytest com integrações simuladas.

## Requisitos

- Python 3.12
- PostgreSQL 16 e Redis 7, ou Docker Desktop
- Uma conta Meta Business e ativos aprovados para envios reais

## Instalação no Windows PowerShell

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Gere segredos antes de editar o `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use os dois primeiros valores em `SECRET_KEY` e `JWT_SECRET_KEY`; use a chave Fernet em `ENCRYPTION_KEY`.

Para desenvolvimento sem PostgreSQL, altere temporariamente:

```dotenv
DATABASE_URL=sqlite:///./divulgai.db
REDIS_URL=redis://localhost:6379/0
ENVIRONMENT=development
```

## Banco, aplicação e filas

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

Em outros terminais, com Redis ativo:

```powershell
celery -A app.tasks.celery_app:celery_app worker --loglevel=info --pool=solo
celery -A app.tasks.celery_app:celery_app beat --loglevel=info
```

Para iniciar apenas o Redis via Docker durante o desenvolvimento:

```powershell
docker run --name divulgai-redis -p 6379:6379 -d redis:7-alpine
```

Acesse `http://localhost:8000`. A documentação da API fica em `http://localhost:8000/api/docs`.

## Docker

Copie e configure o ambiente, mantendo a URL PostgreSQL do exemplo:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Parar os serviços sem excluir os volumes:

```powershell
docker compose down
```

## Variáveis de ambiente

| Variável | Finalidade |
|---|---|
| `DATABASE_URL` | URL SQLAlchemy do PostgreSQL |
| `REDIS_URL` | broker/backend do Celery |
| `SECRET_KEY` | segredo geral e fallback de criptografia em desenvolvimento |
| `JWT_SECRET_KEY` | assinatura dos JWTs |
| `ENCRYPTION_KEY` | chave Fernet para credenciais persistidas |
| `META_APP_ID`, `META_APP_SECRET` | aplicativo Meta e validação de assinatura |
| `META_GRAPH_VERSION` | versão da Graph API, atualizável sem alteração de código |
| `META_VERIFY_TOKEN` | desafio de verificação do webhook |
| `WHATSAPP_PHONE_NUMBER_ID` | número remetente da Cloud API |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | conta WhatsApp Business |
| `WHATSAPP_ACCESS_TOKEN` | token oficial da Cloud API |
| `FACEBOOK_PAGE_ID` | página administrada; perfis pessoais não são aceitos |
| `FACEBOOK_PAGE_ACCESS_TOKEN` | token de Página com permissões aprovadas |
| `INSTAGRAM_ACCOUNT_ID` | conta profissional ligada à Página |
| `AI_API_KEY`, `AI_API_URL`, `AI_MODEL` | provedor oficial de IA |
| `BASE_URL` | URL pública HTTPS da aplicação |
| `ENVIRONMENT`, `DEBUG` | ambiente e depuração (mantenha `DEBUG=false` em produção) |
| `ADMIN_EMAIL` | e-mail que receberá papel administrativo no cadastro inicial |
| `MINUTE_MESSAGE_LIMIT`, `HOURLY_MESSAGE_LIMIT`, `DAILY_MESSAGE_LIMIT` | limites anti-spam internos |

Nunca versione `.env`. Em produção, prefira um gerenciador de segredos.

## Configurar as APIs oficiais da Meta

1. Crie/verifique a empresa no Meta Business Manager e crie um app empresarial no portal Meta for Developers.
2. Adicione WhatsApp, associe a conta WABA e o número, obtenha token de sistema e cadastre templates. Somente templates com estado `approved` no banco podem ser enviados.
3. Para Facebook, autorize uma Página administrada pelo usuário e conceda as permissões de publicação aprovadas na revisão do app.
4. Para Instagram, vincule uma conta comercial/de criador à Página, habilite Instagram Graph API e conceda as permissões aprovadas.
5. Configure a URL pública `https://SEU_DOMINIO/webhooks/meta`, informe o mesmo `META_VERIFY_TOKEN` e assine eventos de mensagens.
6. Preencha as variáveis e reinicie aplicação, worker e beat. Use “Testar conexão” antes de liberar campanhas.

Os nomes/permissões disponíveis e versões da Graph API podem mudar. Confirme-os na documentação oficial e no painel da Meta no momento da implantação. Aprovação do app, verificação empresarial, qualidade do número, templates e limites são externos ao sistema.

Para criar ou promover um administrador por linha de comando:

```powershell
python -m app.utils.create_admin admin@suaempresa.com
```

## CSV de contatos

Codificação UTF-8, até 2 MB:

```csv
nome,telefone,email,consentimento,canal,origem
Maria,+5511999999999,maria@example.com,sim,whatsapp,formulario_site
Joao,+5511888888888,,nao,whatsapp,evento
```

Uma linha sem `consentimento=sim` é importada sem autorização e não poderá receber mensagens. Guarde prova adequada da manifestação do titular; uma coluna em arquivo não substitui essa responsabilidade.

## Testes

```powershell
pytest -q
```

Os testes usam SQLite isolado e não fazem chamadas à Meta nem ao provedor de IA. Cobrem cadastro, login, bloqueio, permissões, contatos, CSV, consentimento, campanha, agendamento, bloqueio sem consentimento, webhook e simulação externa.

## Estrutura

```text
app/
  models/ schemas/ routes/ services/ repositories/ tasks/ security/
  templates/ static/css/ static/js/
alembic/versions/     migrations
tests/                testes automatizados
uploads/              mídia local (não versionada)
Dockerfile            imagem da aplicação
docker-compose.yml    app, PostgreSQL, Redis, worker e beat
```

## Segurança e operação

- Use HTTPS e cookies `Secure` em produção; mantenha origens CORS explícitas.
- Aplique rate limiting também no proxy/API gateway para múltiplas instâncias. O bloqueio de login e os limites de negócio já existem na aplicação.
- Faça backup criptografado, rotação de tokens e revisão periódica dos logs.
- Hospede mídia do Instagram em URL HTTPS pública compatível; caminho local não é publicável pela Graph API.
- Personalize termos, privacidade, retenção e canal de atendimento com assessoria jurídica antes de produção.

## Próximas evoluções

- Fluxo OAuth completo da Meta e renovação automática de tokens.
- Confirmação de e-mail e recuperação de senha com provedor transacional.
- Segmentos dinâmicos avançados, analytics de links com domínio próprio e relatórios exportáveis.
- Armazenamento S3 compatível e antivírus para mídia.
- Rate limiting distribuído por Redis e painel de administração visual completo.
