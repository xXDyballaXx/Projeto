# Divulgaí IA

Plataforma FastAPI para criar, organizar, agendar e acompanhar campanhas responsáveis no WhatsApp, Facebook e Instagram. O projeto usa APIs oficiais, exige consentimento válido por canal e mantém a geração de conteúdo por IA sob revisão e aprovação humana.

O MVP é funcional e seguro por padrão: chamadas externas começam desativadas. Nesse estado, o sistema identifica resultados como **SIMULAÇÃO** e não apresenta mensagens ou publicações fictícias como entregues.

## Recursos implementados

- Cadastro e login com JWT, cookies HttpOnly, rotação de refresh token, logout e revogação de sessão.
- Empresas isoladas, perfil, configurações e administração global protegida por papel.
- Contatos, busca, etiquetas, listas, importação/exportação CSV, exportação LGPD, consentimento, opt-out e bloqueio permanente.
- Campanhas para WhatsApp, Facebook Pages e Instagram profissional, com rascunho, revisão, agendamento, envio, cancelamento e histórico.
- Celery e Redis para filas, agendamentos, tentativas e reconciliação de tarefas.
- WhatsApp Business Cloud API com idempotência, templates oficiais, sincronização de status, eventos de entrega e opt-out por webhook.
- Facebook Pages e Instagram Graph API; perfis pessoais não são suportados.
- Conteúdo assistido por IA, editável e dependente de aprovação humana.
- Credenciais criptografadas por empresa, valores mascarados na interface, auditoria e limites de uso.
- Upload validado de imagens e vídeos, cota por empresa e volume persistente no Docker.
- PostgreSQL, SQLite para desenvolvimento/testes, Alembic, Docker Compose e Pytest.

## Requisitos

- Python 3.12.
- PostgreSQL 16 para implantação. SQLite pode ser usado no desenvolvimento local e nos testes.
- Redis 7 quando o Celery não estiver em modo eager.
- Docker Desktop, opcional, para executar a pilha completa.
- Para operações reais: ativos e credenciais oficiais do provedor de IA e/ou uma conta Meta Business com as aprovações correspondentes.

## Instalação no Windows com PowerShell

Crie o ambiente virtual e instale as dependências da aplicação:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Se a política do PowerShell bloquear a ativação, libere-a somente no terminal atual e tente novamente:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

Gere dois segredos distintos e uma chave Fernet. Execute o primeiro comando duas vezes e coloque os resultados, respectivamente, em `SECRET_KEY` e `JWT_SECRET_KEY`; coloque o terceiro em `ENCRYPTION_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

O `.env.example` usa os nomes de host internos do Docker (`db` e `redis`). Para iniciar localmente com SQLite e tarefas executadas no mesmo processo, defina os overrides no terminal:

```powershell
$env:DATABASE_URL = "sqlite:///./divulgai.db"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:ENVIRONMENT = "development"
$env:DEBUG = "false"
$env:EXTERNAL_SERVICES_ENABLED = "false"
$env:CELERY_TASK_ALWAYS_EAGER = "true"
```

No PowerShell, `DATABASE_URL=sqlite:///./divulgai.db` sozinho é interpretado como um comando e produz `CommandNotFoundException`. Use `$env:DATABASE_URL = "..."` como acima. Dentro do arquivo `.env`, por outro lado, a sintaxe correta continua sendo `DATABASE_URL=...`, sem `$env:`.

Aplique todas as migrations e inicie o servidor:

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

A aplicação fica em `http://localhost:8000`, a documentação da API em `http://localhost:8000/api/docs` e o health check em `http://localhost:8000/health`.

## Instalação no Linux ou macOS

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Gere os segredos com os mesmos três comandos Python mostrados na seção anterior. Para uma execução local simples:

