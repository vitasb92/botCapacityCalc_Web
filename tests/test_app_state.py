import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from capacity_engine import DEFAULT_CONFIGS, analyze_cartons
from config_store import load_configs, save_config


class AppStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "app.sqlite3"
        environment = patch.dict(os.environ, {"BOT_CONFIG_DB": str(self.database)})
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_configuration_tab_adds_a_bot_for_analysis(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertIn("Manage configurations", [tab.label for tab in app.tabs])
        next(
            item for item in app.text_input if item.label == "Configuration name"
        ).set_value("New Bot")
        next(
            item for item in app.selectbox if item.key == "add-config-family-selection"
        ).set_value("Create a new family...")
        next(
            item for item in app.text_input if item.key == "add-config-new-family"
        ).set_value("New Fleet")
        next(button for button in app.button if button.label == "Add configuration").click().run()

        self.assertFalse(app.exception)
        new_bot_label = "New Bot | New Fleet"
        self.assertIn(new_bot_label, app.multiselect[0].options)
        self.assertIn(new_bot_label, load_configs(self.database))

        next(
            item for item in app.selectbox if item.label == "Configuration to edit"
        ).set_value(new_bot_label).run()
        next(
            item
            for item in app.text_input
            if item.key == f"edit-config-name-{new_bot_label}"
        ).set_value("Renamed Bot")
        next(
            item
            for item in app.selectbox
            if item.key == f"edit-config-{new_bot_label}-family-selection"
        ).set_value("OII")
        next(
            item
            for item in app.number_input
            if item.key == f"edit-config-{new_bot_label}-width"
        ).set_value(22)
        next(button for button in app.button if button.label == "Save changes").click().run()

        self.assertFalse(app.exception)
        renamed_label = "Renamed Bot | OII"
        self.assertEqual(load_configs(self.database)[renamed_label]["width"], 22)
        self.assertIn(renamed_label, app.multiselect[0].options)

        next(
            item for item in app.selectbox if item.label == "Configuration to edit"
        ).set_value(renamed_label).run()
        next(
            item
            for item in app.checkbox
            if item.key == f"confirm-delete-{renamed_label}"
        ).set_value(True).run()
        next(
            button for button in app.button if button.label == "Delete configuration"
        ).click().run()

        self.assertFalse(app.exception)
        self.assertNotIn(renamed_label, load_configs(self.database))
        self.assertNotIn(renamed_label, app.multiselect[0].options)
        configuration_table = next(
            dataframe
            for dataframe in app.dataframe
            if "Configuration Name" in dataframe.value.columns
        )
        self.assertIn("Bot Family", configuration_table.value.columns)
        pairs = list(
            zip(
                configuration_table.value["Bot Family"],
                configuration_table.value["Configuration Name"],
            )
        )
        self.assertEqual(
            pairs,
            sorted(pairs, key=lambda pair: (pair[0].casefold(), pair[1].casefold())),
        )

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
        self.assertEqual(app.selectbox[1].label, "Carton fit")
        self.assertGreaterEqual(len(app.get("plotly_chart")), 2)
        fit_chart = json.loads(app.get("plotly_chart")[1].proto.spec)
        fit_trace_names = [trace.get("name") for trace in fit_chart["data"]]
        self.assertIn("Carton body", fit_trace_names)
        self.assertIn("Flaps", fit_trace_names)
        self.assertEqual(app.session_state["analysis_visual_schema_version"], 1)
        self.assertFalse(app.exception)

    def test_optimization_filters_by_explicit_family_not_name_suffix(self):
        source_config = next(
            config for name, config in DEFAULT_CONFIGS.items() if name != "Manual Input"
        )
        save_config("Plain Shelf Name", "FutureFleet", source_config, db_path=self.database)

        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        next(
            item for item in app.checkbox
            if item.label == "Find the best configuration across bot families"
        ).set_value(True).run()
        family_selector = next(
            item for item in app.multiselect if item.label == "Bot families to compare"
        )
        self.assertIn("FutureFleet", family_selector.options)
        next(
            item for item in app.multiselect if item.label == "Bot families to compare"
        ).set_value(["FutureFleet"])
        app.text_area[0].set_value(
            "Carton Name\tLength\tWidth\tHeight\nSample\t5\t5\t5"
        )
        app.run()
        next(button for button in app.button if button.label == "Run capacity analysis").click().run()

        self.assertEqual(list(app.session_state["analysis_results"]), ["Plain Shelf Name | FutureFleet"])
        self.assertFalse(app.exception)

    def test_run_replaces_results_and_visuals_and_resets_selectors(self):
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
            "First\t5\t5\t5\tFlaps Up\n"
            "Second\t4\t4\t4\tFlaps Up"
        )
        app.run()
        next(button for button in app.button if button.label == "Run capacity analysis").click().run()

        self.assertEqual(len(app.session_state["analysis_results"][configs[0]]), 2)
        app.selectbox[0].set_value(configs[1])
        app.selectbox[1].set_value(1).run()

        app.multiselect[0].set_value([configs[0]])
        app.text_area[0].set_value(
            "Carton Name\tLength\tWidth\tHeight\tFlap State\n"
            "Replacement\t7\t4\t4\tFlaps Down"
        )
        app.run()
        next(button for button in app.button if button.label == "Run capacity analysis").click().run()

        results = app.session_state["analysis_results"]
        visual = app.session_state["analysis_visuals"][configs[0]][0]
        self.assertEqual(list(results), [configs[0]])
        self.assertEqual(len(results[configs[0]]), 1)
        self.assertEqual(results[configs[0]].loc[0, "Length"], 7)
        self.assertEqual(app.session_state["analysis_summary"].iloc[0]["Total Cartons Analyzed"], 1)
        self.assertEqual(visual["flap_state"], "folded")
        self.assertEqual(app.selectbox[0].value, configs[0])
        self.assertEqual(app.selectbox[1].value, 0)
        self.assertEqual(app.session_state["analysis_visual_schema_version"], 1)
        self.assertFalse(app.exception)

    def test_stale_visualization_session_keeps_results_and_prompts_for_rerun(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": False,
            "max_density": False,
            "workflow": "p2p",
            "overhang": None,
            "manual_config": {
                "width": 10,
                "depth": 10,
                "hgt": 10,
                "shelves": 1,
                "buffer": 0,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            },
        }
        results = analyze_cartons(
            pd.DataFrame({"Length": [5], "Width": [5], "Height": [5]}),
            ["Manual Input"],
            options,
        )
        app.session_state["analysis_results"] = results
        app.session_state["analysis_summary"] = pd.DataFrame(
            [
                {
                    "Configuration": "Manual Input",
                    "Fitted Cartons": 1,
                    "Total Cartons Analyzed": 1,
                    "Sum of Weighted Average": 1.0,
                }
            ]
        )
        app.session_state["analysis_visuals"] = {
            "Manual Input": [
                {
                    "carton_dimensions": (5, 5, 5),
                    "shelves": [{"width": 10, "depth": 10, "height": 10, "placements": []}],
                }
            ]
        }
        app.session_state["analysis_is_optimized"] = False
        app.session_state["analysis_visual_schema_version"] = 0
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(list(app.session_state["analysis_results"]), ["Manual Input"])
        self.assertIn("older 3D visualization format", app.info[0].value)
        self.assertEqual(len(app.get("plotly_chart")), 1)
        self.assertGreaterEqual(len(app.dataframe), 2)


if __name__ == "__main__":
    unittest.main()
