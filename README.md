# CCOMaps

Módulo de **mapas, camadas e informações geográficas** da família CCO (CCOHub · CCOMaps · CCOFlow · CCOLive). Por enquanto, todas as camadas, inclusive trânsito, Waze e aeronaves, ficam aqui. A separação em CCOFlow e CCOLive está registrada para o futuro.

**Camadas do painel:** Medidores de Velocidade (Controlador, Redutor, Não metrológico) · Previsão do tempo (Chuva, Temperatura, com barra de 48 h) · Mapa base e Vista ficam na barra compacta do canto superior direito. O painel é rebatível (botão ‹) e tem transparência ajustável, que vale para caixas e textos; com o mouse em cima ele fica sólido.

Mapa 3D privado dos equipamentos de fiscalização eletrônica do DF, protegido por login e senha.

## Linguagens

| Parte | Linguagem | Onde fica |
|---|---|---|
| Servidor, login e sessões | **Python** (FastAPI) | `main.py`, `seguranca.py` |
| Leitura e limpeza da planilha | **Python** | `dados.py` (lê o `equipamentos.csv` direto, sem conversão manual) |
| Previsão do tempo (Chuva e Temperatura) | **Python** | `clima.py` (Open-Meteo, grade sobre o DF, cache de 1 h) |
| Fotos aéreas do GDF (2024 e histórico) | **Python** | `gdf.py` (busca na IDE-DF, reprojeta para o mapa, cache) |
| Tráfego aéreo (ADS-B) | **Python** | `aereo.py` (soma adsb.lol + adsb.fi + OpenSky; destaca helicópteros e a frota dos órgãos) |
| Focos de queimada | **Python** | `queimadas.py` (INPE, DF e entorno, 48 h) |
| Trânsito em tempo real | **Python** | `transito.py` (TomTom; a chave fica só no servidor) |
| Waze for Cities | **Python** | `waze.py` (Waze Data Feed; a URL secreta fica só no servidor) |
| Scripts de apoio | **Python** | `criar_usuario.py`, `baixar_cesium.py` |
| Testes | **Python** (pytest) | `test_app.py` |
| Mapa 3D no navegador | JavaScript (CesiumJS) | `index.html`, `app.js`, `app.css` |

O mapa precisa ser JavaScript porque roda dentro do navegador. Toda a lógica do servidor, o controle de acesso e o tratamento dos dados estão em Python.

## Ícones

| Tipo | Ícone | Cor |
|---|---|---|
| Controlador eletrônico (KR) | câmera num **quadrado** | âmbar |
| Redutor eletrônico de velocidade (RE) | placa "60" num **círculo** | azul |
| Não metrológico (FI) | semáforo num **losango** | rosa |

Cada tipo difere ao mesmo tempo pela forma, pela cor e pelo desenho, então dá para distinguir mesmo com daltonismo.

## Publicar no Render (plano gratuito)

1. **Suba este projeto para o GitHub.** Crie um repositório *privado*, clique em "uploading an existing file" → "choose your files" e selecione todos os arquivos desta pasta (Ctrl+A). Todos os arquivos ficam na raiz; não há subpastas.
2. **Gere a lista de usuários.** O jeito mais fácil, sem instalar nada, é abrir `gerador-de-senha.html` no navegador (dois cliques no arquivo). O hash é calculado no próprio navegador. Se preferir, também dá para gerar pelo Python 3.10 ou mais recente:
   ```bash
   python criar_usuario.py narlo
   # digite a senha (mínimo de 10 caracteres). A saída será algo como:
   # narlo:pbkdf2_sha256$600000$...$...
   ```
   Para várias pessoas, rode uma vez para cada uma e junte as linhas com `;`.
3. **Crie o serviço no Render.**
   1. Acesse render.com e entre com a conta do GitHub.
   2. Clique em **New → Blueprint** e escolha o repositório. O Render lê o `render.yaml`.
   3. Quando ele pedir as variáveis, cole a lista do passo 2 em **USERS**. `GOOGLE_MAPS_KEY` e `CESIUM_ION_TOKEN` podem ficar em branco. O `SESSION_SECRET` é gerado sozinho.
   4. Clique em **Apply**. O primeiro deploy leva de 3 a 5 minutos.
4. Abra a URL do tipo `https://geodados-df.onrender.com` e faça login.

> **Sobre o plano gratuito:** o servidor dorme depois de 15 minutos sem acesso, e o primeiro acesso seguinte leva de 30 a 50 segundos. Para ficar sempre ligado, mude para *Starter* em Settings → Instance Type.

## Tarefas comuns

