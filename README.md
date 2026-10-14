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


---

## v0.5.0 — Agendamento automatico de publicacoes

O Windows executa `scheduled_publish.py` a cada 5 minutos. O programa le os posts **do dia atual**, pelo fuso `America/Sao_Paulo`, e **somente posts com Status "Aprovado"** podem ser preparados/publicados.

- Ate 10 minutos antes do horario: baixa artes ausentes do Google Drive, valida PNG/JPG, limpa arquivos **de dias anteriores** do R2 (respeitando sessoes/publicacoes pendentes), sobe ou reutiliza as imagens e prepara o conteiner Meta.
- No horario da planilha: verifica o conteiner e publica. Uma tolerancia maxima de 15 minutos permite pequenos atrasos; atrasos maiores sao ignorados, sem compensacao automatica.
- Sessao SQLite: estados `preparing`, `prepared`, `publishing`, `published`, `uncertain`. Se uma chamada externa falhar com resultado incerto, o ArayFlow **nao tenta publicar de novo** ate revisao manual.
- Posts de outras datas nao sao publicados retroativamente.
- **Nao atualiza automaticamente a coluna Status do Google Sheets** (OAuth atual e somente leitura). Use SQLite e logs para acompanhar e revise a planilha manualmente.
- Nao executa nenhuma chamada de escrita se `--live` estiver ausente.
- Mesmo com `--live`, a publicacao e bloqueada ate que `ARAYFLOW_AUTOPUBLISH_ENABLED=true` seja configurado manualmente no `.env`.

### Instalacao e validacao

No PowerShell, na pasta do projeto, com `.venv`:

```powershell
git pull origin main
python -m pip install -r requirements.txt
python -m unittest test_arayflow test_r2 test_sync test_scheduler -v
python scheduled_publish.py --once
```

O ultimo comando e **DRY-RUN**. Ele consulta a planilha e mostra `WAIT`, `PREPARE`, `DUE`, `EXPIRED` ou `SKIP`. Nao sobe imagens nem publica.

**Ativar conscientemente o envio automatico:**

1. Revise a coluna `Status`, os horarios e as imagens. **Atencao: um post ja `prepared` no SQLite pode ser publicado no proximo horario.**
2. Configure `ARAYFLOW_AUTOPUBLISH_ENABLED=true` no `.env` local (nunca no Git).
3. Execute o instalador da tarefa agendada:

```powershell
.\install_scheduler.ps1
```

O instalador cria `ArayFlow Publisher` no Agendador de Tarefas do Windows, com verificacao a cada **5 minutos** e `--once --live`, usando `.venv\Scripts\python.exe`.

A tarefa foi projetada para a **sessao interativa do usuario** (sem armazenar senha Windows); mantenha o usuario logado e o computador acordado/conectado. Se o Windows hibernar, o script ignora horarios mais de 15 minutos atrasados. A renovacao de um OAuth Google expirado pode exigir intervencao no navegador.

**Consultar os logs:**

```powershell
Get-Content .\logs\scheduled_publish.log -Tail 40
```

**Pausar a tarefa de publicacao automatica:**

```powershell
Disable-ScheduledTask -TaskName "ArayFlow Publisher"
```

**Reativar:**

```powershell
Enable-ScheduledTask -TaskName "ArayFlow Publisher"
```

**Remover:**

```powershell
.\install_scheduler.ps1 -Remove
```

Se o PowerShell bloquear arquivos `.ps1`, use `powershell -NoProfile -ExecutionPolicy Bypass -File .\install_scheduler.ps1` apenas para esta invocacao, sem alterar a politica global.

### Limitacoes e cuidados

- GitHub Actions executa apenas testes **offline**. Testes reais da tarefa agendada dependem do seu Windows, tokens Google/Meta e R2.
- A tarefa nao pesquisa noticias, nao gera artes e nao cria linhas na planilha: essas etapas continuam no fluxo editorial existente.
- As imagens do Google Drive precisam estar completas antes da janela de preparacao.
- A execucao pode ocorrer alguns minutos apos o horario da planilha; **nao e agendamento nativo nos servidores da Meta**.
- As imagens de posts com sessao Meta `prepared`, `preparing`, `publishing` ou `uncertain` sao protegidas contra a limpeza automatica.
- Se quiser primeiro apenas o agendamento sem publicacao, NAO defina `ARAYFLOW_AUTOPUBLISH_ENABLED=true`; a simulacao manual continua disponivel.



