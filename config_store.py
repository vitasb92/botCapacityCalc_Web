import json
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from capacity_engine import DEFAULT_CONFIGS


MANUAL_CONFIG_NAME = "Manual Input"
DEFAULT_DATABASE_PATH = Path(__file__).with_name("bot_configs.sqlite3")
REQUIRED_FIELDS = {
    "width",
    "depth",
    "hgt",
    "shelves",
    "buffer",
    "hinge_hgt",
    "hinge_enabled",
    "payload",
}


def _database_path(db_path=None):
    return Path(db_path or os.environ.get("BOT_CONFIG_DB", DEFAULT_DATABASE_PATH))


def _connect(db_path=None):
    path = _database_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _split_legacy_config_name(name):
    if name.casefold() == MANUAL_CONFIG_NAME.casefold():
        return MANUAL_CONFIG_NAME, ""
    if "|" not in name:
        return name, "Unassigned"
    config_name, bot_family = name.rsplit("|", 1)
    return config_name.strip(), bot_family.strip()


def format_config_label(name, bot_family):
    if bot_family:
        return f"{name} | {bot_family}"
    return name


def _positive_number(value, field, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a finite number.") from None
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field} must be a finite {qualifier} number.")
    return number


def validate_config(
    name,
    bot_family,
    config,
    allow_manual=False,
    require_hinge_dimensions=False,
):
    name = str(name).strip()
    bot_family = str(bot_family).strip()
    if not name:
        raise ValueError("Configuration name cannot be blank.")
    if not allow_manual and name.casefold() == MANUAL_CONFIG_NAME.casefold():
        raise ValueError(f"'{MANUAL_CONFIG_NAME}' is reserved for custom shelf input.")
    if allow_manual and bot_family:
        raise ValueError(f"'{MANUAL_CONFIG_NAME}' cannot have a bot family.")
    if not allow_manual and not bot_family:
        raise ValueError("Bot family cannot be blank.")
    if not isinstance(config, dict):
        raise ValueError("Configuration values must be an object.")

    missing = REQUIRED_FIELDS - set(config)
    if missing:
        raise ValueError(f"Configuration is missing fields: {', '.join(sorted(missing))}.")

    for field in ("width", "depth"):
        _positive_number(config[field], field, allow_zero=allow_manual)

    heights = config["hgt"]
    if isinstance(heights, (list, tuple)):
        if not heights:
            raise ValueError("Shelf heights must contain at least one positive value.")
        for height in heights:
            _positive_number(height, "hgt", allow_zero=allow_manual)
    else:
        _positive_number(heights, "hgt", allow_zero=allow_manual)

    for field in ("overhang", "hinge_hgt", "payload"):
        if field in config:
            _positive_number(config[field], field, allow_zero=True)
    _positive_number(config["buffer"], "buffer", allow_zero=True)
    if float(config["buffer"]) >= 100:
        raise ValueError("Buffer must be less than 100%.")

    shelves = _positive_number(config["shelves"], "shelves")
    if not shelves.is_integer():
        raise ValueError("Shelf count must be a whole number.")
    if not isinstance(config["hinge_enabled"], bool):
        raise ValueError("hinge_enabled must be true or false.")

    if config["hinge_enabled"] and require_hinge_dimensions and not allow_manual:
        for field in ("hng_width", "hng_depth", "hinge_hgt"):
            if field not in config:
                raise ValueError(f"{field} is required when hinge fallback is enabled.")
            _positive_number(config[field], field)
    else:
        for field in ("hng_width", "hng_depth"):
            if field in config:
                _positive_number(config[field], field, allow_zero=not config["hinge_enabled"])

    return name, bot_family


def _create_config_table(connection, table_name="bot_configurations"):
    connection.execute(
        f"""
        CREATE TABLE {table_name} (
            name TEXT NOT NULL COLLATE NOCASE,
            bot_family TEXT NOT NULL COLLATE NOCASE,
            config_json TEXT NOT NULL,
            PRIMARY KEY (name, bot_family)
        )
        """
    )


def _migrate_config_table(connection):
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(bot_configurations)")
    }
    if "bot_family" in columns:
        return

    connection.execute("ALTER TABLE bot_configurations RENAME TO bot_configurations_legacy")
    _create_config_table(connection)
    rows = connection.execute(
        "SELECT name, config_json FROM bot_configurations_legacy ORDER BY rowid"
    ).fetchall()
    for row in rows:
        name, bot_family = _split_legacy_config_name(row["name"])
        connection.execute(
            """
            INSERT INTO bot_configurations (name, bot_family, config_json)
            VALUES (?, ?, ?)
            """,
            (name, bot_family, row["config_json"]),
        )
    connection.execute("DROP TABLE bot_configurations_legacy")


