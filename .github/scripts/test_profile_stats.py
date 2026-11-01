"""Testes do gerador do perfil e do conferidor de links (sem rede).

Rodar na raiz do repo:
    python3 -I -m unittest discover -s .github/scripts -p 'test_*.py' -v
"""

import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import check_links
import profile_stats as ps

AGORA = dt.datetime(2026, 11, 2, 10, 23, tzinfo=dt.timezone.utc)
PAYLOAD = {
    "updatedAt": "2026-10-31T08:00:07.136Z",
    "stats": {"ambientes": 786, "paises": 56, "downloads": 6588, "plugins": 40},
}
README = (
    "# NexTool Solutions\n\nIntro.\n\n"
    "<!-- nx-stats:pt:start -->\nvelho pt\n<!-- nx-stats:pt:end -->\n\n"
    "## Produtos\n\n- item\n\n## English\n\n"
    "<!-- nx-stats:en:start -->\n<!-- nx-stats:en:end -->\n\nFim com acento: ção.\n"
)


def com_stats(**trocas):
    corpo = json.loads(json.dumps(PAYLOAD))
    corpo["stats"].update(trocas)
    return corpo


class TestFormatacao(unittest.TestCase):
    def test_numero_pt_e_en(self):
        self.assertEqual(ps.numero(6588, "pt"), "6.588")
        self.assertEqual(ps.numero(6588, "en"), "6,588")
        self.assertEqual(ps.numero(1234567, "pt"), "1.234.567")
        self.assertEqual(ps.numero(40, "pt"), "40")

    def test_data_no_fuso_de_brasilia(self):
        quando = ps.ler_data("2026-10-31T08:00:07.136Z")
        self.assertEqual(ps.data(quando, "pt"), "31/10/2026")
        self.assertEqual(ps.data(quando, "en"), "Oct 31, 2026")
        # 01:30 UTC ainda é o dia anterior em Brasília.
        self.assertEqual(ps.data(ps.ler_data("2026-11-01T01:30:00Z"), "pt"), "31/10/2026")

    def test_ler_data_sem_fuso_vira_utc(self):
        self.assertEqual(ps.ler_data("2026-10-31T08:00:00").tzinfo, dt.timezone.utc)

    def test_bloco_pt_tem_numeros_rotulo_honesto_e_data(self):
        stats, quando = ps.validar(PAYLOAD, AGORA)
        bloco = ps.montar_bloco(stats, quando, "pt")
        self.assertIn("| **786** | **56** | **6.588** | **40** |", bloco)
        self.assertIn("ambientes GLPI que já instalaram o NexTool", bloco)
        self.assertIn("dados de 31/10/2026", bloco)
        self.assertIn("não só as ativas", bloco)
        self.assertNotIn("ativos em 30", bloco)

    def test_bloco_en(self):
        stats, quando = ps.validar(PAYLOAD, AGORA)
        bloco = ps.montar_bloco(stats, quando, "en")
        self.assertIn("| **786** | **56** | **6,588** | **40** |", bloco)
        self.assertIn("GLPI environments that have installed NexTool", bloco)
        self.assertIn("data as of Oct 31, 2026", bloco)


class TestValidacao(unittest.TestCase):
    def test_payload_valido(self):
        stats, quando = ps.validar(PAYLOAD, AGORA)
        self.assertEqual(stats, PAYLOAD["stats"])
        self.assertEqual(quando.year, 2026)

    def test_chave_faltando(self):
        corpo = com_stats()
        del corpo["stats"]["plugins"]
        with self.assertRaises(ps.ErroPerfil):
            ps.validar(corpo, AGORA)

    def test_zero_negativo_string_float_bool(self):
        for ruim in (0, -1, "786", 786.0, True, None):
            with self.subTest(valor=ruim), self.assertRaises(ps.ErroPerfil):
                ps.validar(com_stats(ambientes=ruim), AGORA)

    def test_sem_stats_ou_nao_objeto(self):
        for corpo in ({}, {"stats": []}, [], None, {"error": "STATS_UNAVAILABLE"}):
            with self.subTest(corpo=corpo), self.assertRaises(ps.ErroPerfil):
                ps.validar(corpo, AGORA)

    def test_snapshot_velho(self):
        velho = dict(PAYLOAD, updatedAt="2026-10-24T08:00:00Z")  # 9 dias antes de AGORA
        with self.assertRaises(ps.ErroPerfil):
            ps.validar(velho, AGORA)
        no_limite = dict(PAYLOAD, updatedAt="2026-10-25T10:24:00Z")  # pouco menos de 8 dias
        ps.validar(no_limite, AGORA)

    def test_snapshot_no_futuro_ou_sem_data(self):
        for quando in ("2026-11-05T00:00:00Z", None, "", "ontem"):
            with self.subTest(updatedAt=quando), self.assertRaises(ps.ErroPerfil):
                ps.validar(dict(PAYLOAD, updatedAt=quando), AGORA)


