from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from capacity_engine import DEFAULT_CONFIGS


class AppStateTests(unittest.TestCase):
    def test_analysis_results_survive_configuration_detail_reruns(self):
        configs = [
            name
            for name in DEFAULT_CONFIGS
            if name.endswith("OI") and "2-Level Box Shelf | OI" in name
        ][:2]
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        app.multiselect[0].set_value(configs)
        app.text_area[0].set_value(
            "Carton Name\tLength\tWidth\tHeight\tFlap State\n"
            "Sample\t5\t5\t5\tFlaps Up"
        )
        app.run()

        self.assertEqual(app.metric[0].label, "Cartons to analyze")
        self.assertEqual(app.metric[0].value, "1")

        run_button = next(
            button for button in app.button if button.label == "Run capacity analysis"
        )
        run_button.click().run()
        self.assertEqual(set(app.session_state["analysis_results"]), set(configs))

        app.selectbox[0].set_value(configs[1]).run()

        self.assertEqual(app.selectbox[0].value, configs[1])
        self.assertEqual(set(app.session_state["analysis_results"]), set(configs))
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
