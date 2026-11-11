from io import BytesIO
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook

from capacity_engine import analyze_cartons, calculate_packing, make_workbook, normalize_cartons


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

    def test_normalize_cartons_maps_dimensions_and_rejects_nonpositive_values(self):
        cartons = normalize_cartons(
            pd.DataFrame({"Width (X)": [10], "Depth (Y)": [8], "Height": [4]})
        )
        self.assertEqual(list(cartons[["Length", "Width", "Height"]].iloc[0]), [10, 8, 4])

        with self.assertRaisesRegex(ValueError, "positive Length"):
            normalize_cartons(pd.DataFrame({"Length": [0], "Width": [8], "Height": [4]}))

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

        result = analyze_cartons(cartons, ["Manual Input"], options)["Manual Input"]

        self.assertEqual(list(result["Flap State"]), ["Flaps Up", "Closed/Case", "Flaps Down"])
        self.assertEqual(list(result["Total Cartons per Bot"]), [16, 48, 9])
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
            result = analyze_cartons(cartons, ["Manual Input"], options)["Manual Input"]

        self.assertEqual(list(result["Total Cartons per Bot"]), [8, 16])
        self.assertEqual(packing.call_args_list[0].args[4:7], (False, False, False))
        self.assertEqual(packing.call_args_list[1].args[4:7], (False, True, True))


if __name__ == "__main__":
    unittest.main()