```bash
export DATABASE_URL='sqlite:///./divulgai.db'
export REDIS_URL='redis://localhost:6379/0'
export ENVIRONMENT='development'
export DEBUG='false'
export EXTERNAL_SERVICES_ENABLED='false'
export CELERY_TASK_ALWAYS_EAGER='true'

python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Variáveis definidas com `$env:` ou `export` valem somente para o terminal atual e têm precedência sobre o `.env`.

## Banco de dados e migrations

Alembic é a fonte de verdade do esquema. Execute o comando abaixo em uma instalação nova e sempre depois de atualizar o código:

```text
python -m alembic upgrade head
```

Em `development` e `test`, a aplicação também cria tabelas ausentes para facilitar o trabalho local. Isso não substitui migrations e não atualiza com segurança uma estrutura antiga. Em produção, aplique a migration antes de iniciar a nova versão.

Para inspecionar o estado:

```text
python -m alembic current
python -m alembic heads
```

## Redis e Celery

Com `CELERY_TASK_ALWAYS_EAGER=true`, tarefas disparadas pela aplicação rodam de forma síncrona. Esse modo é útil para desenvolvimento e testes, mas não substitui Redis, worker e beat para agendamento real e operação resiliente.

Para iniciar apenas o Redis local via Docker:

```powershell
docker run --name divulgai-redis --publish 6379:6379 --detach redis:7-alpine
```

Se o contêiner já existir e estiver parado, use `docker start divulgai-redis`. Depois defina `CELERY_TASK_ALWAYS_EAGER=false` e abra dois terminais com o mesmo ambiente da aplicação.

No Windows:

```powershell
python -m celery -A app.tasks.celery_app:celery_app worker --loglevel=info --pool=solo
python -m celery -A app.tasks.celery_app:celery_app beat --loglevel=info
```

No Linux ou macOS:

```bash
python -m celery -A app.tasks.celery_app:celery_app worker --loglevel=info
python -m celery -A app.tasks.celery_app:celery_app beat --loglevel=info
```

O worker executa campanhas e o beat localiza tarefas vencidas e reconcilia execuções interrompidas. Mantenha ambos ativos quando houver agendamento.

## Docker Compose

Copie o exemplo, gere os três segredos e mantenha no `.env` as URLs com os hosts `db` e `redis`:

```powershell
Copy-Item .env.example .env
docker compose up --build --detach
docker compose logs --follow app worker beat
```

Os valores `POSTGRES_USER=divulgai` e `POSTGRES_PASSWORD=divulgai` do exemplo existem apenas para desenvolvimento local. Antes de uma implantação, escolha credenciais fortes, atualize também o usuário/senha dentro de `DATABASE_URL` (com codificação URL quando necessário) e use `ENVIRONMENT=production`, `BASE_URL=https://...` e origens CORS HTTPS. A aplicação recusa produção com SQLite, HTTP ou a senha PostgreSQL padrão.

O serviço `app` aguarda o banco, aplica `alembic upgrade head` e inicia o Uvicorn. O Compose também inicia PostgreSQL, Redis, worker e beat. Os dados ficam nos volumes `postgres_data`, `redis_data` e `uploads`.

Para parar sem excluir volumes:

```text
docker compose down
```

Não use `docker compose down --volumes` sem a intenção explícita de apagar banco, Redis e uploads persistidos.

## Modo simulado e modo real

O modo é determinado por duas configurações:

| Configuração | Comportamento |
|---|---|
| `EXTERNAL_SERVICES_ENABLED=false` | Bloqueia chamadas à Meta e ao provedor de IA e marca os resultados como simulação. |
| `ENVIRONMENT=test` | Força integrações externas desativadas e tarefas eager, independentemente dos demais valores. |
| `EXTERNAL_SERVICES_ENABLED=true` fora de `test` | Permite chamadas reais, mas somente com a integração da empresa salva, testada e ativa. |

Salvar uma credencial não habilita envios por si só. Para operação real:

1. Configure os segredos globais e o ambiente.
2. Cadastre os identificadores e tokens da empresa em **Integrações**.
3. Altere `EXTERNAL_SERVICES_ENABLED=true` e reinicie app, worker e beat para liberar os testes oficiais.
4. Use **Testar conexão**, corrija qualquer permissão recusada e, no WhatsApp, sincronize os templates.

Essa variável é uma chave geral de segurança. Voltar para `false` interrompe novas chamadas externas sem apagar as credenciais armazenadas.

## Credenciais por empresa

Tokens de canais e chaves de IA não pertencem ao `.env`. Um usuário autenticado cadastra-os na página `/integracoes`, e o backend os associa ao `company_id`, criptografa com Fernet e devolve apenas uma dica mascarada. Uma empresa não consegue listar, testar, usar nem excluir a integração de outra.

Campos esperados na interface:

- WhatsApp: ID do número remetente, ID da conta WhatsApp Business (WABA) e access token.
- Facebook: ID da Página e page access token.
- Instagram: ID da conta profissional e page access token associado.
- IA: API key da empresa.

`META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN` e `META_GRAPH_VERSION` continuam globais porque identificam o aplicativo e protegem o webhook. `AI_API_URL`, `AI_MODEL` e `AI_MAX_OUTPUT_TOKENS` definem o provedor/modelo oferecido pela instalação; apenas a API key é isolada por empresa.

