# Backup do volume `/data` no Cloudflare R2

Primeiro item da Etapa 1. Vale **antes** da migração para o PostgreSQL (o banco SQLite está em `/data`) e **depois**
dela (anexos e chave VAPID). Decisão: [ADR 0003](../decisoes/0003-backup-do-volume-de-dados.md).

## O que é copiado

| Item | Antes do PostgreSQL | Depois |
|---|---|---|
| Banco | cópia consistente do `db.sqlite3` (API de backup do SQLite, com a aplicação no ar) | fora: backup do recurso PostgreSQL no Coolify |
| `anexos/` (atestados, documentos, fotos, folhas) | sim | sim |
| `vapid_privada.pem` (notificações) | sim | sim |
| `manifesto.json` (contagens, sem dados pessoais) | sim | sim |

Tudo vai num `.tar.gz` cifrado (AES-256-GCM). O nome do objeto é `volume-dados/dados-AAAAMMDD-HHMMSS.tar.gz.enc`.

## 1. Preparar o R2 (uma vez)

1. Cloudflare → **R2** → *Create bucket*: por exemplo `estagio-monitor-backup`, local automático. Deixe o bucket
   **privado** (sem domínio público, sem `r2.dev`).
2. R2 → *Manage API tokens* → *Create API token*: permissão **Object Read & Write**, aplicada **só a este bucket**,
   sem prazo (ou com prazo e lembrete de renovar). Anote o *Access Key ID*, o *Secret Access Key* e o endpoint
   (`https://<id-da-conta>.r2.cloudflarestorage.com`).
3. Não configure regra de ciclo de vida no bucket: a retenção 7/4/6 é feita pelo comando (uma regra de expiração
   apagaria os mensais).

## 2. Gerar e guardar a chave

No terminal do container da aplicação (Coolify → recurso → *Terminal*):

```bash
python manage.py backup_dados --gerar-chave
```

- Guarde a chave **fora do servidor**: no seu gerenciador de senhas e numa cópia em papel, num envelope lacrado na
  escola (com a data). **Sem ela, nenhum backup abre.** Ela não vai para o R2.
- Se a chave vazar: gere outra, troque `BACKUP_CHAVE`, faça um backup na hora e apague os backups antigos do bucket
  quando o novo estiver conferido.

## 3. Variáveis no Coolify (recurso da aplicação)

```
BACKUP_CHAVE=<a chave gerada>
BACKUP_S3_ENDPOINT=https://<id-da-conta>.r2.cloudflarestorage.com
BACKUP_S3_BUCKET=estagio-monitor-backup
BACKUP_S3_CHAVE_ID=<Access Key ID>
BACKUP_S3_SEGREDO=<Secret Access Key>
```

Opcionais: `BACKUP_PREFIXO` (padrão `volume-dados`; use outro na homologação, ou outro bucket),
`BACKUP_RETENCAO_DIAS/SEMANAS/MESES` (7/4/6), `BACKUP_TRABALHO` (pasta temporária; padrão `/data/.backup-trabalho`,
que precisa de espaço livre para cerca de duas vezes o tamanho do volume).

**Homologação:** use um bucket separado (ou outro prefixo) e outra chave. Os dados de lá são fictícios, mas os backups
de produção nunca devem ser acessíveis a partir dela.

## 4. Primeiro backup e primeira restauração (na hora)

```bash
python manage.py backup_dados
```

```bash
python manage.py backup_dados --testar-restauracao
```

```bash
python manage.py backup_dados --listar
```

A restauração de teste baixa o backup mais recente, decifra, extrai numa pasta temporária, confere linhas por tabela,
quantidade e tamanho dos arquivos com o manifesto e apaga a pasta. Só depois disso o backup conta como "funcionando".

## 5. Agendar (Coolify → recurso da aplicação → *Scheduled Tasks*)

| Nome | Comando | Frequência (cron) |
|---|---|---|
| backup do volume | `python manage.py backup_dados` | `0 3 * * *` (todo dia, 3h) |
| teste de restauração | `python manage.py backup_dados --testar-restauracao` | `0 4 1 * *` (dia 1º, 4h) |

Falha no backup ou no teste aparece no log da tarefa e em **Erros do sistema** (o aviso vai para os administradores).
Registre a data e o resultado de cada teste mensal (por exemplo, numa planilha de operação).

## 6. Restaurar de verdade (perda do volume ou do servidor)

1. Pare a aplicação no Coolify.
2. Num container temporário da mesma imagem, com as variáveis de backup, extraia numa pasta **nova**:

   ```bash
   python manage.py backup_dados --restaurar-em /data/restauracao-AAAAMMDD
   ```

   (Ou um backup específico: `--objeto volume-dados/dados-AAAAMMDD-HHMMSS.tar.gz.enc`.) O comando já confere o
   conteúdo com o manifesto.
3. Mova o volume atual para o lado (não apague) e coloque o conteúdo restaurado no lugar:
   `db.sqlite3` (se for antes do PostgreSQL), `anexos/` e `vapid_privada.pem` em `/data`.
4. Suba a aplicação e confira: `/saude/`, entrada de cada perfil (contas de teste), um anexo abrindo, um push de teste.
5. Depois de alguns dias sem problema, apague a pasta antiga.

Com o PostgreSQL, o banco volta pelo backup do recurso no Coolify (*Backups → Restore*), e só os arquivos vêm deste
backup.

## 7. Antes de um deploy com migrations

Rode `python manage.py backup_dados` (e, com PostgreSQL, *Backup now* no recurso do banco) e anote no registro do
deploy o nome do backup e a última migration aplicada (`python manage.py showmigrations core | tail -3`).
