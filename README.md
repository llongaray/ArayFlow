# Aray Social Publisher — P1 (Google Sheets + Drive)

Pacote de validação e download: **não agenda nem publica no Instagram e não altera a planilha**.

## 1. Preparação Windows

Coloque estes arquivos na pasta `L:\Sistemas\GitHub_llongaray\Auto_post\` (mantendo `config/`). Preserve seu `.env` existente e acrescente as variáveis de `.env.example` que faltarem.

Execute:

```powershell
py -m pip install -r requirements.txt
py -m pip install tzdata
```

## 2. Ativar APIs Google e criar OAuth Desktop

1. Acesse https://console.cloud.google.com e selecione/crie um projeto do Google Cloud na conta **aray.solucoes@gmail.com**.
2. Em **APIs e serviços > Biblioteca**, habilite **Google Sheets API** e **Google Drive API**.
3. Em **Google Auth Platform**, configure a tela de consentimento. Se o aplicativo estiver em modo *Testing*, adicione `aray.solucoes@gmail.com` como usuário de teste.
4. Crie o **OAuth Client ID** para **Desktop app** (Aplicativo para computador).
5. Baixe o JSON e salve como `config/google_credentials.json`. Nunca publique o JSON ou o token no GitHub.
6. Na primeira execução, escolha **aray.solucoes@gmail.com** na janela OAuth.

## 3. Testar

```powershell
py main.py --check
py main.py --date 2026-10-14 --dry-run
py main.py --date 2026-10-14 --download
py main.py --date tomorrow --dry-run
```

- `--check`: autenticação e leitura da planilha.
- `--dry-run`: verifica pasta, nomes, quantidade, legenda e ordem, sem baixar arquivos.
- `--download`: salva as imagens em `downloads/AAAA-MM-DD/ARAY-...`.
- Nenhuma dessas opções cria contêiner, agenda ou publica mídia na Meta.

**Planilha:** https://docs.google.com/spreadsheets/d/1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM/edit

## Observações

- A coluna **Tipo** deve indicar `Imagem única` ou `Carrossel`.
- **Qtd. imagens** deve corresponder à quantidade de slides oficiais. Arquivos contendo `alternativa`, `alternative` ou `backup` são ignorados.
- A coluna **Pasta das imagens** deve conter a URL da pasta Google Drive de cada publicação.
- Utilize o Google OAuth Desktop. O MCP do ChatGPT não é uma credencial OAuth reutilizável automaticamente pelo Python local.
- Em caso de erro de OAuth, nunca exponha credenciais ou tokens ao pedir ajuda.


---

## ArayFlow v0.2.0 — validacao e publicacao controlada

Esta versao adiciona `image_validator.py`, `instagram_publisher.py`, `publication_store.py` e `publish_post.py`.

**IMPORTANTE:** O fluxo completo de publicacao de carrossel ainda nao passou por um teste real. A Meta exige URLs HTTPS publicas diretamente acessiveis para buscar as imagens. O download do Google Drive e local e **nao** fornece essa hospedagem por si so. Nao existe agendamento automatico nesta versao.

### Atualizar localmente

No terminal PowerShell do projeto, com `.venv` ativo:

```powershell
git pull origin main
python -m pip install -r requirements.txt
```

Se ainda nao tiver baixado as imagens:

```powershell
python main.py --date 2026-10-14 --download
```

### Etapa A — validacao offline, sem publicar

```powershell
python publish_post.py --post ARAY-20261014-001
```

O comando verifica a planilha, a quantidade de arquivos locais, integridade, tamanho, resolucao, proporcao e legenda. Nao cria conteineres nem publica.

### Etapa B — preparar conteineres na Meta (opcional)

Antes, revisar o conteudo editorial e mudar o Status da linha para `Aprovado`.

Criar, **somente no seu computador**, um JSON como `data/post-001-urls.json`:

```json
{
  "ARAY-20261014-001_slide-01.png": "https://seu-dominio.exemplo/post-001-slide-01.png",
  "ARAY-20261014-001_slide-02.png": "https://seu-dominio.exemplo/post-001-slide-02.png",
  "ARAY-20261014-001_slide-03.png": "https://seu-dominio.exemplo/post-001-slide-03.png"
}
```

Os enderecos acima sao **apenas exemplos**. As URLs reais precisam servir os arquivos PNG/JPG por HTTPS sem autenticacao nem pagina intermediaria.

```powershell
python publish_post.py --post ARAY-20261014-001 --manifest .\data\post-001-urls.json --prepare
```

Confirmacao interativa: `PREPARAR ARAY`. Isso cria conteineres na Meta, mas **nao publica**. IDs ficam em `data/arayflow.sqlite3`, arquivo ignorado pelo Git.

### Etapa C — publicacao real e imediata (opcional)

```powershell
python publish_post.py --post ARAY-20261014-001 --publish
```

Confirmacao interativa: `PUBLICAR ARAY`. O comando publica imediatamente, nao agenda. Evita segundo envio automatico se houver publicacao confirmada ou resultado incerto.

### Limitacoes importantes

- A planilha Google e consultada com OAuth de **somente leitura**; esta versao nao muda o status no Sheets.
- A conta precisa continuar configurada no `.env` (`TOKEN` e `CONTA_INSTA_ID`).
- Mantenha `.env`, `config/google_credentials.json`, `config/google_token.json`, `data/`, `downloads/` e manifestos locais fora dos commits.
- Registros antigos publicados fora do ArayFlow nao estao no SQLite: revise o perfil antes de publicar.
- O limite de formato aqui e uma verificacao preliminar; a validacao definitiva e feita pela Meta.
- Nao execute comandos de publicacao ate revisar o conteudo, as fontes e as imagens.

### Estado de desenvolvimento

- P0: teste isolado de publicacao de uma imagem — validado anteriormente.
- P1: Google Sheets e Drive — validados para leitura e download.
- P2: validacao offline e modulos de carrossel/idempotencia — implementados, **aguardando teste local e teste real supervisionado**.


---

## v0.3.0 — Cloudflare R2

A integracao R2 usa **boto3** e suas credenciais S3 locais. Nao envia arquivos ao Instagram automaticamente.

Configure no `.env` (NAO comite):

```dotenv
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=arayflow-media
R2_PUBLIC_URL=https://pub-....r2.dev
```

No PowerShell, dentro de `.venv`:

```powershell
git pull origin main
python -m pip install -r requirements.txt
python -m unittest test_arayflow test_r2 -v
python r2_upload.py --check
python r2_upload.py --post ARAY-20261014-001
```

O ultimo comando e um **dry-run** e nao envia nada. Para **fazer upload publico real**, apos revisar as imagens:

```powershell
python r2_upload.py --post ARAY-20261014-001 --upload
```

Digite `ENVIAR R2` quando solicitado. O script gera `data/ARAY-20261014-001-r2-urls.json` com URLs HTTPS, sem publicar no Instagram. O arquivo `data/` e ignorado no Git.

Somente apos **revisao editorial** e apos mudar a coluna Status para `Aprovado`, voce podera usar o fluxo existente, que tambem exige confirmacao:

```powershell
python publish_post.py --post ARAY-20261014-001 --manifest .\data\ARAY-20261014-001-r2-urls.json --prepare
```

O passo `--prepare` cria conteineres na Meta, mas nao publica. `--publish` e separado, publica imediatamente e exige `PUBLICAR ARAY`.

**Limitacoes e seguranca:** URLs no dominio r2.dev sao publicas; ele serve para testes, nao hospedagem de producao. Uploads geram consumo R2; acompanhe as metricas e limites gratuitos. **A exclusao automatica ainda nao esta ativada**, para evitar que imagens sejam removidas antes de a Meta processar os conteineres. O metodo de exclusao do modulo R2 restringe o prefixo gerenciado, mas requer futura rotina de limpeza supervisionada. Integracao real R2/Meta ainda exige validacao local; este commit nao prova conectividade com sua conta.



---

## ArayFlow v0.4.0 — sessoes e limpeza diaria segura

**Objetivo:** manter no Cloudflare R2 apenas as artes do dia selecionado, exceto
imagens ainda necessarias para conteineres Meta e sessoes incompletas.

### Comandos no Windows (sempre no .venv)

```powershell
git pull origin main
python -m pip install -r requirements.txt
python -m unittest test_arayflow test_r2 test_sync -v
```

**1. Consultar sessoes anteriores (SQLite local):**

```powershell
python sync_day.py --sessions
```

**2. Planejar a sincronizacao SEM apagar ou enviar arquivos (padrao):**

```powershell
python sync_day.py --date 2026-10-14
```

Antes de prosseguir, confira a lista de `[REMOVER]`, `[PROTEGER]`,
`[ENVIAR]` e `[REUTILIZAR]`. O comando consulta Google Sheets e R2,
mas NAO faz modificacoes.

**3. Sincronizar o dia com limpeza REAL:**

```powershell
python sync_day.py --date 2026-10-14 --apply
```

O programa exige a confirmacao exata `SINCRONIZAR 2026-10-14`.
Esta operacao **apaga objetos antigos elegiveis do R2 e envia/substitui
imagens**, mas **nao publica no Instagram**. Leia o plano com atencao.

**4. Publicar posteriormente, apos a revisao editorial:**

A sincronizacao cria manifestos em `data/<POST_ID>-r2-urls.json`,
reutilizados pelo publicador que ja existe:

```powershell
python publish_post.py --post ARAY-20261014-001 --manifest .\data\ARAY-20261014-001-r2-urls.json --prepare
```

`--prepare` exige aprovacao no Sheets e confirmacao separada;
`--publish` continua sendo outro comando com confirmacao de publicacao
real e imediata.

### Regras de seguranca da limpeza

1. Valida primeiro TODAS as imagens locais, quantidades, proporcoes e legendas.
   Se alguma estiver faltando/corrompida, **nao apaga nada**.
2. Lista todos os objetos do prefixo `arayflow/`, com paginacao.
   Ignora objetos fora desse prefixo ou fora do padrao de nomes seguro.
3. Objetos de outros dias e imagens nao pertencentes aos posts selecionados
   podem ser excluidos, MAS nunca quando forem de posts com status SQLite
   `prepared`, `publishing`, `uncertain` ou `failed` com conteiner Meta.
4. Protege tambem os dias de sessoes `running` ou `failed`
   ate que a sessao seja resolvida/retomada. Assim um erro nao apaga
   automaticamente imagens que podem estar em uso. Em casos protegidos,
   pode haver objetos de mais de um dia no R2.
5. Para os objetos do dia, reutiliza apenas se o SHA-256 gravado nos metadados
   do R2 corresponder ao arquivo local. Objetos enviados pela v0.3.0,
   que nao possuem hash nos metadados, serao enviados novamente uma vez.
6. Faz a limpeza elegivel ANTES dos novos uploads, sempre depois da validacao
   e confirmacao explicita. Se houver falha, salva `failed` no SQLite
   e a execucao seguinte retoma/verifica o estado remoto.
7. Nao mexe em objetos fora do bucket configurado e nunca apaga credenciais,
   imagens locais, arquivos do Google Drive ou posts no Instagram.

### Persistencia

- Sessao de cada dia: `daily_syncs`.
- Hashes das imagens conhecidas: `r2_assets`.
- Log de sincronizacao e remocoes: `r2_events`.
- Estados e IDs de contêineres/publicacoes Meta: `publications` (versao anterior).
- Banco local: `data/arayflow.sqlite3`, ignorado pelo Git.
- Credenciais permanecem no `.env` e `config/google_token.json`.

**Ainda nao existe execucao automatica por horario.** Execute a
sincronizacao quando desejar ou integre-a futuramente ao Agendador de Tarefas
do Windows. Para operacao sem confirmacao interativa, precisaremos de regras
de seguranca adicionais antes de habilitar modo autonomo.

**Observacao:** GitHub Actions executa apenas testes unitarios simulados; nao
usa credenciais e nao conecta no seu bucket. A conectividade R2 real e a
exclusao real dependem de validacao local supervisionada.