---

## ArayFlow v0.7.0 — Flask + Playwright para o Meta Business Suite

**Objetivo:** revisar a programacao do dia num painel local e agendar as publicacoes
pela interface visivel do **Meta Business Suite**, para que a Meta publique no
horario sem depender do Windows ligado. Esse fluxo nao usa o endpoint
`media_publish` do Instagram nem requer armazenamento Cloudflare R2.

**Avisos importantes:** o Meta Business Suite nao oferece API publica para
registrar agendamentos nativos do Instagram. O Playwright acessa a interface
web como um usuario: os campos mudam com o tempo. Por seguranca, a v0.7
**nao clica no botao final de Agendar**. Voce confere a pagina/conta, data,
hora, fuso e imagens, clica em Agendar e verifica o post no Planejador.
Somente depois marca como confirmado no terminal. O status no SQLite e
**declarado pelo operador**, nao uma confirmacao programatica da Meta.

### Instalar no Windows, usando exclusivamente o .venv

```powershell
git pull origin main
python -m pip install -r requirements.txt
python -m unittest test_arayflow test_r2 test_sync test_scheduler test_business_suite -v
```

O ultimo comando testa os fluxos com simulacoes de arquivos/sessoes, **sem
efetuar agendamentos reais**.

### Iniciar painel Flask (somente localhost)

```powershell
python dashboard.py
```

Acesse **http://127.0.0.1:8766**. Depois de desativar a API no `.env`
e pausar `ArayFlow Publisher`, escolha a data e clique em
**Abrir assistente do Business Suite**. O Flask abre uma janela de console
Windows interativa, que inicia o Google Chrome instalado e faz as perguntas de confirmacao.
O botao nao funciona se a publicacao automatica por API ainda estiver ativa.
Reinicie o Flask depois de mudar o `.env` para que a configuracao seja relida.

Acesse **http://127.0.0.1:8766**. O painel exibe publicacoes da planilha,
artes baixadas, legenda, historico SQLite, R2 e os status da API/Business Suite.
A unica acao administrativa web disponivel e pausar/retomar explicitamente
a tarefa Windows, com confirmacao e protecao CSRF. O painel nao publica
nem exclui arquivos. Nao exponha essa porta em Cloudflare Tunnel/LAN.

### Antes de usar o assistente Business Suite

O agendador Meta Graph API de v0.5 pode publicar posts aprovados diretamente
no Instagram. **Nunca use os dois agendadores para o mesmo post.**

1. Abra o `.env` e altere `ARAYFLOW_AUTOPUBLISH_ENABLED=false`.
2. Pause a tarefa do Windows para nao ficar processando a API:

```powershell
Disable-ScheduledTask -TaskName "ArayFlow Publisher"
```

3. Revise o Status `Aprovado`, a legenda, as artes e os horarios no Google Sheets.
4. O post `ARAY-20261014-001` ja pode possuir um conteiner `prepared` pela
   Meta Graph API: por seguranca, o assistente **ignora automaticamente**
   posts com qualquer sessao API no SQLite, para evitar duplicatas.
   Resolva o preparo antigo manualmente antes de tentar agendar esse post pelo
   Business Suite, e nao apague linhas SQLite sem verificar a conta Instagram.

### Simular e programar um dia

Simulacao (somente leitura):

```powershell
python business_suite_assistant.py --date 2026-10-14
```

Iniciar sessao VISIVEL do Playwright (iterar os posts aprovados em ordem de hora):

```powershell
python business_suite_assistant.py --date 2026-10-14 --start
```

No primeiro uso, o Google Chrome instalado sera aberto com perfil exclusivo. Entre na conta
Meta **manualmente** e conclua qualquer verificacao em duas etapas.
Quando estiver no criador de publicacao do Business Suite com Instagram
`@aray_solucoes` selecionado, responda `PRONTO` no PowerShell.

O programa tenta carregar os arquivos e inserir a legenda, quando reconhece
um unico campo com seguranca. Se nao encontrar, voce completa manualmente.
**Em todos os casos**, voce seleciona a data/hora no Business Suite,
clica em **Agendar** e verifica no **Planejador**. Depois confirma no
PowerShell digitando `AGENDADO ARAY-YYYYMMDD-001` (ID exato do post).
O assistente prossegue para o proximo post aprovado.

