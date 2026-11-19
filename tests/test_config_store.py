import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from aisle_width_engine import default_aisle_settings
from capacity_engine import DEFAULT_CONFIGS
from config_store import (
    MANUAL_CONFIG_NAME,
    delete_config,
    load_aisle_mappings,
    load_aisle_settings,
    load_config_records,
    load_configs,
    save_aisle_mappings,
    save_aisle_settings,
    save_config,
    validate_config,
)


class ConfigurationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "configs.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initializes_from_defaults_with_sorted_family_labels(self):
        configs = load_configs(self.database)
        self.assertEqual(configs, DEFAULT_CONFIGS)
        self.assertEqual(load_aisle_mappings(self.database), {})
        records = load_config_records(self.database)
        self.assertEqual(records[0]["name"], MANUAL_CONFIG_NAME)
        managed = records[1:]
        self.assertEqual(
            [(record["bot_family"], record["name"]) for record in managed],
            sorted(
                [(record["bot_family"], record["name"]) for record in managed],
                key=lambda pair: (pair[0].casefold(), pair[1].casefold()),
            ),
        )

        original = next(record for record in managed if record["bot_family"] == "OI")
        updated = dict(original["config"])
        updated["width"] = 42
        save_config("Example Bot", "New Family", updated, db_path=self.database)

        configs = load_configs(self.database)
        self.assertEqual(configs["Example Bot | New Family"]["width"], 42)
        self.assertIn(MANUAL_CONFIG_NAME, configs)
        self.assertEqual(load_aisle_settings(self.database), default_aisle_settings())

    def test_persists_edited_aisle_requirements_without_changing_profiles(self):
        settings = default_aisle_settings()
        settings["profiles"]["Origin I | 20.25in/508mm Hinged Boxshelf"][
            "tray_radius_mm"
        ] = 350
        settings["profiles"]["Vector | Shelf"]["minimum_mm"] = (1400, 2700, 4000)
        settings["profiles"]["Vector | Shelf"]["optimal_mm"] = (1600, 3200, 4800)
        settings["origin_constants"]["ORIGIN 1"]["buffer_mm"] = 80
        settings["minimum_one_way_mm"] = 1200

        save_aisle_settings(settings, db_path=self.database)
        loaded = load_aisle_settings(self.database)

        self.assertEqual(
            loaded["profiles"]["Origin I | 20.25in/508mm Hinged Boxshelf"][
                "tray_radius_mm"
            ],
            350,
        )
        self.assertEqual(
            loaded["profiles"]["Vector | Shelf"]["minimum_mm"],
            (1400.0, 2700.0, 4000.0),
        )
        self.assertEqual(loaded["origin_constants"]["ORIGIN 1"]["buffer_mm"], 80)
        self.assertEqual(loaded["minimum_one_way_mm"], 1200)

    def test_rejects_invalid_aisle_requirements(self):
        settings = default_aisle_settings()
        settings["profiles"]["Vector | Shelf"]["minimum_mm"] = (2000, 2500, 3750)

        with self.assertRaisesRegex(ValueError, "must not be smaller"):
            save_aisle_settings(settings, db_path=self.database)

    def test_migrates_legacy_names_and_keeps_manual_input(self):
        default_config = next(
            config for name, config in DEFAULT_CONFIGS.items() if name != MANUAL_CONFIG_NAME
        )
        manual_config = DEFAULT_CONFIGS[MANUAL_CONFIG_NAME]
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE bot_configurations (
                    name TEXT PRIMARY KEY COLLATE NOCASE,
                    config_json TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                "INSERT INTO bot_configurations (name, config_json) VALUES (?, ?)",
                [
                    ("Box Shelf | New Family", json.dumps(default_config)),
                    ("Legacy Custom Shelf", json.dumps(default_config)),
                    (MANUAL_CONFIG_NAME, json.dumps(manual_config)),
                ],
            )

        records = load_config_records(self.database)
        by_name = {record["name"]: record for record in records}

        self.assertEqual(by_name["Box Shelf"]["bot_family"], "New Family")
        self.assertEqual(by_name["Legacy Custom Shelf"]["bot_family"], "Unassigned")
        self.assertEqual(by_name[MANUAL_CONFIG_NAME]["bot_family"], "")
        self.assertEqual(
            load_configs(self.database)["Box Shelf | New Family"],
            default_config,
        )
        self.assertIn("Legacy Custom Shelf | Unassigned", load_configs(self.database))
        with closing(sqlite3.connect(self.database)) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(bot_configurations)")
            }
            self.assertIn("bot_family", columns)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'aisle_width_mappings'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'bot_configurations_legacy'"
                ).fetchone()[0],
                0,
            )

    def test_allows_duplicate_names_across_families_but_requires_unique_pairs(self):
        config = next(
            config for name, config in DEFAULT_CONFIGS.items() if name != MANUAL_CONFIG_NAME
        )

        save_config("Shared Shelf", "OI", config, db_path=self.database)
        save_config("Shared Shelf", "New Family", config, db_path=self.database)

        configs = load_configs(self.database)
        self.assertIn("Shared Shelf | OI", configs)
        self.assertIn("Shared Shelf | New Family", configs)
        with self.assertRaisesRegex(ValueError, "already exists"):
            save_config("Shared Shelf", "OI", config, db_path=self.database)

    def test_edits_name_and_family_and_deletes_by_pair(self):
        records = load_config_records(self.database)
        original = next(
            record
            for record in records
            if record["name"] != MANUAL_CONFIG_NAME
        )
        updated = dict(original["config"])
        updated["width"] = 23.5

        save_config(
            "Renamed Shelf",
            "New Family",
            updated,
            original_name=original["name"],
            original_bot_family=original["bot_family"],
            db_path=self.database,
        )

        configs = load_configs(self.database)
        self.assertNotIn(
            f"{original['name']} | {original['bot_family']}",
            configs,
        )
        self.assertEqual(configs["Renamed Shelf | New Family"]["width"], 23.5)

        delete_config("Renamed Shelf", "New Family", self.database)
        self.assertNotIn("Renamed Shelf | New Family", load_configs(self.database))

    def test_aisle_mapping_follows_configuration_rename_and_is_deleted_with_config(self):
        record = next(
            record
            for record in load_config_records(self.database)
            if record["name"] != MANUAL_CONFIG_NAME
        )
        save_aisle_mappings(
            [
                {
                    "name": record["name"],
                    "bot_family": record["bot_family"],
                    "aisle_profile": "Origin I | 20.25in/508mm Hinged Boxshelf",
                    "robot_width_mm": 508,
                }
            ],
            db_path=self.database,
        )
        original_label = f"{record['name']} | {record['bot_family']}"
        self.assertIn(original_label, load_aisle_mappings(self.database))

        updated = dict(record["config"])
        save_config(
            "Renamed Shelf",
            "New Family",
            updated,
            original_name=record["name"],
            original_bot_family=record["bot_family"],
            db_path=self.database,
        )
        mappings = load_aisle_mappings(self.database)
        renamed_label = "Renamed Shelf | New Family"
        self.assertNotIn(original_label, mappings)
        self.assertEqual(mappings[renamed_label]["robot_width_mm"], 508.0)

        delete_config("Renamed Shelf", "New Family", self.database)
        self.assertNotIn(renamed_label, load_aisle_mappings(self.database))

    def test_aisle_mapping_rejects_bad_catalog_widths_and_missing_configurations(self):
        record = next(
            record
            for record in load_config_records(self.database)
            if record["name"] != MANUAL_CONFIG_NAME
        )
        mapping = {
            "name": record["name"],
            "bot_family": record["bot_family"],
            "aisle_profile": "Origin I | 20.25in/508mm Hinged Boxshelf",
            "robot_width_mm": 520,
        }

        with self.assertRaisesRegex(ValueError, "must match its catalog width"):
            save_aisle_mappings([mapping], db_path=self.database)

        mapping["robot_width_mm"] = 508
        mapping["name"] = "Missing Configuration"
        with self.assertRaisesRegex(ValueError, "refer to missing configurations"):
            save_aisle_mappings([mapping], db_path=self.database)

        mapping["name"] = record["name"]
        mapping["aisle_profile"] = "Unknown profile"
        with self.assertRaisesRegex(ValueError, "Unrecognized aisle profile"):
            save_aisle_mappings([mapping], db_path=self.database)

    def test_zeroes_hinge_dimensions_when_fallback_is_disabled_on_add_and_edit(self):
        config = next(
            dict(config)
            for name, config in DEFAULT_CONFIGS.items()
            if name != MANUAL_CONFIG_NAME and config["hinge_enabled"]
        )
        config["hinge_enabled"] = False

        save_config("Disabled Hinge", "OI", config, db_path=self.database)
        saved = load_configs(self.database)["Disabled Hinge | OI"]
        self.assertEqual(
            (saved["hng_width"], saved["hng_depth"], saved["hinge_hgt"]),
            (0.0, 0.0, 0.0),
        )

        config.update({"hng_width": 12.0, "hng_depth": 10.0, "hinge_hgt": 8.0})
        save_config(
            "Disabled Hinge",
            "OI",
            config,
            original_name="Disabled Hinge",
            original_bot_family="OI",
            db_path=self.database,
        )
        saved = load_configs(self.database)["Disabled Hinge | OI"]
        self.assertEqual(
            (saved["hng_width"], saved["hng_depth"], saved["hinge_hgt"]),
            (0.0, 0.0, 0.0),
        )

    def test_enabled_hinge_fallback_requires_positive_dimensions(self):
        config = next(
            dict(config)
            for name, config in DEFAULT_CONFIGS.items()
            if name != MANUAL_CONFIG_NAME and config["hinge_enabled"]
        )
        for field in ("hng_width", "hng_depth", "hinge_hgt"):
            invalid_config = dict(config)
            invalid_config[field] = 0.0
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, f"{field}.*positive"):
                    save_config(
                        f"Invalid {field}",
                        "OI",
                        invalid_config,
                        db_path=self.database,
                    )

    def test_rejects_nonfinite_hinge_height_when_fallback_is_disabled(self):
        config = dict(
            next(
                config
                for name, config in DEFAULT_CONFIGS.items()
                if name != MANUAL_CONFIG_NAME
            )
        )
        config["hinge_enabled"] = False
        config["hinge_hgt"] = float("nan")

        with self.assertRaisesRegex(ValueError, "hinge_hgt.*finite"):
            validate_config("Invalid Hinge Height", "OI", config)

    def test_loads_older_hinge_configurations_without_explicit_width_and_depth(self):
        config = next(
            dict(config)
            for name, config in DEFAULT_CONFIGS.items()
            if name != MANUAL_CONFIG_NAME and config["hinge_enabled"]
        )
        config.pop("hng_width")
        config.pop("hng_depth")
        load_config_records(self.database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                """
                INSERT INTO bot_configurations (name, bot_family, config_json)
                VALUES (?, ?, ?)
                """,
                ("Older Hinge Config", "OI", json.dumps(config)),
            )

        record = next(
            record
            for record in load_config_records(self.database)
            if record["name"] == "Older Hinge Config"
        )
        self.assertNotIn("hng_width", record["config"])
        self.assertNotIn("hng_depth", record["config"])

    def test_rejects_reserved_manual_name_and_invalid_configuration(self):
        config = dict(
            next(
                config
                for name, config in DEFAULT_CONFIGS.items()
                if name != MANUAL_CONFIG_NAME
            )
        )
        with self.assertRaisesRegex(ValueError, "reserved"):
            save_config(MANUAL_CONFIG_NAME, "OI", config, db_path=self.database)
        with self.assertRaisesRegex(ValueError, "Bot family cannot be blank"):
            save_config("Bad Bot", "", config, db_path=self.database)

        config["buffer"] = 100
        with self.assertRaisesRegex(ValueError, "less than 100"):
            save_config("Bad Bot", "OI", config, db_path=self.database)

    def test_preserves_manual_input_and_last_bot(self):
        configs = load_config_records(self.database)
        first_bot = next(
            record for record in configs if record["name"] != MANUAL_CONFIG_NAME
        )

        with self.assertRaisesRegex(ValueError, "cannot be deleted"):
            delete_config(MANUAL_CONFIG_NAME, "")
        delete_config(first_bot["name"], first_bot["bot_family"], self.database)

        remaining_bot = next(
            record
            for record in load_config_records(self.database)
            if record["name"] != MANUAL_CONFIG_NAME
        )
        for record in load_config_records(self.database):
            record_pair = (record["name"], record["bot_family"])
            remaining_pair = (remaining_bot["name"], remaining_bot["bot_family"])
            if record_pair != (MANUAL_CONFIG_NAME, "") and record_pair != remaining_pair:
                delete_config(record["name"], record["bot_family"], self.database)
        with self.assertRaisesRegex(ValueError, "At least one"):
            delete_config(
                remaining_bot["name"],
                remaining_bot["bot_family"],
                self.database,
            )


if __name__ == "__main__":
    unittest.main()