| Quero… | Como |
|---|---|
| Atualizar os dados | Substitua `equipamentos.csv` no GitHub (Add file → Upload files, com o mesmo nome), mantendo as mesmas colunas. O Render publica sozinho em cerca de 2 minutos |
| Incluir ou remover alguém | Gere a linha com `criar_usuario.py` e edite **USERS** em Render → Environment. Quem sair da lista perde o acesso na hora, mesmo que esteja logado |
| Derrubar todas as sessões | Troque o valor de `SESSION_SECRET` no Render |
| Prédios 3D fotorrealistas | Ative a *Map Tiles API* no Google Cloud, crie uma chave restrita ao seu domínio e cole em `GOOGLE_MAPS_KEY` |
| Domínio próprio | Render → Settings → Custom Domains |

## Rodar no seu computador

```bash
python -m venv .venv && source .venv/bin/activate    # no Windows: .venv\Scripts\activate
pip install -r requirements.txt
python baixar_cesium.py                      # baixa o motor 3D (uma vez só)
export SESSION_SECRET=qualquer-texto USERS="$(python criar_usuario.py narlo MinhaSenha123)"
uvicorn main:app --reload --port 8000
# abra http://localhost:8000
pytest -q                                            # roda os testes
```

No Windows (PowerShell), troque o `export` por `$env:SESSION_SECRET="..."` e `$env:USERS="..."`.

## Segurança

- As senhas ficam guardadas como hash PBKDF2-SHA256 com 600 mil iterações.
- A sessão é um cookie assinado, `HttpOnly`, `Secure` e `SameSite=Lax`, válido por 12 horas.
- Sem login, nada é entregue: nem os dados, nem o mapa, nem os scripts.
- Depois de 8 senhas erradas vindas do mesmo IP, o login fica bloqueado por 15 minutos.
- O site não aparece em buscadores e não pode ser embutido em outros sites.

## Sobre os dados

Na leitura do CSV, o servidor faz três ajustes:

- remove caracteres estranhos dos endereços (`ÿ` e o `<` no fim da linha);
- normaliza os nomes das RAs;
- extrai o sentido da via. Os sentidos Norte/Sul, Sul/Norte, Leste/Oeste e Oeste/Leste viram filtro. Os demais, como "Rodoferroviária/Esplanada" ou sem sentido informado, entram em "Outro / via nomeada".

O arquivo original não é alterado. O CSV pode usar `,` ou `;` como separador.

## Previsão do tempo

- **Fonte:** Open-Meteo, gratuita e sem chave para uso não comercial.
- **Cobertura:** o servidor busca uma grade de 96 pontos (cerca de 9 km entre eles) sobre o DF, com previsão hora a hora para 48 h, e guarda o resultado por 1 hora.
- **Camadas:**
  - Chuva, em mm por hora. Só aparece onde há chuva prevista.
  - Temperatura, em °C.
  - Ambas têm liga/desliga, opacidade e legenda próprios.
- **Barra de tempo:** arraste para ver as próximas horas, ou use ▶ para animar.
- **Consulta no mapa:** ao passar o mouse, a barra inferior mostra a temperatura e a chuva naquele ponto. A ficha de cada medidor também mostra a previsão no local.
- **Se a fonte falhar:** o painel mostra a última previsão obtida e avisa que ela está desatualizada.

## Mapas base

A barra no canto superior direito tem estas opções:

| Opção | Fonte | Observação |
|---|---|---|
| Satélite ▾ | Esri World Imagery (padrão) ou **Esri Clarity** | Mundo todo. Ao clicar, aparece a barra "Fonte" para escolher; o Clarity costuma ser mais nítido em muitas áreas |
| **Histórico** | Acervo SEDUH/GDF (IDE-DF) | Seletor de ano: 1964, 1975, 1980, 1986, 1991, 1997, 2007, 2009, 2013, 2015, 2016, 2017, 2018, 2021, 2022, 2023, 2024. A foto de **2024 tem 8 cm por pixel**. Só dentro do DF; fora dele aparece o satélite Esri |
| Híbrido, Ruas, Escuro | Esri | Sem chave |
| OSM | OpenStreetMap | Uso moderado, com atribuição |

- **Como as fotos do GDF chegam ao mapa:** elas passam pelo servidor Python na rota `/gdf/...`, que só responde a quem está logado.
- **Por que passar pelo servidor:** a IDE-DF usa a projeção SIRGAS 2000 / UTM 23S, e o servidor pede a imagem já convertida para o formato do mapa.
- **Cache:** o servidor guarda até 60 MB de blocos em memória, e o navegador guarda cada bloco por 7 dias.
- **Se o GDF ficar lento ou fora do ar:** aparece um aviso, e o satélite Esri continua como fundo.

