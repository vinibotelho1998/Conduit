# Novidades do Dbx Wire

## 0.7.0, 5 de setembro de 2026

### SFTP dentro do app

- Aba nova na lateral, **Servidores SFTP**. Duplo clique conecta e abre o navegador na
  area principal, do mesmo jeito que um request abre
- Navegacao com trilha clicavel, entrar e voltar, Backspace pra subir, F5 pra recarregar
  e Ctrl+L pra colar um caminho inteiro. Nome, tamanho, data e permissoes em colunas
- Baixar e enviar varios arquivos de uma vez, com barra de progresso. Download grava num
  `.parcial` e so renomeia no fim, entao transferencia interrompida nao deixa arquivo
  pela metade com o nome do arquivo bom
- Criar pasta, renomear e apagar no servidor, com confirmacao que diz em letras que
  aquilo acontece no servidor e que nao existe lixeira
- Previa de arquivo de texto sem baixar, com o mesmo realce de sintaxe da resposta.
  Arquivo binario recusa a previa em vez de encher a tela de lixo
- **A chave do servidor e conferida.** Servidor desconhecido para a conexao e mostra a
  impressao digital SHA256 pra voce comparar antes de confiar; a chave so entra no
  `known_hosts` do workspace depois disso. Chave que mudou desde a ultima vez avisa em
  vermelho, porque e o sinal classico de alguem no meio do caminho
- Senha e frase da chave privada vao pro mesmo cofre AES-256-GCM das variaveis secretas.
  O arquivo versionado guarda so o contrato: host, porta e usuario
- Nada de rede na thread da interface: servidor lento nao congela mais nada

### Tema novo, sem azul

- A marca virou violeta, e os cinzas deixaram de puxar pro azul. O tema escuro ficou mais
  fundo e neutro, e o claro mais quente
- Metodo, status e realce de sintaxe repaginados. Nenhum deles usa a cor da marca:
  metodo e dado, marca e navegacao, e o olho precisa saber qual dos dois esta olhando
- Todo token que carrega informacao passa de 4.5 de contraste na WCAG, conferido nos dois
  temas

### Trocar de tema agora troca a tela inteira

- Cerca de sessenta pontos do app escreviam a propria folha de estilo com a cor ja
  resolvida dentro. Trocar de tema reescrevia a folha geral e nao encostava em nenhum
  deles: rodape, barra da resposta, cartao de variavel, listas e dialogos continuavam na
  paleta antiga ate reabrir o programa. Todos passaram a se registrar e sao repintados
  junto
- O mesmo valia pros icones desenhados em codigo e pros que usavam cor do tema como valor
  padrao de argumento, que o Python resolve uma vez no import e nunca mais

### Consertos

- **Codigo em Go nao compilava** pra request sem corpo: o `strings` entrava no import sem
  ninguem usar
- **Codigo em PowerShell quebrava** quando a url ou um header tinha aspa simples dentro
- Codigo em C# saia sem `using System;`, entao o `Console.WriteLine` nao compilava
- **Exemplo salvo nunca mostrava o tamanho**: gravava numa chave e era lido de outra
- Salvar uma resposta binaria gravava o texto da tela; agora imagem e pdf saem byte a
  byte, com a extensao certa
- A aba Imagem se fechava sozinha a cada resposta nova
- **Ajuda, Novidades nunca abria no app instalado**: o CHANGELOG.md nao ia junto no
  pacote. Agora vai, e a busca funciona tanto do codigo quanto do executavel
- Envio com certificado cliente piscava um console preto a cada chamada
- A altura entre request, resposta e console era gravada e nunca lida de volta
- Erro nao tratado num app de janela sumia sem deixar rastro. Agora vira uma caixa que
  diz o que foi, um registro em `erros.log` e o programa segue de pe
- O executavel passou a carregar versao, produto e empresa nas propriedades do Windows

### Miudezas

- Botao **Enviar** em portugues, ao lado de Enviando e Salvar
- Dado de exemplo sem nome de pessoa e sem referencia a sistema de terceiro
- Menu Arquivo tinha dois separadores seguidos no mesmo lugar


## 0.6.0, 24 de agosto de 2026

### Exemplo de resposta, como no Postman

- O painel de resposta ganhou o marcador, no canto. Guarda a resposta que esta na tela
  como exemplo daquele request
