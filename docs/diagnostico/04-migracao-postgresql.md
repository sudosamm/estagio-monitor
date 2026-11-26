# 04 — Plano de migração do SQLite para o PostgreSQL 18

> **Plano, não execução.** O agente escreve o procedimento e as ferramentas (Etapa 1); **você executa** no servidor.
> Nenhum banco real foi aberto nesta etapa.

## Situação atual

- `DATABASES` fixo em SQLite: `DATA_DIR/db.sqlite3`, com WAL, `synchronous=NORMAL`, `busy_timeout=5000` e
  `transaction_mode=IMMEDIATE` (`monitor/settings.py`).
- Um container no Coolify, volume `/data` com o banco, os anexos (`/data/anexos`) e a chave VAPID.
- `entrypoint.sh` roda `migrate` a cada subida, depois o Gunicorn com 3 workers.
- Backup documentado no README: "copiar o volume `/data`". Sem agendamento nem teste de restauração.

## Alvo (do plano de 2027)

- **PostgreSQL 18** em produção, homologação e desenvolvimento local, sempre na mesma versão.
- Produção e homologação: um **recurso de banco do Coolify**, separado da aplicação, sem porta pública, acessado pela
  URL interna da rede do Coolify, com backup agendado.
- Local: um serviço PostgreSQL num `docker-compose.dev.yml`, para que um deploy da aplicação nunca recrie o banco.
- Configuração por `DATABASE_URL`. **Sem a variável, o sistema continua no SQLite em `/data`** (reversão simples).
- Anexos e chave VAPID continuam no volume `/data`.
- O `migrate` automático do `entrypoint.sh` continua.

## O que muda no código (Etapa 1, deploy próprio, sem mudança de modelo)

1. `requirements.txt`: `psycopg[binary]` (3.x) e, se preferir não escrever o parser, `dj-database-url`.
2. `settings.py`: se `DATABASE_URL` existir, usa PostgreSQL com `CONN_MAX_AGE=60` e `CONN_HEALTH_CHECKS=True`; senão,
   o bloco SQLite atual, igual a hoje (as `OPTIONS` do SQLite só valem para ele).
3. Threads em segundo plano (`core/push.py`, `core/acompanhamento.py`, `core/sugestoes.py`, `core/services.py`):
   fechar a conexão do banco no fim da thread (`connection.close()`). Com `CONN_MAX_AGE > 0`, o
   `close_old_connections()` atual não fecha, e cada thread deixaria uma conexão aberta no PostgreSQL até ser coletada.
   O `enviar_emails` hoje nem chama `close_old_connections()` (o *handler* de erro grava no banco se o envio falhar).
4. Dois comandos novos:
   - `verificar_para_postgres` (roda no SQLite, só lê): `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, textos
     maiores que o `max_length` do campo (o SQLite não impede; o PostgreSQL recusa), caracteres NUL, IPs inválidos em
     `GenericIPAddressField`, decimais fora de `max_digits`, datas inválidas. Sai com um relatório e um JSON de
     contagens por tabela, **sem imprimir dados pessoais** (só tabela, campo, id e o tipo do problema).
   - `comparar_bancos --origem sqlite:///… --destino $DATABASE_URL`: contagem por tabela, maior id e um resumo (hash)
     das colunas de cada tabela, ordenadas por id, nos dois bancos. Sai com código de erro se algo diferir.
5. `docker-compose.dev.yml` com `postgres:18` e volume próprio. O `docker-compose.yml` de produção **não** ganha banco.
6. Suíte de testes rodando também no PostgreSQL (`DATABASE_URL=… manage.py test`). Pontos a observar: ordenação com
   acentos (o SQLite ordena por byte), `iexact`/`icontains` com acentos, `select_for_update` (`core/alertas.py`, que
   no SQLite é ignorado) e testes que dependem de ids sequenciais.

## Decisões de banco

- Criar o banco com `ENCODING 'UTF8'` e collation ICU em português (`LOCALE_PROVIDER icu`, `ICU_LOCALE 'pt-BR'`), para
  "Álvaro" ordenar junto de "Alvaro". **Muda a ordem das listas em relação a hoje** (para melhor); é uma decisão pendente.
- Um usuário de banco da aplicação, dono só do banco dela; sem superusuário. Para rodar os testes, um usuário com
  `CREATEDB` (só no desenvolvimento local e na homologação).
- Fuso: `TIME_ZONE` continua na aplicação; o banco guarda em UTC (`USE_TZ=True`), como hoje.

## Método de cópia dos dados

**Recomendado: `dumpdata`/`loaddata` do próprio Django**, na mesma versão do código, porque respeita os tipos dos
campos, não chama os `save()` customizados (`raw=True`: não gera histórico de registro nem atividades do SICE) e o
`loaddata` acerta as sequências de id no PostgreSQL ao final.

```bash
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission \
  --format jsonl -o /data/migracao/dados.jsonl.gz
```

- `contenttypes` e `auth.permission` são recriados pelo `migrate` no banco novo.
- As sessões (`sessions`) entram, para ninguém precisar entrar de novo. Se preferir, exclua-as: todos fazem login de
  novo e a lista de aparelhos se limpa sozinha.

Alternativa descartada: `pgloader` direto do arquivo SQLite. É mais rápido, mas converte tipos por conta própria
(booleanos, decimais, datas) e não conhece as regras do Django. Para um banco do tamanho deste, a velocidade não
compensa o risco.

## Ensaio (antes da produção)

