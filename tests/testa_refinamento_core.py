"""Regressoes de HTTP, redacao e persistencia; rede simulada, sem servico externo."""

from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, quote_plus

from comum import sem_tela  # coloca o projeto no caminho ao rodar o arquivo diretamente
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from conduit.core import auth, engine, history, vars, vault

sem_tela()


class CofreEmMemoria:
    def __init__(self):
        self.dados = {}

    def get(self, chave):
        return self.dados.get(chave, "")

    def set(self, chave, valor):
        self.dados[chave] = valor


class HttpTests(unittest.TestCase):
    def test_query_preserva_fragmento_e_repetidos(self):
        for url in ("https://api.test/a#secao?interna", "https://api.test/a?antigo=1#secao?interna"):
            with self.subTest(url=url):
                preparado = engine.prepare({"url": url, "params": [
                    {"key": "q", "value": "a+b /"}, {"key": "q", "value": ""},
                ]}, {})
                self.assertEqual(preparado.url, "https://api.test/a?q=a%2Bb+%2F&q=#secao?interna")

    def test_param_desligado_nao_volta_pela_url(self):
        preparado = engine.prepare({"url": "https://api.test/a?senha=antiga#fim", "params": [
            {"key": "senha", "value": "antiga", "enabled": False},
        ]}, {})
        self.assertEqual(preparado.url, "https://api.test/a#fim")

    def test_auth_query_nao_incorpora_fragmento(self):
        preparado = engine.prepare({"url": "https://api.test/a?q=1#fim", "auth": {
            "type": "apikey", "key": "token", "value": "a+b /", "in": "query",
        }}, {})
        self.assertEqual(preparado.url, "https://api.test/a?q=1&token=a%2Bb+%2F#fim")

    def test_chave_de_param_tambem_resolve_variavel(self):
        preparado = engine.prepare({"url": "https://api.test/a", "params": [
            {"key": "{{nome}}", "value": "1"},
        ]}, {"nome": {"value": "tenant", "secret": False}})
        self.assertEqual(preparado.url, "https://api.test/a?tenant=1")

    def test_timeout_invalido_nao_chega_ao_cliente(self):
        for timeout in (-1, "nan", "inf", "-inf"):
            with self.subTest(timeout=timeout):
                preparado = engine.prepare({"url": "https://api.test", "settings": {"timeout": timeout}}, {})
                self.assertEqual(preparado.timeout, 0.0)

    def test_resposta_preserva_headers_repetidos(self):
        cliente_real = httpx.Client

        def responder(request):
            return httpx.Response(200, headers=[
                ("Set-Cookie", "primeiro=1; Path=/; Expires=Wed, 21 Oct 2030 07:28:00 GMT"),
                ("Set-Cookie", "segundo=2; Path=/"),
                ("X-Item", "a"), ("X-Item", "b"),
            ], text="ok")

        with patch("conduit.core.engine.httpx.Client", side_effect=lambda **kw: cliente_real(
                transport=httpx.MockTransport(responder), **kw)):
            resposta = engine.send(engine.Prepared(url="https://api.test/"))
        self.assertTrue(resposta["ok"], resposta)
        self.assertEqual(len([v for k, v in resposta["headers"] if k == "set-cookie"]), 2)
        self.assertEqual([v for k, v in resposta["headers"] if k == "x-item"], ["a", "b"])


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.config = {"type": "oauth2", "tokenUrl": "https://auth.test/token", "clientId": "cliente"}
        self.cofre = CofreEmMemoria()

    def test_cache_com_tipos_invalidos_e_ignorado(self):
        chave = auth._assinatura(self.config, self.config["tokenUrl"], "cliente", "")
        for valor in ([], None, 42, {"token": "t", "expira": "amanha"},
                      {"token": {"valor": "t"}, "expira": time.time() + 3600},
                      {"token": "t", "expira": float("inf")},
                      {"token": "", "expira": time.time() + 3600}):
            with self.subTest(valor=valor):
                self.cofre.set(chave, json.dumps(valor))
                aplicado = auth.aplicar(self.config, {}, self.cofre, rede=False)
                self.assertIsNone(aplicado.erro)
                self.assertIsNotNone(aplicado.pendente)

    def test_trocar_credencial_invalida_cache(self):
        chave = auth._assinatura(self.config, self.config["tokenUrl"], "cliente", "", "", "senha-antiga")
        self.cofre.set(chave, json.dumps({"token": "token-antigo", "expira": time.time() + 3600}))
        antigo = auth.aplicar(dict(self.config, clientSecret="senha-antiga"), {}, self.cofre, rede=False)
        novo = auth.aplicar(dict(self.config, clientSecret="senha-nova"), {}, self.cofre, rede=False)
        self.assertEqual(antigo.headers["Authorization"], "Bearer token-antigo")
        self.assertIsNotNone(novo.pendente)

    def test_redirect_nao_reenvia_credencial(self):
        pedidos = []
        cliente_real = httpx.Client

        def responder(request):
            pedidos.append(request)
            if request.url.host == "auth.test":
                return httpx.Response(307, headers={"Location": "https://outro.test/token"})
            return httpx.Response(200, json={"access_token": "vazou"})

        with patch("conduit.core.auth.httpx.Client", side_effect=lambda **kw: cliente_real(
                transport=httpx.MockTransport(responder), **kw)):
            aplicado = auth.aplicar(dict(self.config, clientSecret="segredo-do-cliente"), {})
        self.assertEqual(len(pedidos), 1)
        self.assertIn("redirecionou", aplicado.erro)

    def test_token_invalido_e_expiracao_zero(self):
        cliente_real = httpx.Client
        for payload in ({"access_token": ["invalido"]}, {"access_token": "ok", "expires_in": 0}):
            with self.subTest(payload=payload), patch("conduit.core.auth.httpx.Client", side_effect=lambda **kw:
                    cliente_real(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)), **kw)):
                aplicado = auth.aplicar(self.config, {}, self.cofre)
                if isinstance(payload["access_token"], list):
                    self.assertIn("access_token", aplicado.erro)
                else:
                    self.assertEqual(aplicado.headers["Authorization"], "Bearer ok")
                self.assertEqual(self.cofre.dados, {})

    def test_erro_do_provedor_redige_segredo_literal(self):
        cliente_real = httpx.Client
        segredo = "credencial+com/espaco e acento-é"
        with patch("conduit.core.auth.httpx.Client", side_effect=lambda **kw: cliente_real(
                transport=httpx.MockTransport(lambda req: httpx.Response(401, text="credencial " + quote_plus(segredo))), **kw)):
            aplicado = auth.aplicar(dict(self.config, clientSecret=segredo), {})
        self.assertIn("{{auth.clientSecret}}", aplicado.erro)
        self.assertNotIn(quote_plus(segredo), aplicado.erro)


