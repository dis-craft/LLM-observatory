from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag == "script" and attributes.get("src"):
            self.assets.append(attributes["src"])
        if tag == "link" and attributes.get("href", "").endswith(".css"):
            self.assets.append(attributes["href"])


class StaticContractTests(unittest.TestCase):
    def test_html_ids_are_unique(self):
        parser = AssetParser()
        parser.feed((ROOT / "web" / "index.html").read_text(encoding="utf-8"))
        duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
        self.assertEqual([], duplicates, "Duplicate HTML ids: " + ", ".join(duplicates))

    def test_frontend_assets_exist(self):
        parser = AssetParser()
        parser.feed((ROOT / "web" / "index.html").read_text(encoding="utf-8"))
        for asset in parser.assets:
            self.assertTrue(asset.startswith("/assets/"), "Unexpected local asset path: " + asset)
            self.assertTrue((ROOT / "web" / asset.removeprefix("/assets/")).is_file(), "Missing asset: " + asset)

    def test_backend_registers_core_routes(self):
        import app as server

        routes = {getattr(route, "path", "") for route in server.app.routes}
        self.assertTrue({"/", "/api/health", "/api/models", "/api/telemetry",
                         "/api/experiments/performance", "/api/evaluations/promptfoo",
                         "/api/experiments", "/api/results/import"}.issubset(routes))

    def test_experiment_storage_is_local_and_ignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/", gitignore)
        self.assertIn("SQLite", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
