## Esse projeto contem o uso de Inteligência Artificial!!

# Coletor de Jurisprudência do STF

## Para que serve

Este programa pesquisa decisões e outros documentos públicos no portal do Supremo Tribunal Federal (STF) e tenta baixar o arquivo PDF de inteiro teor quando ele está disponível.

Você escolhe o tipo de documento, digita palavras-chave e pode limitar a pesquisa por data. Os arquivos são salvos no seu computador. Se configurar o Google Drive, também pode pedir que sejam enviados para uma pasta da sua conta.

O programa roda no seu computador; não é necessário publicar um site ou contratar um servidor. É preciso estar conectado à internet durante as pesquisas e os downloads.

## Começar no Windows

Estas instruções são para Windows 10 ou 11.

### 1. Baixar e abrir o projeto

1. Abra a página do [Projeto Jurisprudência STF no GitHub](https://github.com/HeitorReboucas/jurisprudencia-stf-downloader).
2. Clique no botão verde **Code** e escolha **Download ZIP**.
3. Quando o download terminar, clique com o botão direito no arquivo ZIP e escolha **Extrair Tudo**. Não execute o programa de dentro do ZIP.
4. Abra o VS Code. Escolha **Arquivo > Abrir Pasta** e selecione a pasta `jurisprudencia-stf-downloader-main` que foi extraída.
5. No VS Code, escolha **Terminal > Novo Terminal**. Os comandos abaixo devem ser digitados nesse terminal, dentro da pasta do projeto.

### 2. Instalar o Python

Instale o Python 3.12 ou uma versão mais recente pelo [site oficial do Python](https://www.python.org/downloads/). Depois da instalação, feche e abra novamente o VS Code.

Para conferir se o Windows reconhece o Python, abra o terminal do VS Code em **Terminal > Novo Terminal** e execute:

```powershell
py -3 --version
```

Deve aparecer uma versão do Python. Se o comando `py` não for encontrado, instale o Python pelo site oficial e reinicie o VS Code.

### 3. Preparar o projeto

No terminal, confirme que está na pasta `jurisprudencia-stf-downloader-main` e execute estes comandos, um de cada vez:

```powershell
py -3 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Esses comandos criam um ambiente Python separado para este projeto e instalam os componentes de que ele precisa. No Windows, o coletor usa o Microsoft Edge instalado para abrir a página oficial de pesquisa do STF. Faça essa preparação apenas na primeira vez ou depois de baixar uma cópia nova do projeto.

Se não tiver Microsoft Edge, instale o Chromium controlado pelo Playwright e configure o canal usado pelo programa:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Depois, crie ou edite o arquivo `.env` na pasta do projeto e acrescente:

```text
STF_BROWSER_CHANNEL=chromium
```

Não é obrigatório ativar o ambiente com `Activate.ps1`; usar o caminho `.\.venv\Scripts\python.exe` evita problemas com as permissões do PowerShell.

### 4. Abrir o programa

Inicie o programa com:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Deixe essa janela do terminal aberta enquanto estiver usando o programa. Quando aparecer uma mensagem indicando que o servidor está rodando, abra este endereço no navegador:

**http://127.0.0.1:8000**

Para encerrar, volte ao terminal e pressione **Ctrl+C**. O endereço é local: só funciona enquanto o programa estiver aberto neste computador.

## Fazer uma pesquisa e baixar os PDFs

Na página que abrir no navegador:

1. Em **Tipo de conteúdo**, marque o material que deseja pesquisar. A opção **Acórdãos** já vem selecionada.
2. Digite os termos no campo **Palavras-chave**. Por exemplo: `mulheres e direito fundamental`.
3. Se não quiser limitar por data, deixe **Data inicial** e **Data final** vazias. A pesquisa usará as datas disponíveis no portal.
4. Se quiser limitar o período, informe uma data inicial, uma data final ou ambas. As datas se referem à **publicação** do documento.
5. Se quiser, preencha **Classe processual**, como `RE`. Esse campo é opcional.
6. Para guardar os PDFs somente neste computador, mantenha **Não enviar ao Drive** selecionado.
7. Clique em **Iniciar coleta** e acompanhe o andamento na seção **Execução**.

As palavras-chave são obrigatórias: a pesquisa oficial do STF só é iniciada a partir delas. As datas e a classe processual apenas restringem os resultados. Uma consulta sem data pode encontrar muitos documentos e levar mais tempo.

Por padrão, o portal procura documentos que correspondam a todos os termos digitados. O programa envia a expressão ao mecanismo de pesquisa oficial do STF; portanto, os operadores e as aspas seguem as regras desse portal.

### O que significam os contadores

| Contador | O que mostra |
| --- | --- |
| **Encontrados** | Documentos que apareceram nos resultados da pesquisa. |
| **Baixados** | PDFs que foram salvos no computador. |
| **Enviados** | PDFs enviados para o Google Drive, quando configurado. |
| **Duplicados** | PDFs idênticos a outro arquivo já registrado. |
| **Erros** | Documentos ou envios que precisam de atenção. Consulte o registro da execução. |

O seletor **Coletas recentes** permite consultar uma execução anterior. Se uma coleta for interrompida, selecione-a e use **Retomar** depois de resolver ou aguardar a causa da interrupção. Coletas que ainda estavam na fila quando o programa foi fechado também aparecem como interrompidas e podem ser retomadas.

## Onde os arquivos ficam

Por padrão, o programa cria uma pasta chamada `data` dentro da pasta do projeto:

```text
data/
	downloads/
		STF/
			Acórdãos/2024/
			Decisões Monocráticas/2024/
			Súmulas/2024/
			Informativos/2024/
	jurisprudencias.sqlite3
```

As pastas por ano aparecem conforme os documentos são encontrados. O banco `jurisprudencias.sqlite3` guarda o histórico das coletas, os filtros, os contadores e os dados dos documentos. Não apague esse arquivo se quiser manter o histórico e a possibilidade de retomar jobs.

Se o envio ao Drive falhar, um PDF já baixado continua salvo no computador. Os arquivos e o histórico não são enviados ao GitHub.

## Usar o Google Drive (opcional)

O Google Drive não é necessário para pesquisar nem baixar. Pule esta seção se quiser apenas guardar os PDFs no computador.

Para habilitar o Drive, é preciso criar credenciais de acesso no Google Cloud. Esse passo é separado da instalação do programa:

1. Entre no [Google Cloud Console](https://console.cloud.google.com/) com sua conta Google e crie um projeto.
2. Habilite a **Google Drive API** nesse projeto.
3. Configure a tela de consentimento OAuth. Se o Google deixar o aplicativo em modo de teste, adicione sua conta Google como usuária de teste.
4. Crie um identificador de cliente OAuth do tipo **Web application**.
5. Em **URIs de redirecionamento autorizados**, adicione exatamente `http://localhost:8000/api/drive/oauth/callback`.
6. Baixe o arquivo JSON de credenciais e coloque-o na pasta principal do projeto com o nome `credentials.json`.
7. Com o programa rodando, clique em **Conectar Drive** e autorize o acesso no navegador.
8. Volte à página do coletor, clique em **Atualizar** e escolha uma pasta do Drive.
9. Inicie uma coleta. O programa criará dentro da pasta escolhida uma estrutura `STF/tipo/ano`.

O Google pode mostrar uma tela de aviso para aplicativos em teste; siga apenas se reconhecer o projeto e estiver usando suas próprias credenciais. O token de autorização fica em `data/google-token.json`. Não compartilhe nem publique `credentials.json` ou esse token. O projeto já ignora esses arquivos no Git.

A autorização configurada atualmente permite ao programa listar as pastas do Drive e enviar PDFs. O Google solicitará uma permissão ampla para o Drive, não limitada tecnicamente só à pasta que você selecionar. Leia a tela de consentimento antes de aprovar; você pode revogar o acesso depois nas configurações da sua Conta Google.

Se o callback OAuth não funcionar, confirme que o programa está na porta 8000 e que o endereço foi cadastrado sem diferenças no Google Cloud. Se escolher outra porta, o endereço de retorno também precisa ser atualizado na configuração do programa e no Google Cloud.

## Se algo der errado

### A página não abre

- Confira se o terminal ainda mostra o servidor em execução.
- Abra exatamente `http://127.0.0.1:8000`.
- Se aparecer que a porta está ocupada, outro programa já está usando a porta 8000. Encerre esse programa ou configure uma porta diferente; para usar o Drive, ajuste também o endereço de retorno OAuth.

### O comando `py` não funciona

Instale o Python 3.12 ou mais recente pelo site oficial, feche e abra novamente o VS Code e tente `py -3 --version` outra vez. Confirme também que o terminal está aberto dentro da pasta do projeto.

### A pesquisa terminou sem documentos

Confira se selecionou o tipo de conteúdo correto, se os termos foram escritos como pretendido e se o período escolhido não exclui os resultados. As datas são de publicação, não necessariamente de julgamento. O portal do STF determina quais documentos correspondem aos termos.

No Windows, confirme que o Microsoft Edge está instalado. No macOS e Linux, instale o navegador do Playwright uma vez:

```bash
.venv/bin/python -m playwright install chromium
```

No macOS e Linux, faça esse passo logo depois de instalar as dependências. Se usar o Chromium do Playwright no Windows, adicione `STF_BROWSER_CHANNEL=chromium` ao arquivo `.env`.

### A coleta ficou como “Interrompida” e mostra HTTP 202

O coletor abre a página oficial de pesquisa em um navegador e valida automaticamente o endereço da requisição, o formato da resposta e a origem dos links de PDF antes de processar documentos. Se a URL de pesquisa não iniciar a busca, ele tenta enviar as palavras pelo campo oficial do próprio portal. Em alguns momentos o STF ainda pode responder temporariamente sem resultados, inclusive por controles de tráfego. O programa registra a interrupção e não tenta contornar essa proteção. Aguarde um pouco e depois selecione a coleta em **Coletas recentes** e clique em **Retomar**.

Se o registro disser que os filtros de data e classe não puderam ser aplicados, o portal mudou o formato da pesquisa. O programa para a coleta em vez de baixar documentos fora do período ou da classe escolhidos. Nesse caso, o código de integração precisa ser atualizado.

### Um documento aparece como erro ou não foi baixado

Nem todo resultado tem um arquivo de inteiro teor disponível para download. O coletor registra esse caso e continua com os outros documentos. Abra o registro da execução para ver a mensagem específica.

- **Súmulas e informativos:** o portal normalmente não informa um PDF de inteiro teor para esses tipos, então eles costumam aparecer como erro com a mensagem "sem URL de inteiro teor".
- **Verificação anti-robô:** o servidor de documentos do STF pode exigir uma verificação anti-robô antes de liberar o PDF, o que acontece com frequência nos acórdãos. O programa não contorna essa proteção; o registro indica o documento, que pode ser baixado manualmente pelo portal.

### O Google Drive não conecta ou o upload falha

O download local funciona sem o Drive. Para enviar arquivos, confirme as credenciais, a autorização no navegador e a pasta selecionada. Se o envio falhar, o PDF permanece no computador e pode ser reenviado depois.

## Outros sistemas operacionais

O projeto também pode ser executado em macOS e Linux com Python 3.12 ou mais recente. No terminal aberto na pasta do projeto, crie o ambiente e instale as dependências:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Inicie a aplicação com:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Depois, abra `http://127.0.0.1:8000` no navegador. No macOS e Linux, a pasta do ambiente virtual é `.venv/bin`; no Windows, é `.venv\Scripts`.

## Informações técnicas (opcional)

### API e documentação interativa

Quem quiser usar a API diretamente pode abrir **http://127.0.0.1:8000/docs** enquanto o programa estiver rodando. A página permite consultar os endpoints e enviar pedidos de teste. A tela principal do coletor não exige conhecimento de API.

Para iniciar uma coleta por API, envie uma requisição `POST /api/jobs`. Este exemplo pesquisa acórdãos por palavras-chave sem limitar a data:

```json
{
	"content_types": ["acordaos"],
	"query": "mulheres e direito fundamental"
}
```

O campo `query` é obrigatório. As datas `date_from` e `date_to` são opcionais. Valores possíveis para `content_types`: `acordaos`, `decisoes_monocraticas`, `sumulas` e `informativos`.

Principais endereços da API:

| Endereço | Para que serve |
| --- | --- |
| `GET /api/health` | Verifica se o serviço está ativo. |
| `GET /api/content-types` | Lista os tipos de conteúdo. |
| `POST /api/jobs` | Inicia uma coleta. |
| `GET /api/jobs` | Lista coletas recentes. |
| `GET /api/jobs/{job_id}` | Consulta o estado de uma coleta. |
| `GET /api/jobs/{job_id}/events` | Consulta o registro de eventos. |
| `POST /api/jobs/{job_id}/resume` | Retoma uma coleta interrompida ou com erros. |
| `GET /api/documents` | Lista documentos salvos no catálogo local. |
| `POST /api/documents/{document_id}/upload` | Envia novamente um PDF local ao Drive. |
| `GET /api/drive/status` | Verifica a configuração do Drive. |
| `GET /api/drive/auth/url` | Inicia a autorização do Drive. |
| `GET /api/drive/folders` | Lista pastas disponíveis no Drive. |

### Configurações avançadas

Normalmente não é necessário alterar estas opções. Se precisar, crie ou edite um arquivo `.env` na pasta do projeto:

| Opção | Valor inicial | Explicação simples |
| --- | --- | --- |
| `DATA_DIR` | `data` | Onde guardar o banco, os PDFs e o token do Drive. |
| `STF_TIMEOUT_SECONDS` | `90` | Tempo máximo para abrir o portal e receber a resposta da pesquisa. |
| `STF_REQUEST_DELAY_SECONDS` | `1.0` | Pausa mínima entre pesquisas no STF. Não pode ser menor que 1 segundo. |
| `STF_MAX_ATTEMPTS` | `3` | Número de tentativas para downloads de PDF com falhas temporárias. |
| `STF_BROWSER_CHANNEL` | Edge no Windows; Chromium padrão em outros sistemas | Navegador que o Playwright deve abrir. |
| `DOWNLOAD_MAX_BYTES` | `52428800` | Tamanho máximo permitido por PDF, aproximadamente 50 MiB. |
| `DOWNLOAD_TIMEOUT_SECONDS` | `60` | Tempo máximo de espera por cada PDF. |
| `GOOGLE_CLIENT_SECRETS_FILE` | `credentials.json` | Local do arquivo de credenciais OAuth. |
| `GOOGLE_TOKEN_FILE` | `data/google-token.json` | Local do token OAuth salvo após autorização. |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/drive/oauth/callback` | Endereço local de retorno da autorização Google. |

### Segurança e limites

- O coletor consulta informações públicas no portal oficial do STF e respeita uma pausa mínima entre pesquisas.
- Ele não tenta contornar CAPTCHA, bloqueios ou controles de acesso do portal.
- Esta aplicação foi feita para uso local e não tem login próprio. Mantenha o endereço de escuta em `127.0.0.1`; não exponha o serviço diretamente à internet.
- O Google Drive é uma integração opcional. As credenciais e o token são arquivos privados e não devem ser enviados ao GitHub.
- A pesquisa depende do serviço do STF. Se o portal estiver indisponível ou mudar, a execução poderá ser interrompida até o serviço voltar ou o código de integração ser atualizado.

### Testes do projeto

Para quem estiver desenvolvendo, os testes automatizados podem ser executados no Windows com:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

No macOS ou Linux:

```bash
.venv/bin/python -m pytest -q
```

Os testes usam respostas simuladas e banco temporário; não precisam das credenciais do Google e não iniciam pesquisas reais no STF.

### Palavras que aparecem neste manual

| Palavra | Significado |
| --- | --- |
| **Coleta** | Uma pesquisa e o processamento dos documentos encontrados. |
| **PDF de inteiro teor** | Arquivo que contém o documento completo, quando o STF o disponibiliza. |
| **API** | Uma forma de outro programa conversar com este coletor. O usuário comum pode ignorar essa parte. |
| **OAuth** | Processo pelo qual o Google pede sua autorização para o programa acessar o Drive. |
| **Banco de dados local** | Arquivo no computador que guarda o histórico e o andamento das coletas. |
| **Duplicado** | Arquivo idêntico a outro já baixado, reconhecido pelo conteúdo. |
