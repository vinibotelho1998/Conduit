# Terceiros

O Conduit é distribuído sob a [licença MIT](LICENSE). Este arquivo lista o que ele
usa de terceiros, cada um sob a própria licença.

Nada de terceiros é versionado neste repositório.

## Dependências

| Biblioteca | Licença | Para quê |
|---|---|---|
| PySide6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | interface |
| httpx | BSD-3-Clause | motor de envio das requisições |
| PyYAML | MIT | storage de cada request em arquivo |
| cryptography | Apache-2.0 OR BSD-3-Clause | AES-256-GCM do cofre e o mTLS |
| paramiko | LGPL-2.1 | navegador SFTP |

Lido dos metadados dos pacotes instalados, não de memória.

## Componentes sob LGPL

**PySide6** é usado aqui sob a **LGPL v3**, e **paramiko** sob a **LGPL 2.1**. Os
dois entram como biblioteca, sem modificação, e podem ser substituídos por outra
versão compatível. O Qt que vem no instalador é dinâmico pelo mesmo motivo.
https://www.qt.io/licensing

## Formatos que ele importa e exporta

O Conduit lê e escreve Postman v2.1, Insomnia v4, Bruno e OpenAPI 3. São formatos de
arquivo, implementados aqui a partir das especificações públicas de cada um. Nenhum
código desses projetos é usado, e não há vínculo nem endosso de nenhum deles.