def initialize_config_store(db_path=None):
    with closing(_connect(db_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        existing_table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'bot_configurations'
            """
        ).fetchone()
        if existing_table is None:
            _create_config_table(connection)
        else:
            _migrate_config_table(connection)

        if connection.execute("SELECT COUNT(*) FROM bot_configurations").fetchone()[0] == 0:
            for legacy_name, config in DEFAULT_CONFIGS.items():
                name, bot_family = _split_legacy_config_name(legacy_name)
                validate_config(
                    name,
                    bot_family,
                    config,
                    allow_manual=name.casefold() == MANUAL_CONFIG_NAME.casefold(),
                )
                connection.execute(
                    """
                    INSERT INTO bot_configurations (name, bot_family, config_json)
                    VALUES (?, ?, ?)
                    """,
                    (name, bot_family, json.dumps(config, allow_nan=False)),
                )


def load_config_records(db_path=None):
    initialize_config_store(db_path)
    with closing(_connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT name, bot_family, config_json FROM bot_configurations"
        ).fetchall()
    records = [
        {
            "name": row["name"],
            "bot_family": row["bot_family"],
            "config": json.loads(row["config_json"]),
        }
        for row in rows
    ]
    records.sort(
        key=lambda record: (
            record["name"].casefold() != MANUAL_CONFIG_NAME.casefold(),
            record["bot_family"].casefold(),
            record["name"].casefold(),
        )
    )
    for record in records:
        validate_config(
            record["name"],
            record["bot_family"],
            record["config"],
            allow_manual=record["name"].casefold() == MANUAL_CONFIG_NAME.casefold(),
        )
    return records


def load_configs(db_path=None):
    return {
        format_config_label(record["name"], record["bot_family"]): record["config"]
        for record in load_config_records(db_path)
    }


def save_config(
    name,
    bot_family,
    config,
    original_name=None,
    original_bot_family=None,
    db_path=None,
):
    if isinstance(config, dict):
        config = dict(config)
        if config.get("hinge_enabled") is False:
            config.update({field: 0.0 for field in ("hng_width", "hng_depth", "hinge_hgt")})
    name, bot_family = validate_config(
        name,
        bot_family,
        config,
        require_hinge_dimensions=True,
    )
    if original_name is not None:
        if original_name.casefold() == MANUAL_CONFIG_NAME.casefold():
            raise ValueError(f"'{MANUAL_CONFIG_NAME}' cannot be edited.")
        if original_bot_family is None:
            raise ValueError("Original bot family is required when editing a configuration.")
    initialize_config_store(db_path)
    encoded_config = json.dumps(config, allow_nan=False)

    with closing(_connect(db_path)) as connection, connection:
        try:
            if original_name is None:
                connection.execute(
                    """
                    INSERT INTO bot_configurations (name, bot_family, config_json)
                    VALUES (?, ?, ?)
                    """,
                    (name, bot_family, encoded_config),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE bot_configurations
                    SET name = ?, bot_family = ?, config_json = ?
                    WHERE name = ? COLLATE NOCASE
                    AND bot_family = ? COLLATE NOCASE
                    """,
                    (name, bot_family, encoded_config, original_name, original_bot_family),
                )
                if cursor.rowcount == 0:
                    raise ValueError(
                        f"Configuration '{format_config_label(original_name, original_bot_family)}' "
                        "does not exist."
                    )
        except sqlite3.IntegrityError:
            label = format_config_label(name, bot_family)
            raise ValueError(f"A configuration named '{label}' already exists.") from None


def delete_config(name, bot_family, db_path=None):
    if name.casefold() == MANUAL_CONFIG_NAME.casefold():
        raise ValueError(f"'{MANUAL_CONFIG_NAME}' cannot be deleted.")
    initialize_config_store(db_path)

    with closing(_connect(db_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        count = connection.execute(
            "SELECT COUNT(*) FROM bot_configurations WHERE name != ? COLLATE NOCASE",
            (MANUAL_CONFIG_NAME,),
        ).fetchone()[0]
        if count <= 1:
            raise ValueError("At least one bot configuration must remain.")
        cursor = connection.execute(
            """
            DELETE FROM bot_configurations
            WHERE name = ? COLLATE NOCASE AND bot_family = ? COLLATE NOCASE
            """,
            (name, bot_family),
        )
        if cursor.rowcount == 0:
            raise ValueError(
                f"Configuration '{format_config_label(name, bot_family)}' does not exist."
            )
