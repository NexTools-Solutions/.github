#!/usr/bin/env python3
"""Atualiza os números do perfil da org (profile/README.md).

Fonte: https://nextoolsolutions.com/api/public/stats, os mesmos agregados do
ticker "NexTool em números" da home do site (issue #72 do nextool-ecosystem).
O contrato do endpoint está em docs/site/APIs.md daquele repo: as chaves
ambientes, paises, downloads e plugins são obrigatórias aqui.

Reescreve SÓ o miolo dos blocos entre os marcadores

    <!-- nx-stats:pt:start --> ... <!-- nx-stats:pt:end -->
    <!-- nx-stats:en:start --> ... <!-- nx-stats:en:end -->

e mantém o resto do arquivo byte a byte. Só biblioteca padrão.

Falha (exit 1, README intacto) se o endpoint não responder, se faltar chave,
se algum número não for inteiro positivo, se faltar ou sobrar marcador, ou se
o snapshot tiver mais de MAX_IDADE_DIAS: assim a Action também vigia o cron do
portal que alimenta a home. Exit 0 quando atualizou ou quando nada mudou.

Uso:
    profile_stats.py profile/README.md
    profile_stats.py --input stats.json --agora 2026-11-02T10:00:00Z profile/README.md  (offline)
"""

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

URL = "https://nextoolsolutions.com/api/public/stats"
# A Cloudflare do site recusa o User-Agent padrão do urllib (403): manda UA próprio.
USER_AGENT = "NexTool-Profile-Stats/1.0 (+https://github.com/NexTools-Solutions/.github)"
TIMEOUT_S = 20
ESPERAS_S = (5, 15)  # 3 tentativas no total
MAX_IDADE_DIAS = 8
CHAVES = ("ambientes", "paises", "downloads", "plugins")
# Brasil sem horário de verão desde 2019: a data do snapshot é a de Brasília.
BRT = dt.timezone(dt.timedelta(hours=-3), "BRT")
MESES_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SITE = "https://nextoolsolutions.com"

ROTULOS = {
    "pt": {
        "ambientes": "ambientes GLPI que já instalaram o NexTool",
        "paises": "países",
        "downloads": "downloads de módulos",
        "plugins": "módulos no catálogo",
    },
    "en": {
        "ambientes": "GLPI environments that have installed NexTool",
        "paises": "countries",
        "downloads": "module downloads",
        "plugins": "modules in the catalog",
    },
}


class ErroPerfil(Exception):
    """Qualquer motivo para não tocar no README."""


def buscar(url=URL, esperas=ESPERAS_S, timeout=TIMEOUT_S, dormir=time.sleep):
    """GET com UA próprio e novas tentativas; devolve o JSON decodificado."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    ultimo = None
    for tentativa in range(len(esperas) + 1):
        if tentativa:
            dormir(esperas[tentativa - 1])
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            ultimo = f"HTTP {err.code} em {url}"
            if err.code == 403:
                ultimo += " (Cloudflare? conferir regra de WAF para o caminho /api/public/stats)"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
            ultimo = f"{type(err).__name__} em {url}: {err}"
        print(f"tentativa {tentativa + 1} falhou: {ultimo}", file=sys.stderr)
    raise ErroPerfil(ultimo or f"sem resposta de {url}")


def ler_data(valor):
    """ISO 8601 (com Z ou offset) -> datetime com fuso. Sem fuso = UTC."""
    if not isinstance(valor, str) or not valor.strip():
        raise ErroPerfil("updatedAt ausente: sem data não dá para saber se o número é atual")
    texto = valor.strip()
    if texto.endswith(("Z", "z")):
        texto = texto[:-1] + "+00:00"
    try:
        quando = dt.datetime.fromisoformat(texto)
    except ValueError as err:
        raise ErroPerfil(f"updatedAt inválido: {valor!r}") from err
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=dt.timezone.utc)
    return quando


def validar(payload, agora):
    """Confere o corpo do endpoint; devolve (stats, data_do_snapshot)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("stats"), dict):
        raise ErroPerfil("resposta sem o objeto 'stats'")
    stats = {}
    for chave in CHAVES:
        valor = payload["stats"].get(chave)
        # bool é int em Python: True passaria como 1.
        if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
            raise ErroPerfil(f"'{chave}' ausente ou não é inteiro positivo: {valor!r}")
        stats[chave] = valor
    quando = ler_data(payload.get("updatedAt"))
    idade = agora - quando
    if idade > dt.timedelta(days=MAX_IDADE_DIAS):
        raise ErroPerfil(
            f"snapshot de {quando.isoformat()} tem {idade.days} dias (máximo {MAX_IDADE_DIAS}): "
            "o cron do portal que atualiza a home parou?"
        )
    if idade < -dt.timedelta(hours=1):
        raise ErroPerfil(f"updatedAt no futuro: {quando.isoformat()}")
    return stats, quando


def numero(valor, idioma):
    """6588 -> '6.588' (pt) ou '6,588' (en)."""
    texto = f"{valor:,}"
    return texto.replace(",", ".") if idioma == "pt" else texto


