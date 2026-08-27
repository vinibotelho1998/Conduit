"""Historico de execucoes: durável, rastreavel e sem segredo em claro.

Desenho:

  history/2026-08-24.jsonl   log completo do dia, uma linha por execucao, fonte da verdade
  history/index.db           indice SQLite, so pra buscar rapido e apontar de volta pro log

Por que os dois. O JSONL nunca corrompe, aceita append concorrente, e da pra ler no
terminal com grep quando o app nem estiver aberto. O SQLite responde busca por texto,
por status, por periodo e por id de correlacao sem varrer arquivo. Se o indice sumir,
ele e reconstruido a partir do log, que e o unico dado que importa.

Regra de segredo, secao 5.4 do PLANO.md: o que entra aqui ja passou pelo redator. O
valor real de variavel secreta e trocado de volta pelo {{nome}} antes de gravar.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .vars import redact

# Headers que costumam carregar id de correlacao. Sao extraidos pra coluna propria,
# entao da pra achar uma execucao pelo id que o outro lado registrou.
TRACE_KEYS = {
    "x-request-id",
    "x-correlation-id",
    "x-correlationid",
    "x-transaction-id",
    "x-trace-id",
    "x-amzn-trace-id",
    "x-b3-traceid",
    "traceparent",
    "request-id",
}

# Nomes sempre mascarados, segunda camada de defesa alem do ledger.
MASK_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "apikey",
    "api-key",
    "client_secret",
    "client-secret",
    "password",
    "senha",
    "access_token",
    "refresh_token",
}

MAX_REQ_BODY = 64 * 1024
MAX_RESP_BODY = 256 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id           TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    ts_epoch     REAL NOT NULL,
    day          TEXT NOT NULL,
    offset       INTEGER NOT NULL,
    request_id   TEXT,
    request_path TEXT,
    name         TEXT,
    env          TEXT,
    method       TEXT,
    url          TEXT,
    status       INTEGER,
    ok           INTEGER,
    error        TEXT,
    elapsed_ms   INTEGER,
    size_bytes   INTEGER,
    trace        TEXT
);
CREATE INDEX IF NOT EXISTS ix_entries_ts ON entries (ts_epoch DESC);
CREATE INDEX IF NOT EXISTS ix_entries_request ON entries (request_id, ts_epoch DESC);
CREATE INDEX IF NOT EXISTS ix_entries_status ON entries (status);
CREATE INDEX IF NOT EXISTS ix_entries_trace ON entries (trace);
"""


def new_entry_id(when: float | None = None) -> str:
    """Id curto, ordenavel por tempo e facil de ditar em conversa."""
    stamp = int((when or time.time()) * 1000)
    return f"{stamp:x}{secrets.token_hex(2)}"


def short_id(entry_id: str) -> str:
    return entry_id[-6:]


@dataclass
class Query:
    text: str = ""
    status_class: str = ""       # "", "2", "3", "4", "5", "erro"
    method: str = ""
    request_id: str = ""
    request_path: str = ""       # alternativa ao id, ver comentario em query
    since_days: int = 0          # 0 quer dizer sem limite
    limit: int = 300