class TestSubstituicao(unittest.TestCase):
    def test_preserva_o_resto_byte_a_byte(self):
        stats, quando = ps.validar(PAYLOAD, AGORA)
        novo = ps.atualizar_texto(README, stats, quando)
        ini_pt, fim_pt = "<!-- nx-stats:pt:start -->", "<!-- nx-stats:pt:end -->"
        ini_en, fim_en = "<!-- nx-stats:en:start -->", "<!-- nx-stats:en:end -->"
        # Antes do primeiro marcador, entre os blocos e depois do último: idênticos.
        self.assertEqual(novo.split(ini_pt)[0], README.split(ini_pt)[0])
        self.assertEqual(novo.split(fim_pt)[1].split(ini_en)[0], README.split(fim_pt)[1].split(ini_en)[0])
        self.assertEqual(novo.split(fim_en)[1], README.split(fim_en)[1])
        self.assertNotIn("velho pt", novo)
        self.assertIn("**6.588**", novo)
        self.assertIn("**6,588**", novo)

    def test_idempotente(self):
        stats, quando = ps.validar(PAYLOAD, AGORA)
        uma = ps.atualizar_texto(README, stats, quando)
        self.assertEqual(ps.atualizar_texto(uma, stats, quando), uma)

    def test_preserva_crlf(self):
        stats, quando = ps.validar(PAYLOAD, AGORA)
        novo = ps.atualizar_texto(README.replace("\n", "\r\n"), stats, quando)
        self.assertNotIn("\n", novo.replace("\r\n", ""))

    def test_marcador_ausente_ou_duplicado(self):
        bloco = "x"
        with self.assertRaises(ps.ErroPerfil):
            ps.substituir(README.replace("<!-- nx-stats:pt:end -->", ""), "pt", bloco)
        with self.assertRaises(ps.ErroPerfil):
            ps.substituir(README + "<!-- nx-stats:pt:start -->\n", "pt", bloco)
        with self.assertRaises(ps.ErroPerfil):
            ps.substituir("<!-- nx-stats:pt:end --> <!-- nx-stats:pt:start -->", "pt", bloco)
        with self.assertRaises(ps.ErroPerfil):
            ps.substituir("sem marcador nenhum", "en", bloco)


