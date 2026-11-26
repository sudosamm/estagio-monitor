# 0003 — Backup do volume de dados para o Cloudflare R2

- **Situação:** aceita (Etapa 1, 26/11/2026). Destino (R2) e retenção 7/4/6 decididos por você na Etapa 0.
- **Decide:** como o volume `/data` (banco SQLite até a migração; depois, anexos e chave VAPID) sai do servidor.

## Contexto

- Hoje o backup é "copiar o volume", sem agendamento nem teste de restauração (risco 5 da Etapa 0).
- O backup agendado do Coolify cobre recursos de banco (o PostgreSQL), não o volume de uma aplicação.
- Os arquivos têm dados pessoais e de saúde (atestados): o que sai do servidor precisa ir cifrado, com a chave fora
  do servidor e fora do R2.

## Opções

1. **rclone (ou restic) num container agendado:** ferramentas maduras, mas mais um container, outra configuração e a
   cópia do SQLite em uso precisa de cuidado à parte (a cópia de um arquivo em WAL pode sair inconsistente).
2. **boto3 + criptografia própria, num comando do Django:** usa o SDK oficial, mas acrescenta ~100 MB à imagem para
   quatro operações (enviar, baixar, listar, apagar).
3. **Comando do Django com cliente S3 mínimo (SigV4 com `requests`) e AES-256-GCM:** sem dependência nova (o
   `requests` e o `cryptography` já estavam na imagem), cópia do SQLite pela API de backup do próprio SQLite e teste de
   restauração no mesmo comando.

## Decisão

Opção 3: `python manage.py backup_dados` (`core/backup.py`).

- Pacote `.tar.gz` com a cópia consistente do SQLite, `anexos/`, a chave VAPID e um `manifesto.json` sem dados
  pessoais (linhas por tabela, quantidade e tamanho dos arquivos, `integrity_check`).
- Cifragem AES-256-GCM em blocos de 4 MB, com chave por arquivo derivada (HKDF) de `BACKUP_CHAVE`. Cada bloco é
  autenticado com o número dele e a marca de último: um arquivo cortado, alterado ou com blocos trocados não abre.
- Retenção: o mais recente de cada um dos últimos 7 dias, 4 semanas e 6 meses; aplicada só depois de o envio aparecer
  na listagem. Objetos com outro nome nunca são apagados.
- `--testar-restauracao` baixa, decifra, extrai numa pasta temporária, confere com o manifesto e apaga a pasta.
  `--restaurar-em PASTA` extrai numa pasta nova (nunca em `/data`).
- A assinatura S3 é testada com os vetores oficiais da AWS; o caminho completo é testado com um armazenamento em
  pasta (`BACKUP_PASTA`), que também serve para um disco externo montado.

## Consequências

- Sem `BACKUP_CHAVE` não há restauração. A chave precisa ficar guardada **fora do servidor** (gerenciador de senhas e
  uma cópia impressa em local seguro da escola).
- O token do R2 deve ter permissão só de leitura e escrita de objetos **neste bucket**.
- Depois da troca para o PostgreSQL, o mesmo comando continua cobrindo os anexos e a chave VAPID; o banco passa a ter
  o backup do próprio Coolify.
- A cifragem é própria, mas usa só primitivas da biblioteca `cryptography` (AESGCM, HKDF), sem algoritmo inventado.
