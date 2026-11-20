import math
from typing import Optional


ORIGIN_CONSTANTS = {
    "ORIGIN 1": {
        "mast_to_center_mm": 195.0,
        "front_edge_to_mast_mm": 139.41502,
        "buffer_mm": 75.0,
        "optimal_add_mm": 50.8,
        "max_container_height_mm": 848.0,
        "baseline_depth_mm": 457.0,
    },
    "ORIGIN 2": {
        "mast_to_center_mm": 192.0,
        "front_edge_to_mast_mm": 127.0,
        "buffer_mm": 75.0,
        "optimal_add_mm": 50.8,
        "max_container_height_mm": 1001.0,
        "baseline_depth_mm": 563.0,
    },
}


AISLE_PROFILES = {
    "Origin I | 20.25in/508mm Hinged Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 508.0,
        "tray_radius_mm": 334.0,
    },
    "Origin I | 20.25in/508mm Multi-Level Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 508.0,
        "tray_radius_mm": 332.5,
    },
    "Origin I | 20.5in/520mm Tray": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 520.0,
        "tray_radius_mm": 294.0,
    },
    "Origin I | 22.25in/559mm Hinged Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 559.0,
        "tray_radius_mm": 354.0,
    },
    "Origin I | 22.25in/559mm Multi-Level Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 559.0,
        "tray_radius_mm": 353.0,
    },
    "Origin I | 22.5in/572mm Tray": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 572.0,
        "tray_radius_mm": 328.0,
    },
    "Origin I | 24.25in/610mm Hinged Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 610.0,
        "tray_radius_mm": 377.5,
    },
    "Origin I | 24.25in/610mm Multi-Level Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 610.0,
        "tray_radius_mm": 373.5,
    },
    "Origin I | 24.5in/622mm Tray": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 622.0,
        "tray_radius_mm": 340.0,
    },
    "Origin I | 26.25in/660mm Hinged Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 660.0,
        "tray_radius_mm": 400.0,
    },
    "Origin I | 26.25in/660mm Multi-Level Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 660.0,
        "tray_radius_mm": 394.5,
    },
    "Origin I | 26.5in/673mm Tray": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 673.0,
        "tray_radius_mm": 374.0,
    },
    "Origin I | 30.25in/762mm Hinged Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 762.0,
        "tray_radius_mm": 446.0,
    },
    "Origin I | 30.25in/762mm Multi-Level Boxshelf": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 762.0,
        "tray_radius_mm": 441.0,
    },
    "Origin I | 30.5in/775mm Tray": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 775.0,
        "tray_radius_mm": 420.5,
    },
    "Origin I | 32.5in/826mm Tray": {
        "type": "ORIGIN 1",
        "hardware_width_mm": 826.0,
        "tray_radius_mm": 446.0,
    },
    "Origin II | 20.25in/514mm Multi-Level Boxshelf": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 514.0,
        "tray_radius_mm": 324.0,
    },
    "Origin II | 20.5in/520mm Tray": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 520.0,
        "tray_radius_mm": 287.0,
    },
    "Origin II | 22.25in/564mm Multi-Level Boxshelf": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 564.0,
        "tray_radius_mm": 345.0,
    },
    "Origin II | 22.5in/572mm Tray": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 572.0,
        "tray_radius_mm": 326.0,
    },
    "Origin II | 24.25in/615mm Multi-Level Boxshelf": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 615.0,
        "tray_radius_mm": 365.0,
    },
    "Origin II | 24.5in/622mm Tray": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 622.0,
        "tray_radius_mm": 336.0,
    },
    "Origin II | 26.25in/665mm Multi-Level Boxshelf (hardware width 666 mm)": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 666.0,
        "tray_radius_mm": 388.0,
    },
    "Origin II | 26.5in/673mm Tray": {
        "type": "ORIGIN 2",
        "hardware_width_mm": 673.0,
        "tray_radius_mm": 372.0,
    },
    "Vector | Shelf": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1250.0, 2500.0, 3750.0),
        "optimal_mm": (1500.0, 3000.0, 4500.0),
    },
    "Vector | 2'x4' Cart": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1311.0, 2591.0, 3871.0),
        "optimal_mm": (1801.0, 3571.0, 5341.0),
    },
    "Vector | 2'x5' Cart": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1311.0, 2652.0, 3993.0),
        "optimal_mm": (1811.0, 3652.0, 5493.0),
    },
    "Vector | 2'x6' Cart": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1342.0, 2652.0, 3963.0),
        "optimal_mm": (1852.0, 3672.0, 5493.0),
    },
    "Vector | 3'x4' Cart": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1616.0, 3201.0, 4786.0),
        "optimal_mm": (2096.0, 4160.0, 6226.0),
    },
    "Vector | 3'x5' Cart": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1616.0, 3231.0, 4847.0),
        "optimal_mm": (2116.0, 4231.0, 6347.0),
    },
    "Vector | 3'x6' Cart": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1616.0, 3262.0, 4908.0),
        "optimal_mm": (2136.0, 4301.0, 6468.0),
    },
    "Vector | 3'x6' Non Con": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1616.0, 3262.0, 4908.0),
        "optimal_mm": (2136.0, 4301.0, 6468.0),
    },
    "Vector | Pallet Dolly": {
        "type": "VECTOR",
        "hardware_width_mm": None,
        "minimum_mm": (1780.0, 3550.0, 5320.0),
        "optimal_mm": (2280.0, 4550.0, 6820.0),
    },
}

