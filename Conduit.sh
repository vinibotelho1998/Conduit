#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv --python python3 .venv
        uv pip install --python .venv/bin/python -r requirements.txt
    else
        python3 -m venv .venv
        .venv/bin/python -m pip install -r requirements.txt
    fi
elif ! .venv/bin/python -c 'import httpx, yaml, paramiko, cryptography, PySide6' >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python .venv/bin/python -r requirements.txt
    else
        .venv/bin/python -m pip install -r requirements.txt
    fi
fi
exec .venv/bin/python -m conduit "$@"
