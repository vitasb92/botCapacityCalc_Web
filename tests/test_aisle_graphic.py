from io import BytesIO
import unittest

from PIL import Image, ImageColor

from brand_palette import NEUTRAL_PALE
from aisle_graphic import create_aisle_requirements_png
from aisle_width_engine import TRAFFIC_PATTERNS


class AisleGraphicTests(unittest.TestCase):
    def test_creates_png_for_all_three_traffic_scenarios(self):
        scenarios = [
            {
                "traffic_pattern": traffic_pattern,
                "minimum_width_mm": 1100.0 + index * 100,
                "minimum_carton": f"Minimum carton {index + 1}",
                "optimal_width_mm": 1200.0 + index * 100,
                "optimal_carton": f"Optimal carton {index + 1}",
            }
            for index, traffic_pattern in enumerate(TRAFFIC_PATTERNS)
        ]

        png_data = create_aisle_requirements_png(
            "Sample Bot | OI",
            "Origin I | 20.25in/508mm Hinged Boxshelf",
            508,
            scenarios,
        )

        self.assertTrue(png_data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png_data)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (1800, 990))
            self.assertEqual(
                image.getpixel((0, 0)),
                ImageColor.getrgb(NEUTRAL_PALE),
            )

    def test_rejects_missing_traffic_scenario(self):
        with self.assertRaisesRegex(ValueError, "one result for each traffic pattern"):
            create_aisle_requirements_png(
                "Sample Bot",
                "Vector | Shelf",
                820,
                [
                    {
                        "traffic_pattern": TRAFFIC_PATTERNS[0],
                        "minimum_width_mm": 1250,
                        "minimum_carton": "Carton 1",
                        "optimal_width_mm": 1500,
                        "optimal_carton": "Carton 1",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