def data(quando, idioma):
    """Data do snapshot no fuso de Brasília: '31/10/2026' (pt) ou 'Oct 31, 2026' (en)."""
    local = quando.astimezone(BRT)
    if idioma == "pt":
        return local.strftime("%d/%m/%Y")
    return f"{MESES_EN[local.month - 1]} {local.day}, {local.year}"


def montar_bloco(stats, quando, idioma):
    """Tabela de 4 colunas (números em negrito) + a nota de origem e de honestidade do rótulo."""
    rotulos = ROTULOS[idioma]
    linhas = [
        "| " + " | ".join(f"**{numero(stats[c], idioma)}**" for c in CHAVES) + " |",
        "|" + "|".join(":---:" for _ in CHAVES) + "|",
        "| " + " | ".join(rotulos[c] for c in CHAVES) + " |",
        "",
    ]
    if idioma == "pt":
        linhas.append(
            f"<sub>Atualizado automaticamente toda semana a partir de [nextoolsolutions.com]({SITE}) "
            f"(dados de {data(quando, 'pt')}). Ambientes conta as instalações já feitas, não só as ativas.</sub>"
        )
    else:
        linhas.append(
            f"<sub>Updated automatically every week from [nextoolsolutions.com]({SITE}) "
            f"(data as of {data(quando, 'en')}). Environments counts every installation so far, not only active ones.</sub>"
        )
    return "\n".join(linhas)


def substituir(texto, idioma, bloco):
    """Troca o miolo entre os marcadores do idioma; exige exatamente um par, na ordem."""
    inicio = f"<!-- nx-stats:{idioma}:start -->"
    fim = f"<!-- nx-stats:{idioma}:end -->"
    if texto.count(inicio) != 1 or texto.count(fim) != 1:
        raise ErroPerfil(
            f"o README precisa de exatamente 1 '{inicio}' e 1 '{fim}' "
            f"(achei {texto.count(inicio)} e {texto.count(fim)})"
        )
    a = texto.index(inicio) + len(inicio)
    b = texto.index(fim)
    if b < a:
        raise ErroPerfil(f"'{fim}' aparece antes de '{inicio}'")
    nl = "\r\n" if "\r\n" in texto else "\n"
    # Linha em branco dos dois lados: a tabela não pode colar no comentário HTML do marcador.
    return texto[:a] + nl + nl + bloco.replace("\n", nl) + nl + nl + texto[b:]


def atualizar_texto(texto, stats, quando):
    for idioma in ("pt", "en"):
        texto = substituir(texto, idioma, montar_bloco(stats, quando, idioma))
    return texto


def gravar_atomico(caminho, conteudo):
    pasta = os.path.dirname(os.path.abspath(caminho))
    fd, tmp = tempfile.mkstemp(prefix=".profile-stats-", dir=pasta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(conteudo)
        os.chmod(tmp, os.stat(caminho).st_mode & 0o777)
        os.replace(tmp, caminho)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def saida_github(**pares):
    """Expõe changed/snapshot_date ao passo seguinte do workflow (sem efeito fora do Actions)."""
    destino = os.environ.get("GITHUB_OUTPUT")
    if not destino:
        return
    with open(destino, "a", encoding="utf-8") as fh:
        for chave, valor in pares.items():
            fh.write(f"{chave}={valor}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Atualiza os números do perfil da org a partir do site.")
    ap.add_argument("readme", help="caminho do profile/README.md")
    ap.add_argument("--input", help="JSON local no lugar do endpoint (teste offline)")
    ap.add_argument("--agora", help="instante de referência ISO 8601 (teste offline)")
    ap.add_argument("--url", default=URL, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    try:
        agora = ler_data(args.agora) if args.agora else dt.datetime.now(dt.timezone.utc)
        if args.input:
            with open(args.input, encoding="utf-8") as fh:
                payload = json.load(fh)
        else:
            payload = buscar(args.url)
        stats, quando = validar(payload, agora)
        with open(args.readme, encoding="utf-8", newline="") as fh:
            atual = fh.read()
        novo = atualizar_texto(atual, stats, quando)
    except (ErroPerfil, OSError, ValueError) as err:
        print(f"ERRO: {err} -- README não foi alterado.", file=sys.stderr)
        return 1

    resumo = ", ".join(f"{c}={stats[c]}" for c in CHAVES)
    data_iso = quando.astimezone(BRT).strftime("%Y-%m-%d")
    if novo == atual:
        print(f"Sem mudança ({resumo}; snapshot {data_iso}).")
        saida_github(changed="false", snapshot_date=data_iso)
        return 0
    try:
        gravar_atomico(args.readme, novo)
    except OSError as err:
        print(f"ERRO ao gravar {args.readme}: {err}", file=sys.stderr)
        return 1
    print(f"README atualizado ({resumo}; snapshot {data_iso}).")
    saida_github(changed="true", snapshot_date=data_iso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