Se algo nao estiver certo, **nao confirme**: o post fica em
`needs_review` e o lote para. Verifique primeiro no Business Suite
antes de uma nova tentativa. A nao confirmacao nao e considerada falha
de publicacao da Meta; ela apenas impede duplicatas.

Agendar apenas um post especifico:

```powershell
python business_suite_assistant.py --date 2026-10-14 --post ARAY-20261014-002 --start
```

Consultar estados persistidos no SQLite, sem acessar a Meta:

```powershell
python business_suite_assistant.py --status
```

Se uma sessao terminou antes do registro local, voce pode confirmar
posteriormente **somente depois de verificar o agendamento no Planejador**:

```powershell
python business_suite_assistant.py --confirm ARAY-20261014-002
```

### Seguranca e persistencia

- Perfil/cookies do Chrome em `data/playwright_chrome_profile/`, fora do GitHub;
  nao compartilhe essa pasta, pois ela pode conter uma sessao autenticada.
- Banco SQLite `data/arayflow.sqlite3`: nova tabela `business_suite_schedule`
  com estados `awaiting_confirmation`, `needs_review` e `scheduled`.
- Reservas atomicas: posts com sessao API anterior nao sao criados no
  Business Suite; posts reservados no Suite sao ignorados pela rotina API.
- Sem CAPTCHA/MFA automatizados, sem tentativa de burlar controles da Meta.
  O uso de automacao de navegador pode estar sujeito a restricoes da plataforma.
- Nao ha garantia de seletores Playwright para a interface atual: na primeira
  execucao real, pode ser necessario preencher campos manualmente.
- O painel Flask funciona apenas em `127.0.0.1`; nao disponibiliza login
  web porque nao e destinado a acesso externo.
- Agendamentos apenas para horarios **futuros**; posts expirados nao sao agendados
  automaticamente.



---

## ArayFlow v0.7.1 — Google Chrome instalado e sessao persistente

O assistente do Business Suite utiliza agora **o Google Chrome instalado no
Windows**, em vez do Chromium distribuido pelo Playwright.

- Motor: Playwright com `channel="chrome"` e navegador visivel.
- Perfil EXCLUSIVO: `data/playwright_chrome_profile/`. Permanece salvo entre
  execucoes, inclusive cookies, enquanto a Meta mantiver a sessao valida.
- O Google Chrome pessoal pode continuar aberto. **Nao reaproveitamos** janelas
  ja abertas nem os cookies do perfil pessoal `Default`; isso evita conflitos
  com as restricoes atuais de depuracao remota do Chrome.
- Na primeira execucao desse perfil exclusivo, faca login no Facebook/Meta
  e conclua eventuais verificacoes em duas etapas manualmente.
- O perfil anterior `data/playwright_meta_profile/` (Chromium da v0.7.0)
  **nao e apagado nem copiado**; portanto, o novo Chrome pede login inicial.
- Se o Chrome nao estiver instalado, o script informa o erro. Instale o
  Google Chrome normalmente no Windows. **Nao e necessario**
  `python -m playwright install chromium` para este fluxo.
- O painel Flask continua abrindo o assistente pelo botao e por PowerShell;
  nenhuma modificacao nos controles anti-duplicidade, na planilha ou na API Meta.

Atualizacao e testes (PowerShell com `.venv` ativo):

```powershell
git pull origin main
python -m pip install -r requirements.txt
python -m unittest test_arayflow test_r2 test_sync test_scheduler test_business_suite -v
```

Para usar com um unico post futuro aprovado, com o agendador Meta API desativado:

```powershell
python business_suite_assistant.py --date AAAA-MM-DD --post ARAY-AAAAMMDD-NNN --start
```

Ou abra o painel:

```powershell
python dashboard.py
```

Painel local: http://127.0.0.1:8766

**IMPORTANTE:** dados do perfil Chrome sao sensiveis e permanecem somente
no computador. Nao compartilhe `data/playwright_chrome_profile/`.
O assistente ainda exige que voce confira e confirme manualmente a
programacao no Planejador do Meta Business Suite.


### Correcao do erro 403 ao pausar ou retomar pelo Flask

