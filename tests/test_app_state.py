import json
import math
import os
from html import escape as escape_html
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from brand_palette import ACCENT_ORANGE, ACCENT_YELLOW, LOCUS_BLUE, NEUTRAL_DARK
from capacity_engine import DEFAULT_CONFIGS, analyze_cartons
from config_store import (
    load_aisle_mappings,
    load_aisle_settings,
    load_configs,
    save_aisle_mappings,
    save_config,
)


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
        self.assertIn("Manage Bot Configurations", [tab.label for tab in app.tabs])
        self.assertIn("Aisle Width Configuration", [tab.label for tab in app.tabs])
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

    def test_results_workbench_renders_cards_and_switchable_carton_fit(self):
        config_labels = [
            name for name in DEFAULT_CONFIGS if name.endswith("| OI")
        ][:2]
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        app.multiselect[0].set_value(config_labels)
        app.text_area[0].set_value(
            "Carton Name\tLength\tWidth\tHeight\n"
            "Short\t5\t5\t5\n"
            "Tall\t8\t8\t8"
        )
        app.run()
        next(
            button for button in app.button if button.label == "Run capacity analysis"
        ).click().run()

        self.assertFalse(app.exception)
        tab_labels = [tab.label for tab in app.tabs]
        self.assertNotIn("Layout Previews", tab_labels)
        for label in ("Overview", "Carton Fit", "Aisle Planning", "Downloads"):
            self.assertIn(label, tab_labels)

        summary = app.session_state["analysis_summary"]
        kpi_cards = [
            item.value
            for item in app.markdown
            if "overview-kpi-card" in item.value
        ]
        self.assertEqual(len(kpi_cards), 4)
        for card in kpi_cards:
            self.assertIn("height: 132px;", card)
            self.assertIn(f"border-top: 4px solid {LOCUS_BLUE};", card)

        carton_card = next(card for card in kpi_cards if "Cartons analyzed" in card)
        self.assertIn(">2</div>", carton_card)
        configuration_card = next(
            card for card in kpi_cards if "Top configuration" in card
        )
        self.assertIn(
            escape_html(summary.iloc[0]["Configuration"]),
            configuration_card,
        )
        self.assertIn("font-size: 1rem;", configuration_card)
        compared_card = next(
            card for card in kpi_cards if "Configurations compared" in card
        )
        self.assertIn(">2</div>", compared_card)
        weighted_average_card = next(
            card for card in kpi_cards if "Top weighted average" in card
        )
        self.assertIn(
            f">{summary.iloc[0]['Sum of Weighted Average']:.2f}</div>",
            weighted_average_card,
        )

        summary_chart = json.loads(app.get("plotly_chart")[0].proto.spec)
        self.assertEqual(summary_chart["data"][0]["marker"]["color"], LOCUS_BLUE)

        carton_selector = next(
            item for item in app.selectbox if item.key == "carton_fit_selector"
        )
        self.assertEqual(
            carton_selector.options,
            ["Carton 1 - Short", "Carton 2 - Tall"],
        )
        carton_selector.set_value("Carton 2 - Tall").run()
        self.assertEqual(
            next(
                item for item in app.selectbox if item.key == "carton_fit_selector"
            ).value,
            1,
        )
        self.assertFalse(app.exception)

    def test_analysis_results_survive_configuration_detail_reruns(self):
        configs = [
            name
            for name in DEFAULT_CONFIGS
            if name.endswith("OI") and "2-Level Box Shelf | OI" in name
        ][:2]
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        app.multiselect[0].set_value(configs)
        next(
            item for item in app.text_input
            if item.label.startswith("Global overhang override")
        ).set_value("3")
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
        self.assertIn("Core shelf", fit_trace_names)
        self.assertIn("Overhang extension", fit_trace_names)
        fit_traces = {trace["name"]: trace for trace in fit_chart["data"]}
        self.assertEqual(fit_traces["Carton body"]["color"], ACCENT_ORANGE)
        self.assertEqual(fit_traces["Flaps"]["color"], ACCENT_YELLOW)
        self.assertEqual(fit_traces["Core shelf"]["color"], NEUTRAL_DARK)
        self.assertEqual(fit_traces["Overhang extension"]["color"], LOCUS_BLUE)
        shelf_visual = app.session_state["analysis_visuals"][configs[1]][0]["shelves"][0]
        self.assertEqual(
            shelf_visual["core_depth"],
            load_configs(self.database)[configs[1]]["depth"],
        )
        self.assertEqual(shelf_visual["overhang_depth"], 3)
        self.assertEqual(app.session_state["analysis_visual_schema_version"], 2)
        self.assertFalse(app.exception)

    def test_aisle_recommendations_cover_all_cartons_for_mapped_configuration(self):
        config_label = next(
            name
            for name in DEFAULT_CONFIGS
            if name.endswith("| OI") and "2-Level Box Shelf | OI" in name
        )
        config_name, bot_family = config_label.rsplit(" | ", 1)
        save_aisle_mappings(
            [
                {
                    "name": config_name,
                    "bot_family": bot_family,
                    "aisle_profile": "Origin I | 20.25in/508mm Hinged Boxshelf",
                    "robot_width_mm": 508,
                }
            ],
            db_path=self.database,
        )
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        app.multiselect[0].set_value([config_label])
        app.text_area[0].set_value(
            "Carton Name\tLength\tWidth\tHeight\n"
            "Small\t5\t5\t5\n"
            "Large\t20\t20\t10"
        )
        app.run()
        next(
            button for button in app.button if button.label == "Run capacity analysis"
        ).click().run()

        self.assertFalse(app.exception)
        aisle_tables = [
            item.value
            for item in app.dataframe
            if {"Traffic pattern", "Optimal limiting carton"}.issubset(
                item.value.columns
            )
        ]
        summary = next(
            table
            for table in aisle_tables
            if "Carton 2 - Large" in table["Optimal limiting carton"].values
        )
        two_way = summary.loc[summary["Traffic pattern"] == "Pass (2-Way)"].iloc[0]
        self.assertEqual(two_way["Minimum limiting carton"], "Carton 2 - Large")
        self.assertEqual(two_way["Optimal limiting carton"], "Carton 2 - Large")
        carton_table = next(
            item.value
            for item in app.dataframe
            if "Largest optimal aisle need" in item.value.columns
        )
        large_carton = carton_table.loc[
            carton_table["Carton"] == "Carton 2 - Large"
        ].iloc[0]
        self.assertIn("Pass (2-Way)", large_carton["Largest optimal aisle need"])
        self.assertIn("Aisle width recommendations", [item.value for item in app.subheader])

        next(toggle for toggle in app.toggle if toggle.label == "Metric units (mm / kg)").set_value(
            True
        ).run()
        metric_summary = next(
            item.value
            for item in app.dataframe
            if {"Traffic pattern", "Optimal limiting carton"}.issubset(
                item.value.columns
            )
            and "Carton 2 - Large" in item.value["Optimal limiting carton"].values
        )
        metric_two_way = metric_summary.loc[
            metric_summary["Traffic pattern"] == "Pass (2-Way)"
        ].iloc[0]
        large_carton_radius = math.sqrt(
            (508 / 2) ** 2 + (abs(139.41502 - 195) + 508 / 2) ** 2
        )
        expected_width_mm = 2 * (max(334.0, large_carton_radius) + 75) * 2
        self.assertEqual(
            metric_two_way["Minimum aisle width"],
            f"{expected_width_mm:.1f} mm",
        )
        download_buttons = app.get("download_button")
        self.assertIn(
            "Download aisle requirements PNG",
            [item.label for item in download_buttons],
        )

    def test_manage_configurations_shows_aisle_mapping_editor(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        self.assertFalse(app.exception)

        editors = [item.value for item in app.data_editor]
        self.assertTrue(any("Aisle Profile" in editor.columns for editor in editors))
        mapping_editor = next(
            editor for editor in editors if "Aisle Profile" in editor.columns
        )
        self.assertIn("Robot width (mm)", mapping_editor.columns)

    def test_aisle_configuration_page_saves_existing_profile_requirements(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertIn("Aisle Width Configuration", [tab.label for tab in app.tabs])

        editor = next(
            item
            for item in app.data_editor
            if "Robot type" in item.value.columns
        )
        edited_table = editor.value.copy()
        row_index = edited_table.index[
            edited_table["Aisle Profile"] == "Vector | Shelf"
        ][0]
        edited_table.at[row_index, "1-way minimum (mm)"] = 1400.0
        edited_table.at[row_index, "1-way optimal (mm)"] = 1600.0
        app.session_state["aisle-requirements-profile-editor"] = {
            "edited_rows": {
                row_index: {
                    "1-way minimum (mm)": 1400.0,
                    "1-way optimal (mm)": 1600.0,
                }
            },
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        next(
            button
            for button in app.button
            if button.label == "Save aisle-width requirements"
        ).click().run()

        self.assertFalse(app.exception)
        settings = load_aisle_settings(self.database)
        self.assertEqual(
            settings["profiles"]["Vector | Shelf"]["minimum_mm"][0],
            1400,
        )
        self.assertEqual(
            settings["profiles"]["Vector | Shelf"]["optimal_mm"][0],
            1600,
        )

    def test_manage_configurations_saves_edited_aisle_mapping(self):
        config_label = next(
            name
            for name in DEFAULT_CONFIGS
            if name.endswith("| OI") and "2-Level Box Shelf | OI" in name
        )
        config_name, bot_family = config_label.rsplit(" | ", 1)
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        editor = next(
            item
            for item in app.data_editor
            if "Aisle Profile" in item.value.columns
        )
        edited_table = editor.value.copy()
        row_index = edited_table.index[
            (edited_table["Configuration Name"] == config_name)
            & (edited_table["Bot Family"] == bot_family)
        ][0]
        edited_table.at[row_index, "Aisle Profile"] = (
            "Origin I | 20.25in/508mm Hinged Boxshelf"
        )
        edited_table.at[row_index, "Robot width (mm)"] = 508.0
        app.session_state["aisle-mapping-editor"] = {
            "edited_rows": {
                row_index: {
                    "Aisle Profile": edited_table.at[row_index, "Aisle Profile"],
                    "Robot width (mm)": edited_table.at[
                        row_index, "Robot width (mm)"
                    ],
                }
            },
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        next(
            button for button in app.button if button.label == "Save aisle mappings"
        ).click().run()

        self.assertFalse(app.exception)
        saved = load_aisle_mappings(self.database)
        self.assertEqual(
            saved[config_label]["aisle_profile"],
            "Origin I | 20.25in/508mm Hinged Boxshelf",
        )

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
        self.assertEqual(app.session_state["analysis_visual_schema_version"], 2)
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
        self.assertTrue(
            any("older 3D visualization format" in item.value for item in app.info)
        )
        chart_specs = [
            json.loads(chart.proto.spec)
            for chart in app.get("plotly_chart")
        ]
        chart_titles = [
            spec.get("layout", {}).get("title", {}).get("text")
            for spec in chart_specs
        ]
        self.assertEqual(chart_titles.count("Weighted average cartons per bot"), 1)
        self.assertEqual(
            chart_titles.count("Preview weighted average cartons per bot"),
            0,
        )
        self.assertGreaterEqual(len(app.dataframe), 2)


if __name__ == "__main__":
    unittest.main()