class RedacaoTests(unittest.TestCase):
    def test_formas_codificadas_nao_escapam(self):
        segredo = 's+en/ha com "aspas" e ç'
        formas = [segredo, quote(segredo, safe=""), quote_plus(segredo, safe=""),
                  json.dumps(segredo, ensure_ascii=True)[1:-1], json.dumps(segredo, ensure_ascii=False)[1:-1]]
        for forma in formas:
            with self.subTest(forma=forma):
                self.assertEqual(vars.redact("valor=" + forma, [("credencial", segredo)]), "valor={{credencial}}")

    def test_substituicao_nao_corrompe_outro_placeholder(self):
        self.assertEqual(vars.redact("abcdefgh / token", [("token", "abcdefgh"), ("outro", "token")]),
                         "{{token}} / {{outro}}")

    def test_historico_redige_template_erro_trace_e_indice(self):
        segredo = "credencial+com/espaco e acento-é"
        preparado = engine.Prepared(url="https://api.test/?token=" + quote_plus(segredo),
                                     headers={"X-Request-Id": segredo}, secrets=[("credencial", segredo)])
        with tempfile.TemporaryDirectory(prefix="conduit-redacao-") as pasta:
            hist = history.History(pasta)
            try:
                identificador = hist.record(request={"url": "https://api.test/?token=" + segredo}, prepared=preparado,
                                             result={"ok": False, "error": "falhou " + segredo,
                                                     "reason": segredo, "url": preparado.url})
                entrada = hist.get(identificador)
                indice = hist.resumo(identificador)
                self.assertNotIn(segredo, json.dumps(entrada, ensure_ascii=False))
                self.assertNotIn(quote_plus(segredo), json.dumps(entrada, ensure_ascii=False))
                self.assertEqual(entrada["trace"]["x-request-id"], "{{credencial}}")
                self.assertEqual(indice["error"], "falhou {{credencial}}")
                self.assertEqual(indice["trace"], "x-request-id={{credencial}}")
            finally:
                hist.close()