O painel em `http://127.0.0.1:8766` usa tokens assinados por acao,
validos por **15 minutos**. Os formularios nao dependem de o navegador
preservar cookies de sessao para validar CSRF. Cada botao possui um token
especifico; requisicoes sem token, com token vencido, reutilizado em outra
acao ou de origem externa continuam bloqueadas.

Se visualizar `403 Forbidden`:
1. Volte a `http://127.0.0.1:8766`, atualize a pagina (`Ctrl+F5`)
   e envie o formulario novamente em menos de 15 minutos.
2. Verifique no terminal Flask o motivo (token ou origem); o programa nao
   grava valores sensiveis dos tokens nos logs.
3. Para desativar a tarefa sem o painel, utilize
   `Disable-ScheduledTask -TaskName "ArayFlow Publisher"` no PowerShell
   e confirme o estado com
   `(Get-ScheduledTask -TaskName "ArayFlow Publisher").State`.

Depois de `git pull origin main`, **reinicie o servidor Flask** para que
a correcao seja carregada. Nenhum token, senha ou cookie foi publicado no Git.


### Correcao adicional: botao do Business Suite com HTTP 403 de Origin

Algumas combinacoes de navegador/localizacao apresentam `Origin` com
`localhost:8766` enquanto o painel Flask esta aberto em
`127.0.0.1:8766` (ou vice-versa). A verificacao anterior usava
`request.host_url` como unica referencia e recusava a operacao.

Agora os formularios assinados do ArayFlow aceitam **exclusivamente**
`http://localhost:8766` e `http://127.0.0.1:8766`, conservando a
verificacao CSRF de 15 minutos. Requisicoes de sites externos nao sao
autorizadas. Quando houver bloqueio, o terminal do Flask registra a
origem recebida e o host requisitado, sem divulgar tokens de autorizacao.

Para atualizar, interrompa o Flask com `Ctrl+C`, execute `git pull origin main`,
`python -m unittest test_business_suite -v`, reinicie com
`python dashboard.py` e atualize a pagina com `Ctrl+F5`. O botão
**Abrir assistente do Business Suite** volta a funcionar somente com
`ARAYFLOW_AUTOPUBLISH_ENABLED=false` e a tarefa Windows desativada.


### Correcao: Chrome envia Origin=null ao abrir o Business Suite (403)

O Chrome pode enviar `Origin: null` ao submeter formulario do painel local,
dependendo da politica de referencia do navegador ou de extensoes instaladas.
O Flask agora retorna `Referrer-Policy: same-origin` e aceita o caso
`Origin: null` **somente quando** `Sec-Fetch-Site: same-origin` indica que a
requisicao veio da propria pagina, sempre exigindo token CSRF assinado e
valido (ate 15 minutos). `Sec-Fetch-Site: cross-site`, origens externas
e tokens invalidos continuam retornando HTTP 403.

Para aplicar a correcao, pare o Flask com Ctrl+C, execute
`git pull origin main`, depois
`python -m unittest test_business_suite -v` e
`python dashboard.py`. No Chrome, atualize `http://127.0.0.1:8766`
com Ctrl+F5 e tente novamente. Se persistir, envie a linha de WARNING
do terminal (incluindo Sec-Fetch-Site, sem compartilhar cookies).


---

## ArayFlow v0.7.2 — Chrome pessoal JA ABERTO e LOGADO

O modo `--browser existing` conecta o assistente a sua sessao EXISTENTE do
Google Chrome (Chrome 144+) usando o **Chrome DevTools MCP oficial** com
`--autoConnect`. Ao contrario do modo isolado, **nao abre outro executavel
Chrome nem cria um perfil novo**. Reutiliza as abas, login e cookies que ja
estao abertos no Chrome, sem copiar cookies para arquivos.

A conexao requer permissao manual dentro do Chrome e pode dar acesso ao
conteudo de outras abas do perfil. Use apenas com codigos de confianca;
desative o acesso de depuracao depois de usar. **Nao compartilhe o perfil
ou seus dados de navegacao.** O ArayFlow so seleciona abas do dominio
`business.facebook.com`, ou abre uma aba nova nesse dominio caso ainda
nao exista; nunca le dados de outra aba intencionalmente.

### Antes de iniciar

1. Instale **Node.js 22+** e confirme no PowerShell:
   `node -v` e `npx -v`.
2. No Google Chrome que voce ja usa (e onde a Meta esta logada), acesse:
   `chrome://inspect/#remote-debugging`.
