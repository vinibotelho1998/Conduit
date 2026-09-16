# Conduit

[![Build](https://github.com/vinibotelho1998/Conduit/actions/workflows/release.yml/badge.svg)](https://github.com/vinibotelho1998/Conduit/actions/workflows/release.yml)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6)
![License](https://img.shields.io/badge/license-MIT-green)

Cliente de API de mesa, com navegador SFTP embutido, feito do zero em Python com
PySide6. Nada sai da maquina sem voce mandar: nao existe conta, nao existe nuvem e nao
existe telemetria.

## Instalação

Baixe o **Conduit-Setup.exe** da [última release](https://github.com/vinibotelho1998/Conduit/releases/latest),
execute e pronto. Não precisa de Python nem do repositório.

## Rodar a partir do código-fonte

Precisa de Python 3.13 ou mais novo.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m conduit
```

## Testes

```
.venv\Scripts\python tests\rodar.py
```

Sem framework. As tres suites sobem a janela de verdade num Qt sem tela e conversam com
um servidor SFTP de verdade, aberto numa porta livre da propria maquina. Elas rodam no CI
antes de gerar o instalador.

## O que ele faz

- **Collections, pastas e requests**, com arrastar, ordenar, favoritar e desfazer
- **Cinco escopos de variavel**, globais, collection, pasta, ambiente e execucao, com o
  valor efetivo no cartao do mouse e realce por cor em url, corpo e grade
- **Rascunho por aba**, como no Postman: editar nao muda o que esta gravado ate voce
  salvar, e o rascunho sobrevive ao fechamento do app
- **Exemplos de resposta** salvos dentro do proprio request, com o segredo trocado por
  `{{nome}}` antes de gravar
- **Auth** basic, bearer, api key, OAuth2 client credentials e mTLS por host, com
  heranca de collection e pasta
- **Historico** de execucao com indice, campos de rastreio e expurgo por idade
- **Importar e exportar** Postman v2.1, Insomnia v4, Bruno e OpenAPI 3, nas duas
  direcoes, mais colar curl direto na barra de url
- **Gerar codigo** em nove linguagens, e copiar como curl com Ctrl+Shift+C
- **SFTP** no mesmo workspace: navegar, baixar, enviar, criar pasta, renomear e apagar,
  com previa de arquivo de texto sem precisar baixar. A chave do servidor e conferida
  contra o `known_hosts` do workspace, e servidor novo mostra a impressao digital antes
  de voce confiar
- **Console** com a fita do que o app fez na sessao
- **Tema claro e escuro** e duas densidades, trocados na hora pelo menu Ver

## Onde ficam os dados

Fora do repositorio, em `%USERPROFILE%\Conduit`, um diretorio por workspace. Cada
request e um arquivo YAML, entao o diff do git mostra a mudanca de verdade em vez de uma
linha gigante.

Cada workspace nasce com um `.gitignore` proprio que deixa de fora segredo, historico,
cookie, certificado e rascunho. O que pode ser versionado e compartilhado e o contrato:
nome de variavel, endpoint, header e corpo.

## Segredo

Valor marcado como secreto nunca vai pro arquivo versionado. Ele fica em
`.secrets/vault.dbx`, cifrado em AES-256-GCM, com a chave protegida pela DPAPI do
Windows, entao so a sua conta de usuario nesta maquina abre. A senha do certificado
cliente, o token do OAuth2 e a credencial de cada servidor SFTP moram no mesmo lugar.

O mesmo cuidado vale pra tudo que sai do app: historico, exemplo salvo, codigo gerado e
curl copiado trocam o valor do segredo de volta por `{{nome}}` antes de gravar ou
copiar. A troca e pelo valor e nao pelo nome do header, porque nem todo segredo viaja
num header conhecido, e o basic ainda embaralha usuario e senha em base64.

## Estrutura

```
conduit/core/    modelo, motor de envio, storage, cofre, historico, formatos, sftp
conduit/gui/     janela, arvore, editor, resposta, navegador sftp, dialogos
conduit/gui/tokens.py   cor, espaco, raio e fonte. Toda a interface sai daqui
CHANGELOG.md     o que mudou em cada versao
```

## Licença

Distribuído sob a [licença MIT](LICENSE).