- **O exemplo aparece embaixo do request na arvore**, com a pilula do status na cor dele,
  do jeito que o Postman mostra. Clicar abre o request e a resposta guardada, sem chamar
  nada. Botao direito renomeia e exclui
- Os exemplos tambem ficam numa aba do proprio request, do lado de Params e Headers, com
  nome, status, quando foi salvo e tamanho
- O exemplo mora dentro do arquivo do request, entao vai junto quando a collection for
  compartilhada. E documentacao, e nao historico
- Antes de gravar, o valor do segredo volta a ser {{nome}} e header de credencial sai
  mascarado, o mesmo tratamento do historico. Salvar exemplo nao pode virar o jeito mais
  facil de mandar token pro git

### Copiar como curl

- Ctrl+Shift+C copia o curl do request aberto, ja com as variaveis resolvidas
- Tambem esta no botao direito do request, na aba e no menu Ir
- Segredo nao vai junto: sai como {{nome}}, porque curl copiado costuma acabar colado em
  ticket e em conversa

### Duplicar e mais opcoes no botao direito

- Botao direito no request agora tem abrir, duplicar, copiar como curl e gerar codigo,
  antes de favoritar e renomear
- Botao direito na aba tem duplicar request e copiar como curl, alem de fechar

### Console

- Barra de baixo nova, no espirito do Postman: lateral, Console, Historico e a pasta do
  workspace a esquerda, situacao a direita
- O console lista o que o app fez nesta sessao, com hora e cor: envio, resposta, erro,
  salvamento. A barra de status mostra uma frase por vez e a anterior se perde, entao
  quando algo dava errado no meio de uma sequencia nao sobrava rastro