Não troque `ENCRYPTION_KEY` sem um plano de rotação: a chave é necessária para descriptografar todas as credenciais persistidas.

## Requisitos da Meta, WABA e templates

O sistema não contorna as regras da Meta e não concede aprovações. Antes de habilitar chamadas reais:

1. Crie um aplicativo empresarial no Meta for Developers e configure a empresa no Meta Business Manager.
2. Conclua a verificação empresarial e a revisão do aplicativo quando exigidas para os recursos e permissões usados.
3. No WhatsApp, associe uma WABA e um número remetente, mantenha a qualidade/limites da conta e emita um token com acesso aos ativos corretos.
4. Crie os templates no painel oficial da Meta, aguarde o estado `approved` e sincronize-os pela tela de Integrações. Um template criado apenas localmente permanece `pending`.
5. Para Facebook, use uma Página administrada e um token de Página com as permissões aprovadas. Perfis pessoais não são aceitos.
6. Para Instagram, vincule uma conta comercial ou de criador a uma Página e habilite a Instagram Graph API.
7. Publique `https://SEU_DOMINIO/webhooks/meta`, configure o mesmo `META_VERIFY_TOKEN` no painel e mantenha `META_APP_SECRET` para validar `X-Hub-Signature-256`.

No envio real por WhatsApp, a campanha exige lista com consentimento válido, integração ativa e template sincronizado como `approved`. A validação atual também exige a variável `{{1}}` no corpo e uma instrução clara de cancelamento. O status oficial pode mudar no painel; sincronize novamente antes de investigar uma recusa.

Permissões, nomes de produtos, versões da Graph API e requisitos de revisão podem mudar. Confirme-os na documentação e nos painéis oficiais no momento da implantação.

## Criar ou promover um administrador

O cadastro público sempre cria um usuário comum. `ADMIN_EMAIL` não promove contas e não deve ser configurado. Isso evita que alguém obtenha privilégios administrativos apenas registrando um endereço previsto no ambiente.

Depois de aplicar as migrations, execute o comando usando o mesmo `DATABASE_URL` da aplicação:

```powershell
python -m app.utils.create_admin admin@suaempresa.com --name "Administrador" --company "Sua Empresa"
```

Se o e-mail já existir, o usuário será promovido. Se não existir, o comando solicitará uma senha com pelo menos oito caracteres, letras e números e criará a empresa informada. No Docker:

```text
docker compose exec app python -m app.utils.create_admin admin@suaempresa.com --name "Administrador" --company "Sua Empresa"
```

O papel administrativo possui visão global de empresas, usuários, campanhas, logs e erros de integração. Restrinja o acesso ao host/contêiner e audite toda promoção.

## Variáveis de ambiente

| Variável | Finalidade |
|---|---|
| `DATABASE_URL` | URL SQLAlchemy do PostgreSQL ou SQLite. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Inicialização do PostgreSQL no Compose; devem corresponder a `DATABASE_URL`. |
| `REDIS_URL` | Broker e backend de resultados do Celery. |
| `CELERY_TASK_ALWAYS_EAGER` | Executa tarefas no processo web; use apenas em desenvolvimento/testes. |
| `ENVIRONMENT` | `development`, `test` ou `production`. |
| `DEBUG` | Depuração; deve permanecer `false` em produção. |
| `EXTERNAL_SERVICES_ENABLED` | Chave geral para chamadas externas reais. |
| `SECRET_KEY` | Segredo geral; em produção deve ter pelo menos 32 caracteres. |
| `JWT_SECRET_KEY` | Assinatura dos JWTs; deve ser forte e diferente de `SECRET_KEY`. |
| `ENCRYPTION_KEY` | Chave Fernet que protege credenciais por empresa. |
| `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS` | Duração das sessões. |
| `ALLOWED_ORIGINS` | Origens CORS explícitas, separadas por vírgula. `*` é recusado em produção. |
| `BASE_URL` | URL pública usada para links, webhook e mídias; use HTTPS em produção. |
| `META_APP_ID`, `META_APP_SECRET` | Identidade do aplicativo Meta e validação de assinatura. |
| `META_VERIFY_TOKEN` | Segredo do desafio de verificação do webhook. |
| `META_GRAPH_VERSION` | Versão da Graph API usada nas chamadas. |
| `AI_API_URL`, `AI_MODEL`, `AI_MAX_OUTPUT_TOKENS` | Endpoint, modelo e limite de saída do provedor de IA. |
| `MAX_UPLOAD_MB`, `MAX_COMPANY_UPLOAD_MB` | Limite por arquivo e cota total de mídia por empresa. |
| `MINUTE_MESSAGE_LIMIT`, `HOURLY_MESSAGE_LIMIT`, `DAILY_MESSAGE_LIMIT` | Limites internos de mensagens. |
| `LARGE_CAMPAIGN_THRESHOLD` | Quantidade que exige confirmação adicional. |
| `MINUTE_AI_GENERATION_LIMIT`, `DAILY_AI_GENERATION_LIMIT` | Limites de geração assistida por empresa. |