1. **Homologação, com dados fictícios** (`popular_demo`): sobe o recurso PostgreSQL 18 no Coolify, roda o
   procedimento inteiro, inclusive a reversão, e cronometra. Corrige o que falhar.
2. **Cópia da produção, em ambiente isolado** (decisão pendente: onde). A homologação só pode ter dados fictícios, então
   o ensaio com dados reais acontece no próprio servidor de produção, num recurso PostgreSQL temporário sem porta
   pública, apagado ao final; ou na sua máquina, com o disco criptografado. Roda `verificar_para_postgres`, corrige os
   dados apontados (com migration de dados ou ajuste manual registrado), repete até sair limpo, e roda
   `comparar_bancos`.
3. Critério para seguir: os dois ensaios sem erro, `comparar_bancos` idêntico, suíte verde no PostgreSQL, tempo total
   da janela conhecido.

## Procedimento em produção

Janela sugerida: fora do horário de estágio (por exemplo, sábado à noite), avisada com antecedência. Tempo esperado:
minutos para o banco atual (confirmar no ensaio).

1. **Congelar:** nenhum outro deploy na véspera. Versão em produção = versão ensaiada.
2. **Parar a aplicação** no Coolify (garante que ninguém escreve durante a cópia).
3. **Backup do SQLite**, com a aplicação parada:
   ```bash
   cd /data && mkdir -p migracao
   sqlite3 db.sqlite3 ".backup migracao/db-antes-postgres.sqlite3"
   sha256sum db.sqlite3 migracao/db-antes-postgres.sqlite3 > migracao/sha256.txt
   ```
   Copie `migracao/db-antes-postgres.sqlite3` e um *tar* de `/data/anexos` para fora do servidor (destino: decisão
   pendente). **Não** para a pasta do projeto nem para o Git.
4. **Verificar:** `python manage.py verificar_para_postgres` (container temporário da mesma imagem, sem `DATABASE_URL`).
   Se apontar problema, pare e volte ao ensaio.
5. **Exportar:** o `dumpdata` acima.
6. **Criar o esquema no PostgreSQL:** container temporário com `DATABASE_URL` do recurso novo → `python manage.py
   migrate`.
7. **Importar:** `python manage.py loaddata /data/migracao/dados.jsonl.gz` no mesmo container.
8. **Comparar:** `python manage.py comparar_bancos --origem sqlite:////data/db.sqlite3 --destino "$DATABASE_URL"`.
   Diferença = parar e reverter (passo R1).
9. **Trocar:** colocar `DATABASE_URL` nas variáveis da aplicação no Coolify e fazer o deploy. O arquivo `db.sqlite3`
   **fica onde está**, intocado.
10. **Conferir a aplicação:** `/saude/`, login de cada perfil (contas de teste), painel, ficha de um estágio, folha
    de frequência, download de um anexo, envio de um push de teste, registro de ações gravando.
11. **Liberar** e acompanhar "Erros do sistema" nas primeiras horas.
12. **Ligar o backup agendado** do recurso PostgreSQL no Coolify (ver abaixo) e fazer o primeiro backup manual.

## Reversão

- **R1 — antes de liberar (passos 6 a 10):** tirar `DATABASE_URL` da aplicação e fazer o deploy. Ela volta ao SQLite,
  que não foi alterado desde o passo 2. Apagar o recurso PostgreSQL ou guardá-lo para análise.
- **R2 — depois de liberar, com dados novos no PostgreSQL:** parar a aplicação, `dumpdata` a partir do PostgreSQL,
  `migrate` + `loaddata` num SQLite novo, `comparar_bancos` ao contrário, trocar o arquivo e tirar `DATABASE_URL`.
  Esse caminho também é ensaiado no passo 1 do ensaio.
- **Ponto sem volta:** depois de duas semanas sem incidentes, o `db.sqlite3` antigo pode ser arquivado fora do
  servidor (não apagado) e a reversão passa a ser só pelo backup do PostgreSQL.

## Backup e restauração

- **Banco:** backup agendado do recurso PostgreSQL no Coolify (`pg_dump`), diário, de madrugada. Retenção sugerida:
  7 diários, 4 semanais e 6 mensais. Cópia para fora do servidor (armazenamento S3 compatível): destino e custo são
  decisão pendente.
- **Arquivos:** o volume `/data` (anexos e chave VAPID) continua precisando de backup próprio, diário, com a mesma
  retenção. O backup do PostgreSQL não cobre os anexos.
- **Antes de deploys com migration:** backup manual do banco (e anotar o nome da migration). O `migrate` automático
  do `entrypoint.sh` continua; o README ganha esse passo na Etapa 1.
- **Teste de restauração mensal:** restaurar o último backup num recurso PostgreSQL temporário, rodar
  `comparar_bancos` contra a produção (contagens próximas, sem erro de restauração) e um `manage.py check
  --database default` com a aplicação apontando para ele. Registrar data e resultado. Apagar o recurso temporário.

## Riscos específicos

| Risco | Mitigação |
|---|---|
| Texto maior que o `max_length` (o SQLite aceita) faz o `loaddata` falhar | `verificar_para_postgres` antes; correção registrada |
| Ordem das listas muda com a collation | decisão de collation; testes de ordenação |
| Conexões abertas por threads | `connection.close()` no fim das threads |
| Migration automática falha no PostgreSQL num deploy futuro | backup manual antes de deploys com migration; homologação primeiro |
| Recurso do banco recriado por engano | banco em recurso separado no Coolify, nunca no compose da aplicação |
| Dados reais na homologação | ensaio com dados reais só em recurso temporário isolado |