- Tem filtro, copiar e limpar. Ctrl+` abre e fecha

### Certificados

- Tela refeita, com as duas coisas separadas como no Postman: a CA em que confiar e a
  identidade cliente por host
- **CA propria**, para servidor de cadeia incompleta ou CA interna. Antes a unica saida
  era desligar a verificacao do request, o que trocava um problema pontual por um buraco
  permanente
- Adicionar virou um formulario na propria tela, e nao tres caixinhas em sequencia. O
  certificado e conferido enquanto voce digita, mostrando dono e validade
- A lista mostra ate quando vale, em verde, amarelo perto de vencer e vermelho vencido

### Variaveis no cartao de espiada

- Da pra editar o valor ali mesmo, com dois cliques. A alteracao volta pro escopo de onde
  o valor veio: ambiente, globais, collection ou pasta
- Secreto continua mascarado, com um olho por linha pra ver quando quiser. Ao editar, o
  campo abre com o valor de verdade, senao salvar por cima gravaria a mascara
- Botao de nova variavel no rodape do cartao

### Tamanho e acabamento

- As acoes do painel de resposta viraram icone: quebrar linha, copiar, salvar em arquivo
  e guardar como exemplo. Quatro palavras seguidas em cima da resposta pareciam menu solto
- A pilula de contagem da aba, tipo o 3 de Headers, deixou de cair em cima do rotulo

- Texto maior no app inteiro, de 9 para 10 pontos, e canto mais redondo em campo, botao,
  menu e cartao
- A setinha do combo era um quadradinho: folha de estilo do Qt nao faz triangulo com
  borda como na web, entao agora a seta e desenhada de verdade
- Aba desligada, como Preview quando a resposta nao tem o que mostrar, aparece apagada em
  vez de igual a uma aba comum

## 0.5.0, 24 de agosto de 2026

### A aba diz o que esta acontecendo

- Cada aba mostra a pilula do metodo na frente do nome, com a mesma cor da arvore
- Ponto laranja quando o request tem alteracao que ainda nao foi salva
- O ponto vira X quando o mouse entra, entao o mesmo canto fecha a aba
- Botao do meio do mouse fecha, e o botao direito abre fechar, fechar as outras, fechar
  as da direita e fechar todas
- Aba de ambiente ganhou marca propria, um circulo, pra nao se confundir com request

### Editar agora tem rascunho, como no Postman

- A aba trabalha numa copia. Editar nao muda o que esta gravado ate voce mandar salvar
- Ctrl+S salva o request aberto, Ctrl+Shift+S salva todos, e o menu Arquivo tem Reverter
  pra jogar a copia fora e voltar pro que esta no disco
- Botao Salvar do lado do Send, apagado enquanto nao ha o que salvar
- Fechar aba com alteracao pergunta antes: salvar, descartar ou cancelar
- O rascunho vai pro disco sozinho, em .dbxwire, que fica fora do git. Fechar o app com
  aba alterada nao perde nada: na proxima abertura ela volta, ainda marcada como nao
  salva
- Enviar usa sempre o que esta na tela, salvo ou nao

### Variavel que nao existe nasce sozinha

- Escrever {{alguma}} que nao existe em nenhum escopo cria a variavel, vazia, no ambiente
  ativo. Espera voce parar de digitar, e so vale pro que voce editou: abrir um request
  que usa variavel de outro ambiente nao escreve nada
- O aviso amarelo de variavel sem valor virou atalho. Preencher leva pra aba do ambiente
  com o cursor ja na linha certa

### A resposta e da aba, nao da janela

- Cada aba guarda o resultado dela. Trocar de request e voltar traz a resposta anterior
  de volta, com corpo, headers, cookies e o que foi enviado
- Antes o painel era um so e trocar de aba limpava tudo, entao comparar duas chamadas
  obrigava a refazer as duas

### Variavel colorida tambem na grade

- {{assim}} agora sai colorida em Params e Headers, e nao so na url e no corpo. Azul
  quando resolve, roxo quando e secreta e vermelho quando nenhum escopo define
- Passar o mouse em cima mostra o cartao com escopo, origem e valor, em qualquer um
  desses lugares
- Valor secreto aparece mascarado, com um mostrar do lado pra ver inteiro quando voce
  quiser. O cartao espera uma folga antes de sumir, senao a mao nunca chegaria ate ele

### Miudezas

- A previa da tela de importar agora e desenhada apagada, porque nao tem o que clicar
  nela e linha que acende prometia uma acao que nao existe

## 0.4.0, 24 de agosto de 2026

### Colar um curl e virar request

- Colar um comando curl na propria barra de url monta o request inteiro. E o gesto mais
  natural: a pessoa copia do Chrome ou de um ticket e cola onde o endereco vai
- Tambem tem Ctrl+Shift+V, com uma tela que mostra o que o comando vai virar antes de
  sobrescrever o que estava la
- Entende as tres conchas, bash com barra invertida, PowerShell com crase e cmd com
  circunflexo, alem do Copy as cURL do Chrome e do Firefox
- Cobre metodo, header, corpo, query, usuario e senha, cookie, timeout, redirect e
  verificacao de TLS. O que nao entende aparece na lista de ignorados, em vez de sumir

### Importar e exportar

- **Postman**, Collection v2.1 e environment, nas duas direcoes
- **Insomnia**, exportacao v4, nas duas direcoes
- **Bruno**, pasta com arquivos .bru, nas duas direcoes
- **OpenAPI 3 e Swagger 2**, em JSON ou YAML, nas duas direcoes
- A deteccao e pelo conteudo e nao pela extensao, porque `.json` serve pra tres formatos
  diferentes e olhar so o nome erraria na maioria das vezes
- A tela de importar mostra a arvore inteira antes de aplicar, e o que veio nao apaga o
  que ja existia: nome repetido ganha numero
- Importar uma spec OpenAPI monta requests utilizaveis: servidor vira `{{baseUrl}}`,
  parametro de caminho vira variavel, e o corpo de exemplo sai do proprio esquema
- No export, variavel secreta sai so com o nome e sem valor. Levar o valor real exige
  marcar uma caixa que avisa em vermelho

## 0.3.0, 24 de agosto de 2026

### Autenticacao

- Aba Auth de verdade, com bearer, basic, api key em header ou query e OAuth2 client
  credentials
- Heranca: o request nasce herdando, usa a auth da pasta mais proxima e, se ela tambem
  herda, sobe pra collection. A aba mostra de quem esta herdando
- Token do OAuth2 fica no cofre e e reaproveitado ate perto de expirar, com folga de 30
  segundos. Existe Esquecer tokens no menu Executar pra forcar um novo
- Auth com campo faltando falha antes de sair da maquina, em vez de mandar um request
  sem credencial e receber 401
- **A credencial final sempre entra no ledger de segredo.** Sem isso o Basic vazava: o
  base64 de usuario e senha nao contem o texto do segredo, entao o redator do historico
  nao tinha o que trocar e gravava algo trivialmente reversivel

### Certificado cliente, mTLS

- Certificado por host, aceitando pfx, p12 e pem, com curinga tipo `*.exemplo.com`
- A senha do arquivo vai pro cofre, nunca pro arquivo versionado
- O pfx e convertido em memoria e escrito num PEM temporario com permissao restrita,
  usado no handshake e apagado logo depois, porque nem httpx nem a ssl do Python
  carregam pfx direto

### Cookies

- Cookie jar por dominio, guardado no workspace e fora do git
- O cookie sai do cliente e nao da resposta: num redirect o Set-Cookie vem na resposta
  intermediaria, e a final nao carrega nada
- Menu Executar mostra o que esta guardado e permite limpar

## 0.2.0, 24 de agosto de 2026

Nome e identidade. O programa passou a se chamar **Dbx Wire**, e o simbolo virou a linha
de pulso: sai reto, dispara no pico e volta ao normal quando a resposta chega. O icone e
desenhado em codigo, sem arquivo de arte no repo, e sai nitido de 16 a 256 pixels.

### Interface

- Arvore desenhada por conta propria: a pilula do metodo encosta na seta, guia vertical
  mostra o que esta dentro do que, e a contagem de filhos vai pra direita
- Sete metodos com sete matizes espacadas no circulo de cor. As antigas colidiam entre si
  e com o azul da propria interface
- Abas com marcador desenhado: pilula com numero em Params, Headers, Headers da resposta
  e Cookies, e ponto em Body e Docs
- Aba de Favoritos, com estrela na arvore e Ctrl+Shift+F
- Ordenar a lista por nome, metodo, mais usados ou executados por ultimo. Ordenar e uma
  forma de olhar, nao mexe na ordem dos arquivos ate voce mandar aplicar
- Paleta de comandos: Ctrl+P pula pra qualquer request, Ctrl+K executa qualquer comando
- Espiada rapida nas variaveis que valem agora, direto da barra do topo

### Variaveis

- Cinco escopos: globais, collection, pasta, ambiente e execucao, nessa precedencia
- Passar o mouse numa variavel mostra valor, escopo de origem e em que outro escopo o
  mesmo nome existe e perdeu
- Ambientes ganharam aba propria na lateral, com editor abrindo em aba

### Requisicao e resposta

- Code generation em nove alvos: curl, PowerShell, Python httpx, Python requests,
  JavaScript fetch, Node axios, Java, C# e Go. Variavel secreta sai como {{nome}} por
  padrao
- Query params e url sincronizados nos dois sentidos
- Painel de resposta com pilula de status, metricas, Pretty, Raw, Preview de HTML e de
  imagem, Headers, Cookies e Enviado, mais busca dentro do corpo

### Historico

- Log durável em JSONL por dia mais indice SQLite, com busca por texto, status e periodo
- Extracao de id de correlacao, incluindo id customizado por host
- Reenvio, detalhe da execucao e copiar como curl
- Valor de variavel secreta e gravado como {{nome}}, nunca em claro

### Armazenamento e seguranca

- **Cofre de segredos.** O valor de variavel marcada como secreta saiu do arquivo
  versionado e foi pro cofre cifrado, com envelope DPAPI amarrado a sua conta Windows e
  AES-256-GCM no conteudo. O arquivo que vai pro git fica so com o nome da variavel e a
  marca de secreta
- **Gerenciador de workspaces.** Renomear, trocar a cor, duplicar, abrir a pasta,
  escolher qual e o ativo e excluir. Excluir oferece tirar so da lista ou mover pra
  lixeira, e nunca apaga de vez

- Um arquivo YAML por item no disco, pronto pra git. Uma edicao toca um arquivo so
- Deteccao de escrita concorrente: se um arquivo mudou por fora, uma copia vai pra
  .dbxwire/conflitos antes de sobrescrever
- Desfazer na arvore com Ctrl+Z, guardando as ultimas 30 mudancas de estrutura
- .gitignore gerado em cada workspace, deixando cofre, historico e certificados de fora

## 0.1.0, 24 de agosto de 2026

Primeira versao que abriu. Janela Qt nativa, workspaces isolados, arvore de collections,
editor de request, envio real e viewer de resposta.
