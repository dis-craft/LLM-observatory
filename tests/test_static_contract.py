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
                         "/api/experiments/performance", "/api/evaluations/native", "/api/evaluations/promptfoo",
                         "/api/experiments", "/api/results/import"}.issubset(routes))

    def test_single_dashboard_workflow_is_wired(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        for required in [
            'id="model-choices"', 'id="baseline-model"', 'id="workload-profile"',
            'value="balanced"', 'value="prefill"', 'value="decode"',
            'value="retrieval"', 'value="long"', 'id="performance-repetitions"',
            'id="performance-warmups"', 'id="sample-interval"',
            'id="start-performance"', 'id="start-quality"',
            'id="performance-results"', 'id="quality-results"', 'id="history-rows"',
        ]:
            self.assertIn(required, html)
        self.assertIn('/api/experiments/performance', javascript)
        self.assertIn('/api/evaluations/native', javascript)
        self.assertIn('baseline_model: state.baseline', javascript)
        self.assertIn('change_percent_vs_baseline', javascript)
        self.assertIn('latency_stddev_s', javascript)
        self.assertIn('gpu_energy_j_median_estimate', javascript)

    def test_every_literal_javascript_id_selector_exists_in_html(self):
        import re

        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        html_ids = set(re.findall(r'\bid="([^"]+)"', html))
        selector_ids = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', javascript))
        self.assertFalse(selector_ids - html_ids, "JS selectors missing in HTML: " + ", ".join(sorted(selector_ids - html_ids)))
    def test_reference_baseline_cannot_drift_from_selected_models(self):
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('state.selected.add(state.baseline)', javascript)
        self.assertIn('model.name === state.baseline && !check.checked', javascript)
        self.assertIn('state.models.some((model) => model.name === state.baseline)', javascript)
        self.assertIn('without subtracting idle power', html)
    def test_benchmark_protocol_documents_workload_basis(self):
        protocol = (ROOT / "docs" / "benchmark-protocol.md").read_text(encoding="utf-8")
        self.assertIn("Reference", protocol)
        self.assertIn("Prompt processing", protocol)
        self.assertIn("Generation", protocol)
        self.assertIn("Baseline change", protocol)
        self.assertIn("What this tool does not establish", protocol)

    def test_experiment_storage_is_local_and_ignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/", gitignore)
        self.assertIn("SQLite", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
