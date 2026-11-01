#!/usr/bin/env python3
"""Confere os links externos do profile/README.md (issue #72 do nextool-ecosystem).

Extrai os links markdown `](https://...)` e os `href="https://..."`, sem
duplicata, e testa cada um: HEAD com o mesmo User-Agent do gerador, seguindo
redirect; se o servidor não aceitar HEAD (403, 405, 429, 501), tenta GET. Aceita
200-399. Pula os domínios que recusam robô por política (LinkedIn devolve 999).

Sai 1 se houver link quebrado, listando cada um. Só biblioteca padrão.
Roda DEPOIS do commit dos números no workflow: instabilidade de site de
terceiros não pode segurar a atualização do perfil.
"""

import re
import sys
import time
import urllib.error
import urllib.request

USER_AGENT = "NexTool-Profile-Stats/1.0 (+https://github.com/NexTools-Solutions/.github)"
TIMEOUT_S = 15
PULAR = ("linkedin.com",)
REFAZER_COM_GET = {403, 405, 429, 501}

_MD = re.compile(r"\]\((https?://[^)\s]+)\)")
_HREF = re.compile(r"""href=["'](https?://[^"'\s]+)["']""")


def extrair_links(texto):
    """Links http(s) na ordem em que aparecem, sem repetir."""
    vistos = []
    for padrao in (_MD, _HREF):
        for m in padrao.finditer(texto):
            url = m.group(1)
            if url not in vistos:
                vistos.append(url)
    return vistos


def pular(url):
    host = re.sub(r"^https?://", "", url).split("/", 1)[0].split(":", 1)[0].lower()
    return any(host == d or host.endswith("." + d) for d in PULAR)


def status_de(url, metodo, timeout=TIMEOUT_S):
    req = urllib.request.Request(url, method=metodo, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code


def conferir(url, abrir=status_de, dormir=time.sleep):
    """Devolve None se o link está bom, ou o motivo da falha."""
    motivo = None
    for tentativa in range(2):
        if tentativa:
            dormir(3)
        try:
            codigo = abrir(url, "HEAD")
            if codigo in REFAZER_COM_GET:
                codigo = abrir(url, "GET")
            if 200 <= codigo < 400:
                return None
            motivo = f"HTTP {codigo}"
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            motivo = f"{type(err).__name__}: {err}"
    return motivo


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("uso: check_links.py profile/README.md", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        links = extrair_links(fh.read())
    quebrados = []
    for url in links:
        if pular(url):
            print(f"pulado  {url}")
            continue
        motivo = conferir(url)
        print(f"{'ok     ' if motivo is None else 'QUEBRADO'} {url}{'' if motivo is None else '  (' + motivo + ')'}")
        if motivo is not None:
            quebrados.append((url, motivo))
    if quebrados:
        print(f"\n{len(quebrados)} link(s) quebrado(s) em {argv[0]}:", file=sys.stderr)
        for url, motivo in quebrados:
            print(f"  {url}: {motivo}", file=sys.stderr)
        return 1
    print(f"\n{len(links)} link(s) conferido(s), nenhum quebrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