class History:
    def __init__(self, workspace_path: str | Path):
        self.dir = Path(workspace_path) / "history"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "index.db"
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ banco

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --------------------------------------------------------------- gravacao

    def record(
        self,
        *,
        request: dict,
        prepared,
        result: dict,
        request_path: str = "",
        env_name: str = "",
    ) -> str:
        """Grava uma execucao e devolve o id. O ledger de segredo vem no prepared."""
        now = time.time()
        entry_id = new_entry_id(now)
        moment = datetime.fromtimestamp(now)
        day = moment.strftime("%Y-%m-%d")
        ledger = list(getattr(prepared, "secrets", []) or [])

        req_headers = _clean_headers(getattr(prepared, "headers", {}) or {}, ledger)
        req_body, req_trunc = _clip(redact(getattr(prepared, "body", None) or "", ledger), MAX_REQ_BODY)
        resp_headers = _clean_headers_list(result.get("headers") or [], ledger)
        resp_body, resp_trunc = _clip(redact(result.get("body") or "", ledger), MAX_RESP_BODY)

        trace = _extract_trace(getattr(prepared, "headers", {}) or {}, result.get("headers") or [])

        entry = {
            "id": entry_id,
            "ts": moment.isoformat(timespec="seconds"),
            "requestId": request.get("id"),
            "requestPath": request_path,
            "name": request.get("name"),
            "env": env_name,
            "request": {
                "method": getattr(prepared, "method", request.get("method") or "GET"),
                "url": redact(getattr(prepared, "url", "") or "", ledger),
                "urlTemplate": request.get("url") or "",
                "headers": req_headers,
                "body": req_body,
                "bodyTruncated": req_trunc,
                "missingVars": list(getattr(prepared, "missing", []) or []),
            },
            "response": {
                "ok": bool(result.get("ok")),
                "status": result.get("status"),
                "reason": result.get("reason"),
                "headers": resp_headers,
                "body": resp_body,
                "bodyTruncated": resp_trunc,
                "sizeBytes": result.get("sizeBytes"),
                "elapsedMs": result.get("elapsedMs"),
                "finalUrl": redact(result.get("url") or "", ledger),
                "error": result.get("error"),
            },
            "trace": trace,
        }

        log_path = self.dir / f"{day}.jsonl"
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with log_path.open("ab") as handle:
            offset = handle.tell()
            handle.write(line.encode("utf-8"))

        self.conn.execute(
            "INSERT OR REPLACE INTO entries (id, ts, ts_epoch, day, offset, request_id,"
            " request_path, name, env, method, url, status, ok, error, elapsed_ms,"
            " size_bytes, trace) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                entry["ts"],
                now,
                day,
                offset,
                entry["requestId"],
                request_path,
                entry["name"],
                env_name,
                entry["request"]["method"],
                entry["request"]["url"],
                result.get("status"),
                1 if result.get("ok") else 0,
                result.get("error"),
                result.get("elapsedMs"),
                result.get("sizeBytes"),
                " ".join(f"{k}={v}" for k, v in trace.items()),
            ),
        )
        self.conn.commit()
        return entry_id

    # ----------------------------------------------------------------- leitura

    def query(self, spec: Query) -> list[sqlite3.Row]:
        sql = "SELECT * FROM entries WHERE 1=1"
        args: list = []

        if spec.text:
            like = f"%{spec.text.strip()}%"
            sql += " AND (url LIKE ? OR name LIKE ? OR request_path LIKE ? OR trace LIKE ? OR id LIKE ?)"
            args += [like, like, like, like, like]
        if spec.status_class == "erro":
            sql += " AND ok = 0"
        elif spec.status_class:
            sql += " AND status >= ? AND status < ?"
            base = int(spec.status_class) * 100
            args += [base, base + 100]
        if spec.method:
            sql += " AND method = ?"
            args.append(spec.method)
        if spec.request_id or spec.request_path:
            # Casa por id ou por caminho. So por id quebra quando o request e recriado,
            # reimportado ou vem de outra maquina, porque o id muda e o historico antigo
            # some da vista mesmo sendo do mesmo endpoint.
            condicoes = []
            if spec.request_id:
                condicoes.append("request_id = ?")
                args.append(spec.request_id)
            if spec.request_path:
                condicoes.append("request_path = ?")
                args.append(spec.request_path)
            sql += " AND (" + " OR ".join(condicoes) + ")"
        if spec.since_days:
            sql += " AND ts_epoch >= ?"
            args.append(time.time() - spec.since_days * 86400)

        sql += " ORDER BY ts_epoch DESC LIMIT ?"
        args.append(spec.limit)
        return list(self.conn.execute(sql, args))

    def get(self, entry_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT day, offset FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        path = self.dir / f"{row['day']}.jsonl"
        if not path.exists():
            return None
        with path.open("rb") as handle:
            handle.seek(row["offset"])
            line = handle.readline()
        try:
            return json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def uso_por_request(self) -> dict:
        """Quantas vezes e quando cada request rodou, pra ordenar a arvore por uso.

        Chaveia por id e tambem por caminho, porque id muda quando o request e recriado
        ou reimportado, e ai o historico antigo ficaria orfao.
        """
        mapa: dict[str, tuple[int, float]] = {}
        linhas = self.conn.execute(
            "SELECT request_id, request_path, COUNT(*) vezes, MAX(ts_epoch) ultima"
            " FROM entries GROUP BY request_id, request_path"
        )
        for linha in linhas:
            for chave in (linha["request_id"], linha["request_path"]):
                if not chave:
                    continue
                vezes, ultima = mapa.get(chave, (0, 0.0))
                mapa[chave] = (vezes + linha["vezes"], max(ultima, linha["ultima"] or 0.0))
        return mapa

    def stats(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) total, SUM(ok=0) falhas, MIN(ts) primeira FROM entries"
        ).fetchone()
        return {
            "total": row["total"] or 0,
            "falhas": row["falhas"] or 0,
            "primeira": row["primeira"],
        }

    # ---------------------------------------------------------------- limpeza

    def purge(self, body_days: int = 7, meta_days: int = 90) -> dict:
        """Corpo some rapido, metadado fica mais tempo. Ver secao 5 do PLANO.md."""
        removed_files = 0
        limit_day = (datetime.now() - timedelta(days=body_days)).strftime("%Y-%m-%d")
        for path in self.dir.glob("*.jsonl"):
            if path.stem < limit_day:
                path.unlink(missing_ok=True)
                removed_files += 1

        cutoff = time.time() - meta_days * 86400
        cursor = self.conn.execute("DELETE FROM entries WHERE ts_epoch < ?", (cutoff,))
        self.conn.commit()
        return {"arquivos": removed_files, "registros": cursor.rowcount}

    def clear(self) -> None:
        for path in self.dir.glob("*.jsonl"):
            path.unlink(missing_ok=True)
        self.conn.execute("DELETE FROM entries")
        self.conn.commit()

    def delete(self, entry_id: str) -> None:
        self.conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self.conn.commit()

    def rebuild_index(self) -> int:
        """Reconstroi o indice a partir dos JSONL. O log e a fonte da verdade."""
        self.conn.execute("DELETE FROM entries")
        total = 0
        for path in sorted(self.dir.glob("*.jsonl")):
            day = path.stem
            with path.open("rb") as handle:
                while True:
                    offset = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    try:
                        entry = json.loads(line.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    response = entry.get("response") or {}
                    request = entry.get("request") or {}
                    try:
                        epoch = datetime.fromisoformat(entry["ts"]).timestamp()
                    except (KeyError, ValueError):
                        epoch = 0.0
                    self.conn.execute(
                        "INSERT OR REPLACE INTO entries (id, ts, ts_epoch, day, offset,"
                        " request_id, request_path, name, env, method, url, status, ok,"
                        " error, elapsed_ms, size_bytes, trace) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            entry.get("id"),
                            entry.get("ts"),
                            epoch,
                            day,
                            offset,
                            entry.get("requestId"),
                            entry.get("requestPath"),
                            entry.get("name"),
                            entry.get("env"),
                            request.get("method"),
                            request.get("url"),
                            response.get("status"),
                            1 if response.get("ok") else 0,
                            response.get("error"),
                            response.get("elapsedMs"),
                            response.get("sizeBytes"),
                            " ".join(f"{k}={v}" for k, v in (entry.get("trace") or {}).items()),
                        ),
                    )
                    total += 1
        self.conn.commit()
        return total


# ------------------------------------------------------------------ auxiliares


def _mask(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-2:]}"


def _clean_headers(headers: dict, ledger) -> list[list[str]]:
    out = []
    for key, value in headers.items():
        text = redact(str(value), ledger)
        if key.lower() in MASK_KEYS:
            text = _mask(text) if "{{" not in text else text
        out.append([key, text])
    return out


def _clean_headers_list(headers: list, ledger) -> list[list[str]]:
    out = []
    for pair in headers:
        key, value = pair[0], pair[1]
        text = redact(str(value), ledger)
        if key.lower() in MASK_KEYS:
            text = _mask(text) if "{{" not in text else text
        out.append([key, text])
    return out


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if text is None:
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _extract_trace(req_headers: dict, resp_headers: list) -> dict:
    trace: dict[str, str] = {}
    for key, value in (req_headers or {}).items():
        if key.lower() in TRACE_KEYS:
            trace[key.lower()] = str(value)
    for pair in resp_headers or []:
        key = str(pair[0]).lower()
        if key in TRACE_KEYS:
            trace[key] = str(pair[1])
    return trace
