from io import BytesIO
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

from capacity_engine import (
    analyze_cartons,
    analyze_cartons_with_placements,
    calculate_packing,
    make_workbook,
    normalize_cartons,
)


class PackingTests(unittest.TestCase):
    def test_picking_workflow_limits_depth_to_one(self):
        p2p_count, _, _ = calculate_packing(
            20, 10, 10, (5, 5, 5), stackable=True, allow_3d=False, workflow="p2p"
        )
        pick_put_count, _, _ = calculate_packing(
            20, 10, 10, (5, 5, 5), stackable=True, allow_3d=False, workflow="pick_put"
        )

        self.assertEqual(p2p_count, 16)
        self.assertEqual(pick_put_count, 8)

    def test_decimal_exact_fits_are_not_undercounted_by_float_rounding(self):
        for max_density in (False, True):
            with self.subTest(max_density=max_density):
                count, _, _ = calculate_packing(
                    0.3,
                    0.2,
                    0.3,
                    (0.1, 0.1, 0.1),
                    stackable=True,
                    allow_3d=False,
                    max_density=max_density,
                )
                self.assertEqual(count, 18)

        count, _, _ = calculate_packing(
            0.29999,
            0.2,
            0.3,
            (0.1, 0.1, 0.1),
            stackable=True,
            allow_3d=False,
        )
        self.assertEqual(count, 12)

    def test_normalize_cartons_maps_dimensions_and_rejects_nonpositive_values(self):
        cartons = normalize_cartons(
            pd.DataFrame({"Width (X)": [10], "Depth (Y)": [8], "Height": [4]})
        )
        self.assertEqual(list(cartons[["Length", "Width", "Height"]].iloc[0]), [10, 8, 4])

        with self.assertRaisesRegex(ValueError, "positive Length"):
            normalize_cartons(pd.DataFrame({"Length": [0], "Width": [8], "Height": [4]}))

    def test_normalize_cartons_trims_outer_whitespace_but_rejects_embedded_spaces(self):
        cartons = normalize_cartons(
            pd.DataFrame(
                {
                    "Length": ["\u00a013.5\u00a0"],
                    "Width": [" 5.25 "],
                    "Height": ["8.75\t"],
                }
            )
        )
        self.assertEqual(
            list(cartons[["Length", "Width", "Height"]].iloc[0]),
            [13.5, 5.25, 8.75],
        )

        with self.assertRaisesRegex(ValueError, "positive Length"):
            normalize_cartons(
                pd.DataFrame({"Length": ["1 3"], "Width": [5], "Height": [8]})
            )

    def test_manual_configuration_applies_stack_count(self):
        cartons = pd.DataFrame({"Length": [5], "Width": [5], "Height": [5]})
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": True,
            "max_density": False,
            "workflow": "p2p",
            "overhang": None,
            "manual_config": {
                "width": 10,
                "depth": 10,
                "hgt": 10,
                "overhang": 0,
                "shelves": 1,
                "buffer": 0,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            },
        }

        result = analyze_cartons(cartons, ["Manual Input"], options)["Manual Input"]
        self.assertEqual(result.loc[0, "Total Cartons per Bot"], 8)

    def test_analysis_uses_the_supplied_live_configuration_set(self):
        cartons = pd.DataFrame({"Length": [5], "Width": [5], "Height": [5]})
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": True,
            "max_density": False,
            "workflow": "p2p",
            "overhang": None,
            "manual_config": {},
        }
        configs = {
            "Edited Bot": {
                "width": 10,
                "depth": 10,
                "hgt": 10,
                "overhang": 0,
                "shelves": 1,
                "buffer": 0,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            }
        }

        result = analyze_cartons(
            cartons, ["Edited Bot"], options, configs=configs
        )["Edited Bot"]

        self.assertEqual(result.loc[0, "Total Cartons per Bot"], 8)

    def test_visual_placements_follow_weight_capped_capacity(self):
        cartons = pd.DataFrame(
            {"Carton Name": ["Sample"], "Length": [5], "Width": [5], "Height": [5], "Weight": [1]}
        )
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": True,
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
                "payload": 5,
            },
        }

        results, visuals = analyze_cartons_with_placements(
            cartons, ["Manual Input"], options
        )

        self.assertEqual(results["Manual Input"].loc[0, "Total Cartons per Bot"], 5)
        self.assertEqual(len(visuals["Manual Input"][0]["shelves"][0]["placements"]), 5)
        self.assertEqual(
            visuals["Manual Input"][0]["shelves"][0]["placements"][0],
            {"x": 0, "y": 0, "z": 0, "l": 5, "w": 5, "h": 5},
        )
        self.assertNotIn("placements", results["Manual Input"].columns)

    def test_visual_placements_preserve_each_manual_shelf_height(self):
        cartons = pd.DataFrame({"Length": [5], "Width": [5], "Height": [5]})
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": True,
            "max_density": False,
            "workflow": "p2p",
            "overhang": None,
            "manual_config": {
                "width": 10,
                "depth": 10,
                "hgt": [5, 10],
                "shelves": 1,
                "buffer": 0,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            },
        }

        _, visuals = analyze_cartons_with_placements(cartons, ["Manual Input"], options)
        shelves = visuals["Manual Input"][0]["shelves"]

        self.assertEqual([shelf["height"] for shelf in shelves], [5, 10])
        self.assertEqual([len(shelf["placements"]) for shelf in shelves], [4, 8])

    def test_visual_shelf_metadata_separates_physical_overhang_from_buffer(self):
        cartons = pd.DataFrame({"Length": [1], "Width": [1], "Height": [1]})
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": True,
            "max_density": False,
            "workflow": "p2p",
            "overhang": 5,
            "manual_config": {
                "width": 20,
                "depth": 15,
                "hgt": 10,
                "overhang": 3,
                "shelves": 1,
                "buffer": 10,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            },
        }

        _, visuals = analyze_cartons_with_placements(
            cartons, ["Manual Input"], options
        )
        shelf = visuals["Manual Input"][0]["shelves"][0]

        self.assertEqual(shelf["physical_width"], 20)
        self.assertEqual(shelf["core_depth"], 15)
        self.assertEqual(shelf["overhang_depth"], 5)
        self.assertEqual(shelf["width"], 18)
        self.assertEqual(shelf["depth"], 18)

    def test_per_carton_flap_states_override_global_and_blank_uses_global(self):
        cartons = pd.DataFrame(
            {
                "Length": [5, 5, 5],
                "Width": [5, 5, 5],
                "Height": [5, 5, 5],
                "Flap State": ["Flaps Up", None, "Flaps Down"],
            }
        )
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": True,
            "max_density": True,
            "workflow": "p2p",
            "overhang": None,
            "manual_config": {
                "width": 20,
                "depth": 20,
                "hgt": 15,
                "shelves": 1,
                "buffer": 0,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            },
        }

        result, visuals = analyze_cartons_with_placements(
            cartons, ["Manual Input"], options
        )
        result = result["Manual Input"]

        self.assertEqual(list(result["Flap State"]), ["Flaps Up", "Closed/Case", "Flaps Down"])
        self.assertEqual(list(result["Total Cartons per Bot"]), [16, 48, 9])
        self.assertEqual(
            [visual["flap_state"] for visual in visuals["Manual Input"]],
            ["up", "closed", "folded"],
        )
        self.assertEqual(
            [visual["carton_body_dimensions"] for visual in visuals["Manual Input"]],
            [(5, 5, 5)] * 3,
        )
        self.assertEqual(
            [visual["flap_extension"] for visual in visuals["Manual Input"]],
            [2.5, 0, 0],
        )
        self.assertEqual(
            [visual["flap_margin"] for visual in visuals["Manual Input"]],
            [0, 0, 0.25],
        )
        workbook = load_workbook(
            BytesIO(make_workbook({"Manual Input": result})), read_only=True
        )
        worksheet = workbook["Manual Input"]
        headers = [cell.value for cell in next(worksheet.iter_rows(max_row=1))]
        self.assertIn("Flap State", headers)
        state_column = headers.index("Flap State") + 1
        self.assertEqual(worksheet.cell(row=2, column=state_column).value, "Flaps Up")

    def test_missing_flap_state_column_uses_global_and_invalid_values_are_rejected(self):
        options = {
            "metric": False,
            "carton_state": "up",
            "stackable": True,
            "max_density": True,
            "workflow": "p2p",
            "overhang": None,
            "manual_config": {
                "width": 20,
                "depth": 20,
                "hgt": 15,
                "shelves": 1,
                "buffer": 0,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            },
        }
        cartons = pd.DataFrame({"Length": [5], "Width": [5], "Height": [5]})

        result = analyze_cartons(cartons, ["Manual Input"], options)["Manual Input"]
        self.assertEqual(result.loc[0, "Flap State"], "Flaps Up")
        self.assertEqual(result.loc[0, "Total Cartons per Bot"], 16)

        cartons["Flap State"] = "Open-ish"
        with self.assertRaisesRegex(ValueError, "Unrecognized Flap State"):
            analyze_cartons(cartons, ["Manual Input"], options)

    def test_open_cartons_disable_max_density_packing(self):
        cartons = pd.DataFrame(
            {
                "Length": [2, 2],
                "Width": [3, 3],
                "Height": [2, 2],
                "Flap State": ["No Flaps", None],
            }
        )
        options = {
            "metric": False,
            "carton_state": "closed",
            "stackable": False,
            "max_density": True,
            "workflow": "p2p",
            "overhang": None,
            "manual_config": {
                "width": 8,
                "depth": 8,
                "hgt": 8,
                "shelves": 1,
                "buffer": 0,
                "hinge_hgt": 0,
                "hinge_enabled": False,
                "payload": 0,
            },
        }

        with patch("capacity_engine.calculate_packing", wraps=calculate_packing) as packing:
            result, visuals = analyze_cartons_with_placements(
                cartons, ["Manual Input"], options
            )
            result = result["Manual Input"]

        self.assertEqual(list(result["Total Cartons per Bot"]), [8, 16])
        self.assertEqual(
            [visual["flap_state"] for visual in visuals["Manual Input"]],
            ["no_flaps", "closed"],
        )
        self.assertEqual(packing.call_args_list[0].args[4:7], (False, False, False))
        self.assertEqual(packing.call_args_list[1].args[4:7], (False, True, True))


if __name__ == "__main__":
    unittest.main()
