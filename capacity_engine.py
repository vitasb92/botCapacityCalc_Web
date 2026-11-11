import json
import math
import re
from io import BytesIO
from itertools import permutations
from pathlib import Path

import pandas as pd


with Path(__file__).with_name("bot_configs.json").open(encoding="utf-8") as config_file:
    DEFAULT_CONFIGS = json.load(config_file)

FLAP_STATES = {
    "closed/case": ("closed", "Closed/Case"),
    "flaps up": ("up", "Flaps Up"),
    "flaps down": ("folded", "Flaps Down"),
    "no flaps": ("no_flaps", "No Flaps"),
}
FLAP_STATE_LABELS = {code: label for code, label in FLAP_STATES.values()}
FLAP_STATE_CODES = {label.casefold(): code for code, label in FLAP_STATES.values()}


def get_best_homogeneous(e_l, e_w, e_h, rotations, stackable, workflow="p2p", x0=0, y0=0, z0=0):
    best_coords, max_count = [], 0
    for bl, bw, bh in rotations:
        if bl <= 0 or bw <= 0 or bh <= 0:
            continue
        fit_l, fit_w = int(e_l // bl), int(e_w // bw)
        if workflow == "pick_put":
            fit_w = min(1, fit_w)
        fit_h = int(e_h // bh) if stackable else (1 if bh <= e_h else 0)
        count = fit_l * fit_w * fit_h
        if count > max_count:
            max_count = count
            best_coords = [
                {
                    "x": x0 + i * bl,
                    "y": y0 + j * bw,
                    "z": z0 + k * bh,
                    "l": bl,
                    "w": bw,
                    "h": bh,
                }
                for k in range(fit_h)
                for j in range(fit_w)
                for i in range(fit_l)
            ]
    return best_coords


def calculate_packing(
    e_l, e_w, e_h, box_dims, stackable=True, allow_3d=True, max_density=False, workflow="p2p"
):
    if any(d <= 0 for d in (e_l, e_w, e_h)) or any(d <= 0 for d in box_dims):
        return 0, "No Fit", []
    rotations = (
        list(permutations(box_dims))
        if allow_3d
        else [
            (box_dims[0], box_dims[1], box_dims[2]),
            (box_dims[1], box_dims[0], box_dims[2]),
        ]
    )

    if not max_density:
        best_coords = get_best_homogeneous(e_l, e_w, e_h, rotations, stackable, workflow)
        if not best_coords:
            return 0, "No Fit", []
        first = best_coords[0]
        orientation = f"{round(first['l'], 2)}x{round(first['w'], 2)}x{round(first['h'], 2)}"
        return len(best_coords), orientation, best_coords

    best_all_coords, best_total, best_orientation = [], 0, "No Fit"
    for bl, bw, bh in rotations:
        if bl <= 0 or bw <= 0 or bh <= 0:
            continue
        fit_l, fit_w = int(e_l // bl), int(e_w // bw)
        if workflow == "pick_put":
            fit_w = min(1, fit_w)
        fit_h = int(e_h // bh) if stackable else (1 if bh <= e_h else 0)
        if fit_l * fit_w * fit_h == 0:
            continue

        main_coords = [
            {"x": i * bl, "y": j * bw, "z": k * bh, "l": bl, "w": bw, "h": bh}
            for k in range(fit_h)
            for j in range(fit_w)
            for i in range(fit_l)
        ]
        used_l, used_w = fit_l * bl, fit_w * bw
        rem_x = get_best_homogeneous(
            e_l - used_l, e_w, e_h, rotations, stackable, workflow, x0=used_l
        )
        rem_y = []
        if workflow == "p2p":
            rem_y = get_best_homogeneous(
                used_l, e_w - used_w, e_h, rotations, stackable, workflow, y0=used_w
            )
        total_coords = main_coords + rem_x + rem_y
        if len(total_coords) > best_total:
            best_total = len(total_coords)
            best_all_coords = total_coords
            best_orientation = f"Mixed (Main: {round(bl, 2)}x{round(bw, 2)}x{round(bh, 2)})"
    return best_total, best_orientation, best_all_coords


def normalize_cartons(dataframe, default_flap_state="closed"):
    aliases = {
        "length": "Length",
        "width (x)": "Length",
        "width": "Width",
        "depth (y)": "Width",
        "height": "Height",
        "sku": "SKU",
        "item": "SKU",
        "item number": "SKU",
        "carton name": "Carton Name",
        "name": "Carton Name",
        "carton": "Carton Name",
        "description": "Carton Name",
        "weight": "Weight",
        "flap state": "Flap State",
    }
    df = dataframe.copy()
    rename = {}
    seen = set()
    for column in df.columns:
        name = str(column).strip().lower()
        target = aliases.get(name)
        if "usage" in name:
            target = "Usage %"
        if target:
            if target in seen:
                raise ValueError(f"More than one input column maps to '{target}'.")
            rename[column] = target
            seen.add(target)
    df.rename(columns=rename, inplace=True)

    missing = [column for column in ("Length", "Width", "Height") if column not in df.columns]
    if missing:
        raise ValueError("Input must include Length/Width, and Height columns.")

    for column in ("Length", "Width", "Height"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
        invalid = df[column].isna() | ~df[column].map(math.isfinite) | (df[column] <= 0)
        if invalid.any():
            raise ValueError(f"Every carton needs a valid positive {column} value.")

    if "Usage %" not in df.columns:
        df["Usage %"] = 1.0
    else:
        df["Usage %"] = pd.to_numeric(df["Usage %"], errors="coerce").fillna(1.0)
        if (df["Usage %"] < 0).any():
            raise ValueError("Usage % values cannot be negative.")
    if "Weight" in df.columns:
        df["Weight"] = pd.to_numeric(df["Weight"], errors="coerce")
        if (df["Weight"].dropna() < 0).any():
            raise ValueError("Weight values cannot be negative.")

    default_key = str(default_flap_state).strip().casefold()
    default_label = FLAP_STATE_LABELS.get(default_key)
    if default_label is None:
        default_label = FLAP_STATES.get(default_key, (None, None))[1]
    if default_label is None:
        raise ValueError(f"Unrecognized global flap state: {default_flap_state}")
    if "Flap State" not in df.columns:
        df["Flap State"] = default_label
    else:
        effective_states = []
        for index, value in df["Flap State"].items():
            if pd.isna(value) or not str(value).strip():
                effective_states.append(default_label)
                continue
            state_key = str(value).strip().casefold()
            if state_key not in FLAP_STATES:
                raise ValueError(
                    f"Unrecognized Flap State at input row {index}: {value}. "
                    f"Choose from {', '.join(state[1] for state in FLAP_STATES.values())}."
                )
            effective_states.append(FLAP_STATES[state_key][1])
        df["Flap State"] = effective_states
    return df


def analyze_cartons(dataframe, selected_configs, options):
    df_input = normalize_cartons(dataframe, options["carton_state"])
    conv_to_inch = 1 / 25.4 if options["metric"] else 1.0
    conv_to_lb = 1 / 0.453592 if options["metric"] else 1.0
    conv_to_display = 25.4 if options["metric"] else 1.0
    df_input["Eng_L"] = df_input["Length"] * conv_to_inch
    df_input["Eng_W"] = df_input["Width"] * conv_to_inch
    df_input["Eng_H"] = df_input["Height"] * conv_to_inch
    if "Weight" in df_input.columns:
        df_input["Eng_Wgt"] = pd.to_numeric(df_input["Weight"], errors="coerce") * conv_to_lb

    overhang_override = options.get("overhang")
    if overhang_override is not None:
        overhang_override *= conv_to_inch

    outputs = {}
    for config_name in selected_configs:
        config = options["manual_config"] if config_name == "Manual Input" else DEFAULT_CONFIGS[config_name]
        config = dict(config)
        if config_name == "Manual Input":
            for key in ("width", "depth", "hgt", "hinge_hgt", "hng_width", "hng_depth"):
                if key in config:
                    value = config[key]
                    config[key] = (
                        [item * conv_to_inch for item in value]
                        if isinstance(value, list)
                        else value * conv_to_inch
                    )
            config["payload"] *= conv_to_lb
        cfg_overhang = (
            overhang_override
            if overhang_override is not None
            else config.get("overhang", 0.0)
        )
        buffer = float(config.get("buffer", 0))
        if not 0 <= buffer < 100:
            raise ValueError(f"Buffer for '{config_name}' must be between 0 and 100.")
        factor = (100.0 - buffer) / 100.0
        shelf_l = config.get("width", 0)
        shelf_w = config.get("depth", 0)
        shelf_h = config.get("hgt", 0)
        hinge_h = config.get("hinge_hgt", 0) * factor
        usable_l = round(shelf_l * factor, 2)
        usable_w = round((shelf_w + cfg_overhang) * factor, 2)
        hinge_l = round(config.get("hng_width", shelf_l) * factor, 2)
        hinge_w = round((config.get("hng_depth", shelf_w) + cfg_overhang) * factor, 2)
        heights = shelf_h if isinstance(shelf_h, list) else [shelf_h]
        shelf_count = len(heights) if isinstance(shelf_h, list) else int(config.get("shelves", 1))
        payload = float(config.get("payload", 0))

        results = df_input.copy()
        if (results["Flap State"] == FLAP_STATES["flaps up"][1]).any():
            results["Height with Flaps"] = results["Height"] + results["Width"].where(
                results["Flap State"] == FLAP_STATES["flaps up"][1], 0
            ) / 2

        capacities, orientations, statuses, buffered_shelves = [], [], [], []
        for _, row in results.iterrows():
            carton_state = FLAP_STATE_CODES[row["Flap State"].casefold()]
            carton_stackable = options["stackable"] and carton_state == "closed"
            carton_max_density = options["max_density"] and carton_state == "closed"
            allow_3d = carton_state == "closed"
            adj_l, adj_w, adj_h = row["Eng_L"], row["Eng_W"], row["Eng_H"]
            if carton_state == "up":
                adj_h += row["Eng_W"] / 2
            elif carton_state == "folded":
                adj_l += 0.25
                adj_w += 0.25
            carton_dims = (adj_l, adj_w, adj_h)
            if isinstance(shelf_h, list):
                total, coords_by_shelf = 0, []
                for height in heights:
                    usable_h = round(height * factor, 2)
                    count, _, coords = calculate_packing(
                        usable_l,
                        usable_w,
                        usable_h,
                        carton_dims,
                        carton_stackable,
                        allow_3d,
                        carton_max_density,
                        options["workflow"],
                    )
                    total += count
                    coords_by_shelf.append((usable_h, count, coords))
                capacity = total
                orientation = "Mixed (See Visuals)"
                status = "Custom Fit" if total else "No Fit"
                shelf_description = (
                    f"{round(usable_l * conv_to_display, 2)}W x "
                    f"{round(usable_w * conv_to_display, 2)}D x "
                    f"{[round(h * factor * conv_to_display, 2) for h in heights]}H"
                )
            else:
                usable_h = round(float(shelf_h) * factor, 2)
                count, orientation, _ = calculate_packing(
                    usable_l,
                    usable_w,
                    usable_h,
                    carton_dims,
                    carton_stackable,
                    allow_3d,
                    carton_max_density,
                    options["workflow"],
                )
                hinge_count, hinge_orientation = 0, "N/A"
                if config.get("hinge_enabled", False) and count == 0:
                    hinge_count, hinge_orientation, _ = calculate_packing(
                        hinge_l,
                        hinge_w,
                        hinge_h,
                        carton_dims,
                        carton_stackable,
                        allow_3d,
                        carton_max_density,
                        options["workflow"],
                    )
                if count:
                    capacity = count * shelf_count
                    status = "Standard Fit"
                    shelf_description = (
                        f"{round(usable_l * conv_to_display, 2)}W x "
                        f"{round(usable_w * conv_to_display, 2)}D x "
                        f"{round(usable_h * conv_to_display, 2)}H"
                    )
                elif hinge_count:
                    capacity = hinge_count
                    orientation = hinge_orientation
                    status = "Hinge Required"
                    shelf_description = (
                        f"{round(hinge_l * conv_to_display, 2)}W x "
                        f"{round(hinge_w * conv_to_display, 2)}D x "
                        f"{round(hinge_h * conv_to_display, 2)}H"
                    )
                else:
                    capacity = 0
                    orientation = "No Fit"
                    status = "No Fit"
                    shelf_description = (
                        f"{round(usable_l * conv_to_display, 2)}W x "
                        f"{round(usable_w * conv_to_display, 2)}D x "
                        f"{round(usable_h * conv_to_display, 2)}H"
                    )

            capacities.append(capacity)
            orientations.append(orientation)
            statuses.append(status)
            buffered_shelves.append(shelf_description)

        results["Total Cartons per Bot"] = capacities
        results["Best Orientation (LxWxH)"] = orientations
        results["Fit Status"] = statuses
        results["Buffered Shelf (WxDxH)"] = buffered_shelves

        if "Eng_Wgt" in results.columns and payload > 0:
            for index, row in results.iterrows():
                weight = row["Eng_Wgt"]
                if row["Total Cartons per Bot"] > 0 and pd.notna(weight) and weight > 0:
                    limit = math.floor(payload / weight)
                    if row["Total Cartons per Bot"] > limit:
                        results.at[index, "Total Cartons per Bot"] = limit
                        results.at[index, "Fit Status"] = "Capped by Weight"

        results["Raw Missions"] = results.apply(
            lambda row: row["Usage %"] / row["Total Cartons per Bot"]
            if row["Total Cartons per Bot"] > 0
            else 0.0,
            axis=1,
        )
        total_missions = results["Raw Missions"].sum()
        results["% of missions"] = (
            results["Raw Missions"] / total_missions if total_missions > 0 else 0.0
        )
        results["Weighted Average"] = (
            results["% of missions"] * results["Total Cartons per Bot"]
        )
        display_columns = [
            "Raw Missions",
            "% of missions",
            "Weighted Average",
            "Best Orientation (LxWxH)",
        ]
        results[display_columns] = results[display_columns].astype(object)
        results.loc[
            results["Total Cartons per Bot"] == 0,
            display_columns,
        ] = "N/A"
        results.drop(
            columns=["Eng_L", "Eng_W", "Eng_H", "Eng_Wgt"],
            errors="ignore",
            inplace=True,
        )
        outputs[config_name] = results

    return outputs


def make_workbook(results):
    summary_rows = []
    for config_name, dataframe in results.items():
        capacity = pd.to_numeric(dataframe["Total Cartons per Bot"], errors="coerce").fillna(0)
        summary_rows.append(
            {
                "Configuration": config_name,
                "Fitted Cartons": int((capacity > 0).sum()),
                "Total Cartons Analyzed": len(dataframe),
                "Sum of Weighted Average": pd.to_numeric(
                    dataframe["Weighted Average"], errors="coerce"
                ).fillna(0).sum(),
            }
        )

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        used_names = {"Summary"}
        for config_name, dataframe in results.items():
            base_name = re.sub(r"[\[\]:*?/\\]", "_", config_name)[:31].strip("'")
            sheet_name = base_name or "Results"
            suffix = 1
            while sheet_name in used_names:
                tail = f"_{suffix}"
                sheet_name = base_name[: 31 - len(tail)] + tail
                suffix += 1
            used_names.add(sheet_name)
            dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output.getvalue()