class PersistenciaTests(unittest.TestCase):
    def test_reconstrucao_ignora_linha_sem_campos_obrigatorios(self):
        with tempfile.TemporaryDirectory(prefix="conduit-historico-") as pasta:
            diretorio = Path(pasta) / "history"
            diretorio.mkdir()
            entradas = [{}, {"id": "sem-data"}, {"id": [], "ts": "2026-10-02T12:00:00"},
                        {"id": "valida", "ts": "2026-10-02T12:00:00", "request": {}, "response": {"ok": True}}]
            (diretorio / "2026-10-02.jsonl").write_text("\n".join(json.dumps(e) for e in entradas) + "\n", encoding="utf-8")
            hist = history.History(pasta)
            try:
                self.assertEqual(hist.stats()["total"], 1)
                self.assertEqual(hist.get("valida")["id"], "valida")
            finally:
                hist.close()

    def test_cofre_com_conteudo_invalido_falha_de_forma_controlada(self):
        with tempfile.TemporaryDirectory(prefix="conduit-cofre-") as pasta:
            caminho = Path(pasta) / ".secrets" / vault.ARQUIVO
            caminho.parent.mkdir()
            chave = AESGCM.generate_key(bit_length=256)
            nonce = b"012345678901"
            corpo = AESGCM(chave).encrypt(nonce, b'["nao e mapa"]', vault.ENTROPIA)
            envelope = {"schemaVersion": 1, "provider": "dpapi", "wrappedKey": base64.b64encode(chave).decode(),
                        "nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(corpo).decode()}
            caminho.write_text(json.dumps(envelope), encoding="utf-8")
            with patch.object(vault, "desproteger", side_effect=lambda dados: dados):
                cofre = vault.Vault(pasta)
                self.assertEqual(cofre.get("qualquer"), "")
                self.assertIn("mapa de segredos", cofre.erro)

    def test_falha_de_gravacao_preserva_cofre_original(self):
        with tempfile.TemporaryDirectory(prefix="conduit-cofre-") as pasta:
            caminho = Path(pasta) / ".secrets" / vault.ARQUIVO
            caminho.parent.mkdir()
            caminho.write_text("cofre anterior ilegivel", encoding="utf-8")
            cofre = vault.Vault(pasta)
            self.assertIsNotNone(cofre.erro)
            with patch.object(vault, "proteger", side_effect=lambda dados: dados), \
                    patch.object(Path, "replace", side_effect=OSError("disco indisponivel")):
                with self.assertRaises(OSError):
                    cofre.set("novo", "valor")
            self.assertEqual(caminho.read_text(encoding="utf-8"), "cofre anterior ilegivel")
            self.assertFalse(caminho.with_suffix(".tmp").exists())
            self.assertEqual(len(list(caminho.parent.glob("vault.dbx.ilegivel-*"))), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