Em `production`, a inicialização é recusada se os segredos estiverem ausentes/fracos ou iguais, se `ENCRYPTION_KEY` não for uma chave Fernet, se CORS estiver vazio/coringa ou se `DEBUG=true`.

## Testes e auditoria de dependências

As ferramentas de desenvolvimento ficam em `requirements-dev.txt`, que já inclui `requirements.txt`:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

No Linux e macOS, os comandos são os mesmos com o ambiente virtual ativado. Os testes usam um banco SQLite isolado, forçam tarefas eager e bloqueiam serviços externos. Nenhum teste deve depender de Redis, Meta ou do provedor de IA real.

Para auditar as dependências instaladas:

```text
python -m pip_audit -r requirements.txt
```

Se o Windows apresentar `UnicodeDecodeError` porque o caminho do projeto possui caracteres acentuados, ative o modo UTF-8 no terminal antes da auditoria:

```powershell
$env:PYTHONUTF8 = "1"
python -m pip_audit -r requirements.txt
```

## Contatos e CSV

O CSV deve estar em UTF-8, ter até 2 MB e conter os cabeçalhos abaixo:

```csv
nome,telefone,email,consentimento,canal,origem
Maria,+5511999999999,maria@example.com,sim,whatsapp,formulario_site
Joao,+5511888888888,,nao,whatsapp,evento
```

Uma linha sem `consentimento=sim` é importada sem autorização e não poderá receber mensagens. Guarde a prova da manifestação do titular; uma coluna no arquivo não substitui essa responsabilidade.

## Segurança e uploads

- Nunca versione `.env`, tokens ou chaves. Em produção, use um gerenciador de segredos e planeje rotação e revogação.
- Use HTTPS. Cookies tornam-se `Secure` em produção e usam `HttpOnly` e `SameSite=strict`; mantenha `ALLOWED_ORIGINS` restrito aos frontends reais.
- O webhook valida tamanho e assinatura. Não exponha `META_APP_SECRET` nem reutilize `META_VERIFY_TOKEN` como senha de usuário.
- Uploads aceitam somente JPG, PNG, WebP e MP4, validam tipo e assinatura do arquivo, geram nome aleatório e ficam separados por diretório de empresa.
- `MAX_UPLOAD_MB` limita cada arquivo e `MAX_COMPANY_UPLOAD_MB` limita o total da empresa. O volume `uploads` precisa de backup junto com o banco.
- A pasta `/uploads` é servida pela aplicação e `BASE_URL` compõe a URL pública. Não envie material confidencial. Instagram exige imagem/vídeo acessível por HTTPS pela Meta.
- Para produção, considere armazenamento de objetos, antivírus, retenção, CDN/proxy com limites de corpo e políticas de exclusão.
- Aplique rate limiting também no proxy ou API gateway quando houver múltiplas instâncias e monitore `/health`, worker, beat e logs de auditoria.
- Faça backups criptografados e testes de restauração. Sem a `ENCRYPTION_KEY` correta, credenciais recuperadas do banco não poderão ser usadas.
- Revise termos, privacidade, base legal, retenção e canal de atendimento com assessoria adequada antes da operação real.

## Estrutura principal

```text
app/
  models/ schemas/ routes/ services/ repositories/ tasks/ security/
  templates/ static/css/ static/js/
alembic/versions/     migrations
tests/                testes automatizados
uploads/              mídia local, persistida em volume no Docker
Dockerfile            imagem da aplicação
docker-compose.yml    app, PostgreSQL, Redis, worker e beat
```

## Limitações conhecidas

- O fluxo OAuth completo da Meta e a renovação automática de tokens ainda não estão implementados.
- Recuperação de senha por e-mail ainda depende de um provedor transacional.
- Armazenamento de objetos e antivírus para mídia continuam como evoluções recomendadas.
- Rate limiting distribuído deve ser aplicado externamente em implantações com múltiplas instâncias.
