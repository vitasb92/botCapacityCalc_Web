import math
import unittest

from aisle_width_engine import (
    AISLE_PROFILES,
    calculate_aisle_widths,
    default_aisle_settings,
    profile_catalog_width,
    validate_aisle_mapping,
    validate_aisle_settings,
)


class AisleWidthTests(unittest.TestCase):
    def test_origin_profile_applies_clearance_and_minimum_one_way_width(self):
        profile = "Origin I | 20.25in/508mm Hinged Boxshelf"
        result = calculate_aisle_widths(profile, 508, 100, 100, 100)

        offset = abs(139.41502 - 195.0)
        carton_radius = math.sqrt(50**2 + (offset + 50) ** 2)
        minimum_diameter = 2 * (max(334.0, carton_radius) + 75.0)

        self.assertEqual(result["minimum_mm"]["one_way"], 1066.8)
        self.assertEqual(result["optimal_mm"]["one_way"], 1117.6)
        self.assertAlmostEqual(result["minimum_mm"]["two_way"], minimum_diameter * 2)
        self.assertAlmostEqual(result["minimum_mm"]["three_way"], minimum_diameter * 3)
        self.assertAlmostEqual(
            result["optimal_mm"]["three_way"],
            result["minimum_mm"]["three_way"] + 50.8,
        )
        self.assertEqual(result["warnings"], ())

    def test_origin_reports_hardware_height_overhang_and_scanning_warnings(self):
        result = calculate_aisle_widths(
            "Origin I | 20.25in/508mm Hinged Boxshelf",
            508,
            600,
            600,
            900,
        )

        self.assertEqual(
            result["warnings"],
            (
                "Container height exceeds the robot height limit.",
                "Container width exceeds the mapped hardware width.",
                "Container overhang exceeds 50.8 mm (2 in).",
                "Container depth may impact scanning.",
            ),
        )

    def test_vector_profile_uses_fixed_catalog_widths(self):
        result = calculate_aisle_widths(
            "Vector | Shelf",
            820,
            100,
            100,
            100,
        )

        self.assertEqual(
            result["minimum_mm"],
            {"one_way": 1250.0, "two_way": 2500.0, "three_way": 3750.0},
        )
        self.assertEqual(
            result["optimal_mm"],
            {"one_way": 1500.0, "two_way": 3000.0, "three_way": 4500.0},
        )
        self.assertEqual(result["warnings"], ())
        self.assertIsNone(profile_catalog_width("Vector | Shelf"))

    def test_aisle_settings_override_origin_and_vector_requirements(self):
        settings = default_aisle_settings()
        settings["minimum_one_way_mm"] = 1300
        vector_profile = settings["profiles"]["Vector | Shelf"]
        vector_profile["minimum_mm"] = (1400, 2700, 4000)
        vector_profile["optimal_mm"] = (1600, 3200, 4800)

        origin_result = calculate_aisle_widths(
            "Origin I | 20.25in/508mm Hinged Boxshelf",
            508,
            100,
            100,
            100,
            aisle_settings=settings,
        )
        vector_result = calculate_aisle_widths(
            "Vector | Shelf",
            820,
            100,
            100,
            100,
            aisle_settings=settings,
        )

        self.assertEqual(origin_result["minimum_mm"]["one_way"], 1300)
        self.assertEqual(origin_result["optimal_mm"]["one_way"], 1350.8)
        self.assertEqual(
            vector_result["minimum_mm"],
            {"one_way": 1400.0, "two_way": 2700.0, "three_way": 4000.0},
        )
        self.assertEqual(
            vector_result["optimal_mm"],
            {"one_way": 1600.0, "two_way": 3200.0, "three_way": 4800.0},
        )

    def test_aisle_settings_reject_invalid_requirements_and_catalog_changes(self):
        settings = default_aisle_settings()
        settings["profiles"]["Vector | Shelf"]["minimum_mm"] = (2000, 2500, 3750)
        with self.assertRaisesRegex(ValueError, "must not be smaller"):
            validate_aisle_settings(settings)

        settings = default_aisle_settings()
        settings["profiles"]["Vector | Shelf"]["hardware_width_mm"] = 508
        with self.assertRaisesRegex(ValueError, "Hardware width cannot be changed"):
            validate_aisle_settings(settings)

    def test_origin_mapping_requires_exact_catalog_width(self):
        with self.assertRaisesRegex(ValueError, "must match its catalog width"):
            validate_aisle_mapping(
                "Origin I | 20.25in/508mm Hinged Boxshelf",
                510,
            )

        self.assertEqual(
            validate_aisle_mapping("Origin I | 20.25in/508mm Hinged Boxshelf", 508),
            508.0,
        )

    def test_mapping_and_carton_dimensions_must_be_finite_and_positive(self):
        with self.assertRaisesRegex(ValueError, "Robot width"):
            validate_aisle_mapping("Vector | Shelf", float("nan"))

        for value in (0, -1, float("inf"), "not a dimension"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Carton depth"):
                    calculate_aisle_widths(
                        "Vector | Shelf",
                        820,
                        100,
                        value,
                        100,
                    )

    def test_catalog_has_all_profiles_from_attached_calculator(self):
        self.assertEqual(
            sum(profile["type"] == "ORIGIN 1" for profile in AISLE_PROFILES.values()),
            16,
        )
        self.assertEqual(
            sum(profile["type"] == "ORIGIN 2" for profile in AISLE_PROFILES.values()),
            8,
        )
        self.assertEqual(
            sum(profile["type"] == "VECTOR" for profile in AISLE_PROFILES.values()),
            9,
        )


if __name__ == "__main__":
    unittest.main()
