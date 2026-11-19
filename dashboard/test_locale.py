"""Language parity, offline assets and localized errors from the real HTTP handler."""

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
from desk_text import Message, catalog
from test_apis import serving

ROOT = Path(__file__).resolve().parent


class Keys(HTMLParser):
    def __init__(self):
        super().__init__()
        self.keys = set()

    def handle_starttag(self, tag, attrs):
        self.keys.update(value for attr, value in attrs if attr.startswith("data-i18n"))


class LanguageTests(unittest.TestCase):
    def test_catalog_covers_both_languages_and_format_arguments(self):
        available = catalog()
        for key, pair in available.items():
            with self.subTest(key=key):
                self.assertEqual(set(pair), {"fa", "en"})
                self.assertTrue(all(value.strip() for value in pair.values()))
                self.assertEqual(
                    sorted(re.findall(r"\{\w+\}", pair["fa"])), sorted(re.findall(r"\{\w+\}", pair["en"]))
                )
        page = Keys()
        page.feed((ROOT / "index.html").read_text(encoding="utf-8"))
        refs = set(page.keys)
        for file in ("desk.js", "app.py", "team_desk.py", "herdr_worker.py", "paperclip_client.py"):
            refs.update(
                re.findall(
                    r"""["']((?:app|msg|template|step|state|field|err|dialog|team|work|side|nav|plan)\.[\w]+)["']""",
                    (ROOT / file).read_text(encoding="utf-8"),
                )
            )
        self.assertFalse(refs - available.keys(), refs - available.keys())

    def test_assets_and_language_negotiation_do_not_need_a_board(self):
        with (
            serving(app.DashboardHandler) as server,
            patch.object(app, "COMPANY_ID", ""),
            patch.object(app, "paperclip_json", return_value=[]),
        ):
            base = f"http://127.0.0.1:{server.server_port}"
            for route, mime in [
                ("/strings.json", "application/json"),
                ("/i18n.js", "application/javascript"),
                ("/brand/desk-mark.png", "image/png"),
            ]:
                with urlopen(base + route, timeout=3) as r:
                    self.assertEqual(r.headers.get_content_type(), mime)
                    self.assertTrue(r.read())
            for header, lang, phrase in [
                ("fa-IR", "fa", "یک شرکت بسازید"),
                ("en", "en", "Create a company"),
                ("fr, en-US;q=0.4, fa;q=0.8", "fa", "یک شرکت بسازید"),
                ("fa;q=0, fr", "en", "Create a company"),
            ]:
                with self.assertRaises(HTTPError) as cm:
                    urlopen(Request(base + "/api/agents", headers={"Accept-Language": header}), timeout=3)
                with cm.exception as r:
                    self.assertEqual(r.code, 409)
                    self.assertEqual(r.headers["Content-Language"], lang)
                    data = json.load(r)
                    self.assertIn(phrase, data["error"])
                    self.assertEqual(data["i18n"]["key"], "err.createCompany")
                    self.assertEqual(data["i18n"]["vars"], {"url": app.PAPERCLIP_URL})

    def test_nested_partial_failure_keeps_issue_identity_and_reason(self):
        detail = Message("err.partial", id="ATL-21", count=1, total=2, reason=Message("err.unreachable"))
        self.assertIn("1 of 2", str(detail))
        self.assertIn("ATL-21", detail.render("fa"))
        self.assertIn("۱ از ۲", detail.render("fa"))
        self.assertIn("اتصال به Paperclip", detail.render("fa"))
        self.assertEqual(detail.wire()["vars"]["reason"]["key"], "err.unreachable")