O botão **3D** só aparece quando há `GOOGLE_MAPS_KEY` ou `CESIUM_ION_TOKEN` configurado no Render.

## Seleção de um medidor

Ao clicar num medidor, no mapa ou na lista, acontecem três coisas:

- **A coordenada exata fica à vista:** o ícone sobe cerca de 30 m, e uma haste luminosa desce até um alvo no chão que marca o ponto. Assim a via fica livre para ver.
- **A câmera faz uma órbita lenta** em volta do ponto, com uma volta a cada ~90 s.
- **Como parar e retomar a órbita:** ela para assim que você clica, arrasta ou usa a roda do mouse no mapa. O botão **Pausar órbita / Girar em volta**, na ficha, pausa e retoma. O botão **Inclinada / De cima** muda o ângulo sem interromper a órbita.

Quem ativou "reduzir movimento" no sistema operacional não vê a órbita automática. O botão continua funcionando.

## Camadas no estilo God's Eye

Ao entrar, o mapa abre em vista inclinada do DF com **todas as camadas desligadas e os grupos recolhidos**. O agrupamento de pontos já vem ligado.

| Camada | Fonte | O que mostra |
|---|---|---|
| **Tráfego aéreo** | adsb.lol + [adsb.fi](https://adsb.fi) + OpenSky, somados (cada rede tem antenas diferentes) | Aeronaves num raio de ~110 km, em 3D na altitude real, com o rumo. Até 15 km da câmera aparecem como **modelos 3D** (helicóptero com rotor girando e avião, arquivos `heli.glb` e `aviao.glb`); mais longe, como ícones. Helicópteros e aeronaves dos órgãos ganham haste até o chão e rastro. Atualiza a cada 10 s |
| **Trânsito em tempo real** | TomTom Traffic Flow | Fluxo nas vias, de verde (livre) a vermelho-escuro (parado). Atualiza a cada 2 min |
| **Waze · ocorrências** | Waze for Cities (Data Feed) | Acidentes, alagamentos, clima na via, perigos (inclui semáforo com defeito e buraco), interdições e obras, polícia e congestionamentos em linha, com liga/desliga por categoria. Atualiza a cada 2 min |
| **Focos de queimada** | INPE, Programa Queimadas | Focos de calor por satélite no DF e entorno nas últimas 48 h, com cor por idade |

### Variáveis novas no Render (Environment → Add Environment Variable)

| Variável | Para quê | Exemplo |
|---|---|---|
| `FROTA` | Aeronaves de órgãos em destaque, com nome e cor. Aceita matrícula ou código hex (ICAO), separados por `;` | `PR-ABC:PMDF;PR-XYZ:CBMDF;PP-DEF:DETRAN;PR-GHI:PRF` |
| `TOMTOM_KEY` | Liga a camada de trânsito. Chave gratuita em developer.tomtom.com | `abc123…` |
| `WAZE_FEED_URL` | Liga a camada do Waze. É a URL do feed no Partner Hub (Toolbox → Waze Data Feed), a que termina em `?format=1` | `https://www.waze.com/row-partnerhub-api/partners/…/waze-feeds/…?format=1` |
| `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` | Opcional. Aumenta o limite da fonte reserva de voos | — |

Cores dos órgãos: **DETRAN** em amarelo marca-texto, **PRF** em bege, **PMDF** em azul, **CBMDF** em vermelho, **PCDF** em verde e os demais em lilás. Helicópteros sem órgão ficam em âmbar; aviões, em branco.

**Limites das fontes:**
- Nem toda aeronave transmite ADS-B, e aeronaves de segurança pública às vezes desligam ou filtram o sinal. A camada mostra só o que as antenas comunitárias captam.
- O plano gratuito da TomTom e os dados do adsb.lol e do OpenSky são para uso não comercial. Confira os termos para uso institucional.

### Como cadastrar uma variável no Render

1. Em dashboard.render.com, abra o serviço **geodados-df**.
2. No menu da esquerda, clique em **Environment**.
3. Clique em **+ Add Environment Variable**, preencha **Key** (ex.: `TOMTOM_KEY`) e **Value** (a chave), sem espaços antes ou depois.
4. Clique em **Save, rebuild, and deploy**. O site reinicia em 1 ou 2 minutos, já com a camada liberada.

Os dados do Waze exigem a atribuição "Dados: Waze", que já aparece no painel. Eles só podem ser usados conforme o acordo de parceria do Waze for Cities; como o site é privado e com login, o uso fica restrito à equipe.