TRAFFIC_PATTERNS = (
    "No-Pass (1-Way)",
    "Pass (2-Way)",
    "High-Density (3-Way)",
)

_TRAFFIC_KEYS = ("one_way", "two_way", "three_way")
MINIMUM_ONE_WAY_MM = 1066.8


def default_aisle_settings():
    return {
        "profiles": {
            profile_key: dict(profile)
            for profile_key, profile in AISLE_PROFILES.items()
        },
        "origin_constants": {
            robot_type: dict(constants)
            for robot_type, constants in ORIGIN_CONSTANTS.items()
        },
        "minimum_one_way_mm": MINIMUM_ONE_WAY_MM,
    }


def _finite_number(value, name, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number.") from None
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a finite {qualifier} number.")
    return number


def validate_aisle_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("Aisle settings must be an object.")
    profiles = settings.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(AISLE_PROFILES):
        raise ValueError("Aisle settings must include every existing profile exactly once.")

    normalized_profiles = {}
    for profile_key, defaults in AISLE_PROFILES.items():
        profile = profiles[profile_key]
        if not isinstance(profile, dict) or profile.get("type") != defaults["type"]:
            raise ValueError(f"Profile type cannot be changed for '{profile_key}'.")
        if profile.get("hardware_width_mm") != defaults["hardware_width_mm"]:
            raise ValueError(f"Hardware width cannot be changed for '{profile_key}'.")
        normalized = dict(defaults)
        if defaults["type"] == "VECTOR":
            for field in ("minimum_mm", "optimal_mm"):
                values = profile.get(field)
                if not isinstance(values, (list, tuple)) or len(values) != len(_TRAFFIC_KEYS):
                    raise ValueError(
                        f"{field} for '{profile_key}' must have one value per traffic pattern."
                    )
                normalized[field] = tuple(
                    _finite_number(value, f"{profile_key} {field}")
                    for value in values
                )
            if any(
                optimal < minimum
                for minimum, optimal in zip(
                    normalized["minimum_mm"], normalized["optimal_mm"]
                )
            ):
                raise ValueError(
                    f"Optimal aisle widths must not be smaller than minimum widths for '{profile_key}'."
                )
        else:
            normalized["tray_radius_mm"] = _finite_number(
                profile.get("tray_radius_mm"),
                f"{profile_key} tray radius",
            )
        normalized_profiles[profile_key] = normalized

    origin_constants = settings.get("origin_constants")
    if (
        not isinstance(origin_constants, dict)
        or set(origin_constants) != set(ORIGIN_CONSTANTS)
    ):
        raise ValueError("Aisle settings must include every existing Origin model exactly once.")
    normalized_constants = {}
    for robot_type, defaults in ORIGIN_CONSTANTS.items():
        constants = origin_constants[robot_type]
        if not isinstance(constants, dict) or set(constants) != set(defaults):
            raise ValueError(f"Invalid Origin model settings for '{robot_type}'.")
        normalized_constants[robot_type] = {
            field: _finite_number(
                constants[field],
                f"{robot_type} {field}",
                allow_zero=field in ("buffer_mm", "optimal_add_mm"),
            )
            for field in defaults
        }

    return {
        "profiles": normalized_profiles,
        "origin_constants": normalized_constants,
        "minimum_one_way_mm": _finite_number(
            settings.get("minimum_one_way_mm"),
            "One-way minimum aisle width",
        ),
    }


def validate_aisle_mapping(profile_key, robot_width_mm):
    profile = AISLE_PROFILES.get(profile_key)
    if profile is None:
        raise ValueError(f"Unrecognized aisle profile: {profile_key}")
    if isinstance(robot_width_mm, bool):
        raise ValueError("Robot width must be a finite positive number in mm.")
    try:
        width = float(robot_width_mm)
    except (TypeError, ValueError):
        raise ValueError("Robot width must be a finite positive number in mm.") from None
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Robot width must be a finite positive number in mm.")

    catalog_width = profile["hardware_width_mm"]
    if catalog_width is not None and not math.isclose(
        width, catalog_width, rel_tol=0.0, abs_tol=0.01
    ):
        raise ValueError(
            f"Robot width for '{profile_key}' must match its catalog width "
            f"of {catalog_width:g} mm."
        )
    return width


def _positive_dimension(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive number in mm.")
    try:
        dimension = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite positive number in mm.") from None
    if not math.isfinite(dimension) or dimension <= 0:
        raise ValueError(f"{name} must be a finite positive number in mm.")
    return dimension


def calculate_aisle_widths(
    profile_key,
    robot_width_mm,
    carton_width_mm,
    carton_depth_mm,
    carton_height_mm,
    aisle_settings=None,
):
    settings = default_aisle_settings() if aisle_settings is None else aisle_settings
    profile_catalog = settings["profiles"]
    profile = profile_catalog.get(profile_key)
    if profile is None:
        raise ValueError(f"Unrecognized aisle profile: {profile_key}")
    robot_width_mm = validate_aisle_mapping(profile_key, robot_width_mm)
    carton_width_mm = _positive_dimension(carton_width_mm, "Carton width")
    carton_depth_mm = _positive_dimension(carton_depth_mm, "Carton depth")
    carton_height_mm = _positive_dimension(carton_height_mm, "Carton height")

    if profile["type"] == "VECTOR":
        minimum = dict(zip(_TRAFFIC_KEYS, profile["minimum_mm"]))
        optimal = dict(zip(_TRAFFIC_KEYS, profile["optimal_mm"]))
        warnings = ()
    else:
        constants = settings["origin_constants"][profile["type"]]
        offset = abs(
            constants["front_edge_to_mast_mm"] - constants["mast_to_center_mm"]
        )
        container_radius = math.sqrt(
            (0.5 * carton_width_mm) ** 2
            + (offset + 0.5 * carton_depth_mm) ** 2
        )
        physical_radius = max(profile["tray_radius_mm"], container_radius)
        minimum_diameter = 2 * (physical_radius + constants["buffer_mm"])
        one_way_minimum = max(minimum_diameter, settings["minimum_one_way_mm"])
        minimum = {
            "one_way": one_way_minimum,
            "two_way": minimum_diameter * 2,
            "three_way": minimum_diameter * 3,
        }
        optimal = {
            key: value + constants["optimal_add_mm"]
            for key, value in minimum.items()
        }

        warning_messages = []
        if carton_height_mm > constants["max_container_height_mm"]:
            warning_messages.append(
                "Container height exceeds the robot height limit."
            )
        if carton_width_mm > robot_width_mm:
            warning_messages.append(
                "Container width exceeds the mapped hardware width."
            )
        if container_radius - profile["tray_radius_mm"] > constants["optimal_add_mm"]:
            warning_messages.append(
                "Container overhang exceeds 50.8 mm (2 in)."
            )
        if carton_depth_mm > constants["baseline_depth_mm"]:
            warning_messages.append(
                "Container depth may impact scanning."
            )
        warnings = tuple(warning_messages)

    return {
        "minimum_mm": minimum,
        "optimal_mm": optimal,
        "warnings": warnings,
    }


def profile_catalog_width(profile_key) -> Optional[float]:
    profile = AISLE_PROFILES.get(profile_key)
    if profile is None:
        raise ValueError(f"Unrecognized aisle profile: {profile_key}")
    return profile["hardware_width_mm"]