class TestMain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.readme = os.path.join(self.dir, "README.md")
        with open(self.readme, "w", encoding="utf-8", newline="") as fh:
            fh.write(README)
        self.payload = os.path.join(self.dir, "stats.json")
        self._gravar_payload(PAYLOAD)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def _gravar_payload(self, corpo):
        with open(self.payload, "w", encoding="utf-8") as fh:
            json.dump(corpo, fh)

    def _rodar(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            codigo = ps.main(["--input", self.payload, "--agora", "2026-11-02T10:23:00Z", self.readme])
        return codigo, out.getvalue(), err.getvalue()

    def _ler(self):
        with open(self.readme, encoding="utf-8", newline="") as fh:
            return fh.read()

    def test_atualiza_e_depois_nao_regrava(self):
        codigo, out, _ = self._rodar()
        self.assertEqual(codigo, 0)
        self.assertIn("README atualizado", out)
        self.assertIn("**786**", self._ler())
        # Mesmo payload: o arquivo não é regravado (mtime antigo intacto).
        os.utime(self.readme, ns=(1_000_000_000, 1_000_000_000))
        codigo, out, _ = self._rodar()
        self.assertEqual(codigo, 0)
        self.assertIn("Sem mudança", out)
        self.assertEqual(os.stat(self.readme).st_mtime_ns, 1_000_000_000)

    def test_payload_invalido_nao_toca_no_readme(self):
        self._gravar_payload(com_stats(downloads=0))
        codigo, _, err = self._rodar()
        self.assertEqual(codigo, 1)
        self.assertIn("README não foi alterado", err)
        self.assertEqual(self._ler(), README)

    def test_marcador_quebrado_nao_toca_no_readme(self):
        quebrado = README.replace("<!-- nx-stats:en:end -->", "")
        with open(self.readme, "w", encoding="utf-8", newline="") as fh:
            fh.write(quebrado)
        codigo, _, _ = self._rodar()
        self.assertEqual(codigo, 1)
        self.assertEqual(self._ler(), quebrado)

    def test_saida_para_o_workflow(self):
        destino = os.path.join(self.dir, "github_output")
        antigo = os.environ.get("GITHUB_OUTPUT")
        os.environ["GITHUB_OUTPUT"] = destino
        try:
            self._rodar()
        finally:
            if antigo is None:
                del os.environ["GITHUB_OUTPUT"]
            else:
                os.environ["GITHUB_OUTPUT"] = antigo
        with open(destino, encoding="utf-8") as fh:
            saida = fh.read()
        self.assertIn("changed=true", saida)
        self.assertIn("snapshot_date=2026-10-31", saida)


class TestBuscar(unittest.TestCase):
    def test_desiste_depois_das_tentativas_sem_dormir_de_verdade(self):
        esperas = []
        with redirect_stderr(io.StringIO()), self.assertRaises(ps.ErroPerfil):
            ps.buscar("http://127.0.0.1:9/api/public/stats", esperas=(5, 15), timeout=1, dormir=esperas.append)
        self.assertEqual(esperas, [5, 15])

    def test_user_agent_proprio(self):
        self.assertTrue(ps.USER_AGENT.startswith("NexTool-Profile-Stats/"))
        self.assertNotIn("urllib", ps.USER_AGENT.lower())


class TestCheckLinks(unittest.TestCase):
    def test_extrai_sem_duplicata_e_na_ordem(self):
        texto = (
            "[a](https://nextoolsolutions.com) [b](https://nextoolsolutions.com/blog) "
            "[a de novo](https://nextoolsolutions.com) <a href=\"https://github.com/x\">x</a> "
            "[rel](/caminho) [mail](mailto:a@b)"
        )
        self.assertEqual(
            check_links.extrair_links(texto),
            ["https://nextoolsolutions.com", "https://nextoolsolutions.com/blog", "https://github.com/x"],
        )

    def test_pula_linkedin(self):
        self.assertTrue(check_links.pular("https://www.linkedin.com/company/nextool-solutions/"))
        self.assertFalse(check_links.pular("https://nextoolsolutions.com/"))
        self.assertFalse(check_links.pular("https://notlinkedin.com/"))

    def test_head_recusado_tenta_get(self):
        chamadas = []

        def abrir(url, metodo):
            chamadas.append(metodo)
            return 405 if metodo == "HEAD" else 200

        self.assertIsNone(check_links.conferir("https://x.test/", abrir=abrir, dormir=lambda s: None))
        self.assertEqual(chamadas, ["HEAD", "GET"])

    def test_404_e_quebrado(self):
        motivo = check_links.conferir("https://x.test/", abrir=lambda u, m: 404, dormir=lambda s: None)
        self.assertEqual(motivo, "HTTP 404")

    def test_readme_do_perfil_tem_links_esperados(self):
        caminho = os.path.join(os.path.dirname(__file__), "..", "..", "profile", "README.md")
        if not os.path.exists(caminho):
            self.skipTest("profile/README.md fora do lugar esperado")
        with open(caminho, encoding="utf-8") as fh:
            texto = fh.read()
        links = check_links.extrair_links(texto)
        self.assertTrue(links)
        for proibido in ("plugins.glpi-project.org", "nextoolsolutions.com/docs", "ContainerAPI",
                         "SLA Charts", "Ticket Ratings", "Custom Login"):
            self.assertNotIn(proibido, texto)
        for idioma in ("pt", "en"):
            self.assertEqual(texto.count(f"<!-- nx-stats:{idioma}:start -->"), 1)
            self.assertEqual(texto.count(f"<!-- nx-stats:{idioma}:end -->"), 1)


if __name__ == "__main__":
    unittest.main()