3. Ative **Allow remote debugging for this browser instance**.
   Nao feche o seu Chrome pessoal.
4. No `.env`, mantenha `ARAYFLOW_AUTOPUBLISH_ENABLED=false` e pause a
   tarefa Windows `ArayFlow Publisher`.
5. Atualize o projeto e instale os pacotes Python:

```powershell
git pull origin main
python -m pip install -r requirements.txt
python -m unittest test_arayflow test_r2 test_sync test_scheduler test_business_suite test_existing_chrome -v
```

### Pelo Flask (recomendado)

```powershell
python dashboard.py
```

Acesse http://127.0.0.1:8766 e selecione a data, na secao
**Assistente Business Suite** clique em **Conectar ao meu Chrome ja aberto
(logado)**. Uma janela de console abre o assistente; digite
`CONECTAR CHROME` para solicitar acesso. O Chrome devera exibir uma
solicitacao de permissao: escolha **Permitir** somente se reconhecer o
ArayFlow. Um servidor MCP local e iniciado, mas nao e exposto na rede.

O programa seleciona uma aba existente do Business Suite. Se nenhuma
aba estiver aberta, abre uma nova aba do Business Suite DENTRO DO MESMO
Chrome ja logado. Selecione o Instagram `@aray_solucoes` e abra o
compositor. Digite `PRONTO` no console. Ele tenta carregar imagem(ns) e
legenda somente se identificar os campos de forma nao ambigua; quando
nao for possivel, preencha manualmente. **O assistente nao clica em
Publicar nem Agendar**: confira data/hora/conta e clique em Agendar
voce mesmo. Verifique o post no Planejador e confirme pelo console.

O perfil exclusivo `data/playwright_chrome_profile` da versao anterior
continua disponivel, sem migrar cookies, pelo botao alternativo de
**Chrome em perfil isolado**. Nenhuma sessao anterior e apagada.

### Pelo PowerShell (sem painel Flask)

```powershell
python business_suite_assistant.py --date 2026-10-14 --start --browser existing
```

O Chrome existente requer Chrome >=144, Node.js >=22 e acesso autorizado
em `chrome://inspect/#remote-debugging`. Na primeira utilizacao,
`npx` pode baixar o pacote npm oficial `chrome-devtools-mcp` da internet.

**Limitacoes:** esta e uma integracao assistida e experimental. A Meta pode
alterar os campos de upload e legenda; os preenchimentos automaticos podem
falhar, voltando ao processo manual. O status "scheduled" no banco e
registrado APENAS apos a confirmacao humana no Planejador.

Mais informacoes:
- https://developer.chrome.com/docs/devtools/agents/get-started/configuration
- https://github.com/ChromeDevTools/chrome-devtools-mcp


### Diagnostico de conexao Chrome DevTools MCP (v0.7.2)

Se o modo `--browser existing` retornar erro generico antes da tela do
Business Suite, atualize o projeto e execute o diagnostico:

```powershell
git pull origin main
python -m unittest test_existing_chrome -v
python business_suite_assistant.py --diagnose-chrome
```

Esse comando NAO usa Google Sheets, nao cria publicacoes/agendamentos,
nao grava reservas no SQLite e nao clica em paginas. Ele inicia o MCP,
pede autorizacao no Chrome e conta somente abas do dominio
`business.facebook.com`.

**Preparacao:** no Chrome pessoal (144+), abra
`chrome://inspect/#remote-debugging`, habilite a depuracao e autorize
a conexao solicitada. Se houver varios perfis do Chrome, o autoConnect
seleciona o perfil padrao, que pode nao ser o perfil logado. Feche
temporariamente outras conexoes Chrome DevTools MCP que possam competir
pela sessao. Node.js 22+ e `npx` precisam estar disponiveis no PATH.

A partir desta revisao, o comando mostra a causa interna do SDK MCP
(inclusive erros de `ExceptionGroup`) com tentativa de ocultar URLs,
tokens, cookies e outros segredos. **Antes de compartilhar o resultado,
revise-o e remova quaisquer dados sensiveis remanescentes.**

Se o diagnostico retornar `[OK] MCP conectado`, use normalmente:

```powershell
python business_suite_assistant.py --date 2026-10-14 --start --browser existing
```

Referencia oficial: https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/troubleshooting.md
