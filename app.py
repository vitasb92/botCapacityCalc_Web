import hashlib
import io
import math
import re
import sqlite3

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from aisle_width_engine import (
    AISLE_PROFILES,
    TRAFFIC_PATTERNS,
    calculate_aisle_widths,
)
from aisle_graphic import create_aisle_requirements_png
from capacity_engine import analyze_cartons_with_placements, make_workbook
from config_store import (
    MANUAL_CONFIG_NAME,
    delete_config,
    format_config_label,
    load_aisle_mappings,
    load_aisle_settings,
    load_config_records,
    save_aisle_mappings,
    save_aisle_settings,
    save_config,
)


VISUALIZATION_SCHEMA_VERSION = 2


st.set_page_config(page_title="Bot Capacity Calculator", page_icon="📦", layout="wide")
st.title("Bot Capacity Calculator")
st.caption("Estimate carton capacity for Locus robot shelf configurations.")


def configuration_editor_fields(config, key_prefix):
    left_column, right_column = st.columns(2)
    with left_column:
        width = st.number_input(
            "Shelf width (in)",
            min_value=0.01,
            value=float(config["width"]),
            step=0.1,
            key=f"{key_prefix}-width",
        )
        depth = st.number_input(
            "Shelf depth (in)",
            min_value=0.01,
            value=float(config["depth"]),
            step=0.1,
            key=f"{key_prefix}-depth",
        )
        height_value = config["hgt"]
        if isinstance(height_value, (list, tuple)):
            height_text = ", ".join(str(height) for height in height_value)
        else:
            height_text = str(height_value)
        height_text = st.text_input(
            "Shelf height(s) (in), comma-separated",
            value=height_text,
            key=f"{key_prefix}-hgt",
        )
        shelves = st.number_input(
            "Shelf count (single-height configs)",
            min_value=1,
            value=int(config["shelves"]),
            step=1,
            help="A comma-separated height list represents one shelf at each height.",
            key=f"{key_prefix}-shelves",
        )
        buffer = st.number_input(
            "Buffer (%)",
            min_value=0.0,
            max_value=99.99,
            value=float(config["buffer"]),
            step=0.1,
            key=f"{key_prefix}-buffer",
        )
    with right_column:
        overhang = st.number_input(
            "Overhang (in)",
            min_value=0.0,
            value=float(config.get("overhang", 0.0)),
            step=0.1,
            key=f"{key_prefix}-overhang",
        )
        hinge_enabled = st.checkbox(
            "Enable hinge fallback",
            value=bool(config["hinge_enabled"]),
            help="When off, hinge dimensions are saved as 0. When on, width, depth, and height must be positive.",
            key=f"{key_prefix}-hinge-enabled",
        )
        hinge_width = st.number_input(
            "Hinge width (in)",
            min_value=0.0,
            value=float(
                config.get("hng_width", config["width"]) if hinge_enabled else 0.0
            ),
            step=0.1,
            key=f"{key_prefix}-hng-width",
        )
        hinge_depth = st.number_input(
            "Hinge depth (in)",
            min_value=0.0,
            value=float(
                config.get("hng_depth", config["depth"]) if hinge_enabled else 0.0
            ),
            step=0.1,
            key=f"{key_prefix}-hng-depth",
        )
        hinge_height = st.number_input(
            "Hinge height (in)",
            min_value=0.0,
            value=float(config["hinge_hgt"] if hinge_enabled else 0.0),
            step=0.1,
            key=f"{key_prefix}-hinge-hgt",
        )
        payload = st.number_input(
            "Payload (lb)",
            min_value=0.0,
            value=float(config["payload"]),
            step=0.1,
            key=f"{key_prefix}-payload",
        )

    return {
        "width": width,
        "depth": depth,
        "hgt": height_text,
        "overhang": overhang,
        "shelves": int(shelves),
        "buffer": buffer,
        "hng_width": hinge_width,
        "hng_depth": hinge_depth,
        "hinge_hgt": hinge_height,
        "hinge_enabled": hinge_enabled,
        "payload": payload,
    }


def parse_configuration_fields(fields):
    try:
        heights = [
            float(part.strip())
            for part in fields["hgt"].split(",")
            if part.strip()
        ]
    except ValueError:
        raise ValueError("Shelf heights must be positive numbers separated by commas.") from None
    if not heights:
        raise ValueError("Enter one or more positive shelf heights.")
    parsed = dict(fields)
    parsed["hgt"] = heights if len(heights) > 1 else heights[0]
    return parsed


try:
    config_records = load_config_records()
    aisle_mappings = load_aisle_mappings()
    aisle_settings = load_aisle_settings()
except (sqlite3.Error, OSError, ValueError) as error:
    st.error(f"Could not load configuration data: {error}")
    st.stop()

active_configs = {
    format_config_label(record["name"], record["bot_family"]): record["config"]
    for record in config_records
}
config_families = {
    format_config_label(record["name"], record["bot_family"]): record["bot_family"]
    for record in config_records
}
managed_config_records = {
    format_config_label(record["name"], record["bot_family"]): record
    for record in config_records
    if record["name"].casefold() != MANUAL_CONFIG_NAME.casefold()
}
managed_config_names = list(managed_config_records)
bot_families = sorted(
    {record["bot_family"] for record in config_records if record["bot_family"]},
    key=str.casefold,
)


def configuration_family_editor(label, key_prefix, current_family=None):
    create_family = "Create a new family..."
    family_options = list(bot_families)
    if current_family and current_family not in family_options:
        family_options.append(current_family)
        family_options.sort(key=str.casefold)
    options = family_options + [create_family]
    default_index = (
        options.index(current_family)
        if current_family in options
        else (0 if family_options else len(options) - 1)
    )
    selected_family = st.selectbox(
        label,
        options,
        index=default_index,
        key=f"{key_prefix}-family-selection",
    )
    new_family = st.text_input(
        "New bot family (only used when creating a new family)",
        key=f"{key_prefix}-new-family",
    )
    if selected_family == create_family:
        return new_family
    return selected_family


def format_carton_label(row, row_number):
    name = row.get("Carton Name")
    if pd.isna(name) or not str(name).strip():
        name = row.get("SKU")
    label = f"Carton {row_number + 1}"
    if not pd.isna(name) and str(name).strip():
        label += f" - {name}"
    return label


def format_aisle_distance(distance_mm, metric):
    if metric:
        return f"{distance_mm:.1f} mm"
    return f"{distance_mm / 25.4:.2f} in"

analysis_tab, configuration_tab, aisle_configuration_tab, layout_preview_tab = st.tabs(
    [
        "Capacity analysis",
        "Manage Bot Configurations",
        "Aisle Width Configuration",
        "Layout Previews",
    ]
)
with analysis_tab:
    with st.sidebar:
        st.header("Analysis settings")
        metric = st.toggle("Metric units (mm / kg)")
        length_unit = "mm" if metric else "in"
        weight_unit = "kg" if metric else "lb"

        config_names = [
            format_config_label(record["name"], record["bot_family"])
            for record in config_records
        ]
        selected_configs = st.multiselect(
            "Configurations",
            options=config_names,
            help="Choose one or more shelf configurations. Select Manual Input to define a custom shelf.",
        )
        overhang_text = st.text_input(
            f"Global overhang override ({length_unit})",
            placeholder="Leave blank to use each configuration's value",
        )

        carton_state = st.radio(
            "Carton state",
            options=["Closed/Case", "Flaps Up", "Flaps Down", "No Flaps"],
            horizontal=True,
        )
        state_values = {
            "Closed/Case": "closed",
            "Flaps Up": "up",
            "Flaps Down": "folded",
            "No Flaps": "no_flaps",
        }
        workflow_label = st.radio(
            "Workflow",
            options=["P2P (max fill)", "Picking/putaway (1 deep)"],
            horizontal=False,
        )
        stackable = st.checkbox("Allow carton stacking", value=False, disabled=carton_state != "Closed/Case")
        max_density = st.checkbox("Max density (mixed orientations)", disabled=carton_state != "Closed/Case")

        manual_config = None
        if "Manual Input" in selected_configs:
            st.subheader("Manual shelf")
            manual_width = st.number_input(
                f"Shelf width ({length_unit})", min_value=0.01, value=508.0 if metric else 20.0
            )
            manual_depth = st.number_input(
                f"Shelf depth ({length_unit})", min_value=0.01, value=381.0 if metric else 15.0
            )
            manual_height_text = st.text_input(
                f"Shelf height(s), comma-separated ({length_unit})",
                value="406.4" if metric else "16",
                help="A list of heights models one shelf at each height.",
            )
            manual_shelves = st.number_input("Shelf count", min_value=1, value=1, step=1)
            manual_buffer = st.number_input("Buffer (%)", min_value=0.0, max_value=99.99, value=0.0)
            manual_hinge_height = st.number_input(f"Hinge height ({length_unit})", min_value=0.0, value=0.0)
            manual_hinge = st.checkbox("Enable hinge fallback")
            manual_payload = st.number_input(f"Payload ({weight_unit})", min_value=0.0, value=0.0)
            try:
                manual_heights = [float(part.strip()) for part in manual_height_text.split(",") if part.strip()]
                if not manual_heights or any(height <= 0 for height in manual_heights):
                    raise ValueError
                height_value = manual_heights if len(manual_heights) > 1 else manual_heights[0]
                manual_config = {
                    "width": manual_width,
                    "depth": manual_depth,
                    "hgt": height_value,
                    "overhang": 0.0,
                    "shelves": int(manual_shelves),
                    "buffer": manual_buffer,
                    "hng_width": manual_width,
                    "hng_depth": manual_depth,
                    "hinge_hgt": manual_hinge_height,
                    "hinge_enabled": manual_hinge,
                    "payload": manual_payload,
                }
            except ValueError:
                st.error("Enter one or more positive shelf heights.")

        st.divider()
        optimize = st.checkbox("Find the best configuration across bot families")
        selected_families = []
        if optimize:
            selected_families = st.multiselect(
                "Bot families to compare",
                options=bot_families,
                default=bot_families,
            )

    st.header("Carton data")
    upload_tab, paste_tab, enter_tab = st.tabs(["Upload spreadsheet", "Paste from Excel", "Enter cartons"])

    with upload_tab:
        uploaded_file = st.file_uploader(
            "Upload .xlsx or .csv",
            type=["xlsx", "xls", "csv"],
            help="Required columns: Length, Width, Height. Optional: Carton Name, SKU, Usage %, Weight, Flap State.",
        )

    with paste_tab:
        pasted_data = st.text_area(
            "Paste tab-separated rows from Excel",
            height=160,
            placeholder="Carton name\tLength\tWidth\tHeight\tUsage %\tWeight\tFlap State",
        )

    with enter_tab:
        empty_cartons = pd.DataFrame(
            columns=["Carton Name", "Length", "Width", "Height", "Usage %", "Weight", "Flap State"]
        )
        entered_cartons = st.data_editor(
            empty_cartons,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Carton Name": st.column_config.TextColumn(),
                "Length": st.column_config.NumberColumn(min_value=0.0),
                "Width": st.column_config.NumberColumn(min_value=0.0),
                "Height": st.column_config.NumberColumn(min_value=0.0),
                "Usage %": st.column_config.NumberColumn(min_value=0.0),
                "Weight": st.column_config.NumberColumn(min_value=0.0),
                "Flap State": st.column_config.SelectboxColumn(
                    options=["", "Closed/Case", "Flaps Up", "Flaps Down", "No Flaps"],
                    help="Leave blank to use the global Carton state setting.",
                ),
            },
            key="carton_editor",
        )


    def load_cartons():
        if uploaded_file is not None:
            contents = uploaded_file.getvalue()
            if uploaded_file.name.lower().endswith(".csv"):
                return pd.read_csv(io.BytesIO(contents))
            return pd.read_excel(io.BytesIO(contents))
        if pasted_data.strip():
            try:
                pasted = pd.read_csv(io.StringIO(pasted_data), sep="\t")
                if any(str(column).strip().lower() in {"length", "width", "width (x)", "height"} for column in pasted.columns):
                    return pasted
            except pd.errors.ParserError:
                pass
            pasted = pd.read_csv(io.StringIO(pasted_data), sep="\t", header=None)
            if not 4 <= len(pasted.columns) <= 7:
                raise ValueError("Pasted data must contain 4 to 7 tab-separated columns.")
            pasted.columns = [
                "Carton Name",
                "Length",
                "Width",
                "Height",
                "Usage %",
                "Weight",
                "Flap State",
            ][: len(pasted.columns)]
            return pasted
        if entered_cartons.empty:
            raise ValueError("Upload a spreadsheet, paste rows, or enter at least one carton.")
        populated = entered_cartons.dropna(how="all", subset=["Length", "Width", "Height"])
        if populated.empty:
            raise ValueError("Enter at least one carton with dimensions.")
        return populated


    def current_carton_input_key():
        if uploaded_file is not None:
            contents = uploaded_file.getvalue()
            return (
                "upload",
                uploaded_file.name,
                hashlib.sha256(contents).hexdigest(),
            )
        if pasted_data.strip():
            return ("paste", hashlib.sha256(pasted_data.encode("utf-8")).hexdigest())
        if not entered_cartons.empty:
            table_hash = pd.util.hash_pandas_object(entered_cartons, index=True).values.tobytes()
            return ("manual", table_hash)
        return None


    def get_carton_data():
        input_key = current_carton_input_key()
        if input_key is None:
            st.session_state.pop("carton_input_key", None)
            st.session_state.pop("carton_dataframe", None)
            return None
        if input_key != st.session_state.get("carton_input_key"):
            st.session_state["carton_dataframe"] = load_cartons()
            st.session_state["carton_input_key"] = input_key
        return st.session_state["carton_dataframe"]


    def make_fit_figure(shelf, placements, metric, carton_visual):
        display_factor = 25.4 if metric else 1.0
        unit = "mm" if metric else "in"
        shelf_width = shelf["width"] * display_factor
        shelf_depth = shelf["depth"] * display_factor
        shelf_height = shelf["height"] * display_factor
        flap_state = carton_visual["flap_state"]
        body_height = carton_visual["carton_body_dimensions"][2] * display_factor
        flap_extension = carton_visual["flap_extension"] * display_factor
        flap_margin = carton_visual["flap_margin"] * display_factor

        figure = go.Figure()
        corners = [
            (0, 0, 0),
            (shelf_width, 0, 0),
            (shelf_width, shelf_depth, 0),
            (0, shelf_depth, 0),
            (0, 0, shelf_height),
            (shelf_width, 0, shelf_height),
            (shelf_width, shelf_depth, shelf_height),
            (0, shelf_depth, shelf_height),
        ]
        edge_pairs = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        shelf_x, shelf_y, shelf_z = [], [], []
        for start, end in edge_pairs:
            shelf_x.extend([corners[start][0], corners[end][0], None])
            shelf_y.extend([corners[start][1], corners[end][1], None])
            shelf_z.extend([corners[start][2], corners[end][2], None])
        figure.add_trace(
            go.Scatter3d(
                x=shelf_x,
                y=shelf_y,
                z=shelf_z,
                mode="lines",
                name="Usable shelf",
                line={"color": "#334155", "width": 5},
                hoverinfo="skip",
            )
        )

        physical_width = shelf.get("physical_width", shelf["width"]) * display_factor
        core_depth = shelf.get("core_depth", shelf["depth"]) * display_factor
        overhang_depth = shelf.get("overhang_depth", 0.0) * display_factor

        def add_shelf_region(name, start_depth, end_depth, color):
            if end_depth <= start_depth:
                return
            figure.add_trace(
                go.Mesh3d(
                    x=[0, physical_width, physical_width, 0],
                    y=[start_depth, start_depth, end_depth, end_depth],
                    z=[0, 0, 0, 0],
                    i=[0, 0],
                    j=[1, 2],
                    k=[2, 3],
                    color=color,
                    opacity=0.55,
                    flatshading=True,
                    name=name,
                    hoverinfo="skip",
                )
            )

        add_shelf_region("Core shelf", 0, core_depth, "#64748b")
        add_shelf_region(
            "Overhang extension",
            core_depth,
            core_depth + overhang_depth,
            "#14b8a6",
        )

        body_mesh = {"x": [], "y": [], "z": [], "i": [], "j": [], "k": []}
        flap_mesh = {"x": [], "y": [], "z": [], "i": [], "j": [], "k": []}
        body_edge_x, body_edge_y, body_edge_z = [], [], []
        flap_edge_x, flap_edge_y, flap_edge_z = [], [], []
        box_edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        side_and_bottom_faces = [
            (0, 1, 2), (0, 2, 3),
            (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
            (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
        ]

        def add_mesh_geometry(mesh, points, faces):
            base = len(mesh["x"])
            mesh["x"].extend(point[0] for point in points)
            mesh["y"].extend(point[1] for point in points)
            mesh["z"].extend(point[2] for point in points)
            for face in faces:
                mesh["i"].append(base + face[0])
                mesh["j"].append(base + face[1])
                mesh["k"].append(base + face[2])

        def add_edges(points, pairs, edge_x, edge_y, edge_z):
            for first, second in pairs:
                edge_x.extend([points[first][0], points[second][0], None])
                edge_y.extend([points[first][1], points[second][1], None])
                edge_z.extend([points[first][2], points[second][2], None])

        def add_flap_panel(points):
            add_mesh_geometry(flap_mesh, points, [(0, 1, 2), (0, 2, 3)])
            add_edges(points, [(0, 1), (1, 2), (2, 3), (3, 0)], flap_edge_x, flap_edge_y, flap_edge_z)

        for placement in placements:
            x, y, z, length, width, fit_height = (
                placement[key] * display_factor for key in ("x", "y", "z", "l", "w", "h")
            )
            if flap_state == "folded":
                body_length = length - flap_margin
                body_width = width - flap_margin
                body_depth = fit_height
                body_x = x + flap_margin / 2
                body_y = y + flap_margin / 2
            else:
                body_length = length
                body_width = width
                body_depth = body_height if flap_state == "up" else fit_height
                body_x = x
                body_y = y

            box = [
                (body_x, body_y, z),
                (body_x + body_length, body_y, z),
                (body_x + body_length, body_y + body_width, z),
                (body_x, body_y + body_width, z),
                (body_x, body_y, z + body_depth),
                (body_x + body_length, body_y, z + body_depth),
                (body_x + body_length, body_y + body_width, z + body_depth),
                (body_x, body_y + body_width, z + body_depth),
            ]
            body_faces = side_and_bottom_faces
            if flap_state == "no_flaps":
                body_faces = body_faces + [(4, 5, 6), (4, 6, 7)]
            add_mesh_geometry(body_mesh, box, body_faces)
            add_edges(box, box_edges, body_edge_x, body_edge_y, body_edge_z)

            top = z + body_depth
            if flap_state == "closed":
                half_width = body_width / 2
                add_flap_panel(
                    [
                        (body_x, body_y, top),
                        (body_x + body_length, body_y, top),
                        (body_x + body_length, body_y + half_width, top),
                        (body_x, body_y + half_width, top),
                    ]
                )
                add_flap_panel(
                    [
                        (body_x, body_y + half_width, top),
                        (body_x + body_length, body_y + half_width, top),
                        (body_x + body_length, body_y + body_width, top),
                        (body_x, body_y + body_width, top),
                    ]
                )
            elif flap_state == "up" and flap_extension > 0:
                flap_top = top + flap_extension
                add_flap_panel(
                    [
                        (body_x, body_y, top),
                        (body_x + body_length, body_y, top),
                        (body_x + body_length, body_y, flap_top),
                        (body_x, body_y, flap_top),
                    ]
                )
                add_flap_panel(
                    [
                        (body_x, body_y + body_width, top),
                        (body_x, body_y + body_width, flap_top),
                        (body_x + body_length, body_y + body_width, flap_top),
                        (body_x + body_length, body_y + body_width, top),
                    ]
                )
                add_flap_panel(
                    [
                        (body_x, body_y, top),
                        (body_x, body_y, flap_top),
                        (body_x, body_y + body_width, flap_top),
                        (body_x, body_y + body_width, top),
                    ]
                )
                add_flap_panel(
                    [
                        (body_x + body_length, body_y, top),
                        (body_x + body_length, body_y + body_width, top),
                        (body_x + body_length, body_y + body_width, flap_top),
                        (body_x + body_length, body_y, flap_top),
                    ]
                )
            elif flap_state == "folded":
                front_drop = min(body_depth, body_width / 2)
                side_drop = min(body_depth, body_length / 2)
                add_flap_panel(
                    [
                        (body_x, y, top - front_drop),
                        (body_x + body_length, y, top - front_drop),
                        (body_x + body_length, y, top),
                        (body_x, y, top),
                    ]
                )
                add_flap_panel(
                    [
                        (body_x, y + width, top - front_drop),
                        (body_x, y + width, top),
                        (body_x + body_length, y + width, top),
                        (body_x + body_length, y + width, top - front_drop),
                    ]
                )
                add_flap_panel(
                    [
                        (x, body_y, top - side_drop),
                        (x, body_y, top),
                        (x, body_y + body_width, top),
                        (x, body_y + body_width, top - side_drop),
                    ]
                )
                add_flap_panel(
                    [
                        (x + length, body_y, top - side_drop),
                        (x + length, body_y + body_width, top - side_drop),
                        (x + length, body_y + body_width, top),
                        (x + length, body_y, top),
                    ]
                )

        if placements:
            figure.add_trace(
                go.Mesh3d(
                    **body_mesh,
                    color="#d89a5b",
                    opacity=0.82,
                    flatshading=True,
                    name="Carton body",
                    hoverinfo="skip",
                )
            )
            figure.add_trace(
                go.Scatter3d(
                    x=body_edge_x,
                    y=body_edge_y,
                    z=body_edge_z,
                    mode="lines",
                    name="Carton body outline",
                    line={"color": "#704214", "width": 2},
                    hoverinfo="skip",
                )
            )
            if flap_mesh["x"]:
                figure.add_trace(
                    go.Mesh3d(
                        **flap_mesh,
                        color="#43b8a7",
                        opacity=0.78,
                        flatshading=True,
                        name="Flaps",
                        hoverinfo="skip",
                    )
                )
                figure.add_trace(
                    go.Scatter3d(
                        x=flap_edge_x,
                        y=flap_edge_y,
                        z=flap_edge_z,
                        mode="lines",
                        name="Flap panel outlines",
                        line={"color": "#087f75", "width": 3},
                        hoverinfo="skip",
                    )
                )

        figure.update_layout(
            scene={
                "xaxis_title": f"Width ({unit})",
                "yaxis_title": f"Depth ({unit})",
                "zaxis_title": f"Height ({unit})",
                "aspectmode": "data",
            },
            margin={"l": 0, "r": 0, "t": 10, "b": 0},
            legend={"orientation": "h"},
            height=520,
        )
        return figure


    try:
        carton_dataframe = get_carton_data()
        if carton_dataframe is not None:
            st.metric("Cartons to analyze", f"{len(carton_dataframe):,}")
    except (ValueError, KeyError, OSError, pd.errors.ParserError) as error:
        carton_dataframe = None
        st.error(f"Could not read the carton data: {error}")

    run_analysis = st.button("Run capacity analysis", type="primary", use_container_width=True)

    st.session_state.setdefault("analysis_results", None)
    st.session_state.setdefault("analysis_summary", None)
    st.session_state.setdefault("analysis_visuals", None)
    st.session_state.setdefault("analysis_visual_schema_version", 0)
    st.session_state.setdefault("analysis_is_optimized", False)
    st.session_state.setdefault("analysis_metric", metric)

    if run_analysis:
        st.session_state["analysis_results"] = None
        st.session_state["analysis_summary"] = None
        st.session_state["analysis_visuals"] = None
        st.session_state["analysis_visual_schema_version"] = 0
        st.session_state["analysis_is_optimized"] = False
        st.session_state["analysis_metric"] = metric
        st.session_state.pop("configuration_details_selector", None)
        st.session_state.pop("carton_fit_selector", None)
        if optimize:
            configs_to_run = [
                name
                for name in config_names
                if name != MANUAL_CONFIG_NAME
                and config_families[name] in selected_families
            ]
        else:
            configs_to_run = selected_configs

        if not configs_to_run:
            st.error("Select at least one configuration or bot family.")
        elif "Manual Input" in configs_to_run and manual_config is None:
            st.error("Correct the manual shelf height before running the analysis.")
        elif carton_dataframe is None:
            st.error("Upload, paste, or enter carton information before running the analysis.")
        else:
            try:
                options = {
                    "metric": metric,
                    "carton_state": state_values[carton_state],
                    "stackable": stackable,
                    "max_density": max_density,
                    "workflow": "pick_put" if workflow_label.startswith("Picking") else "p2p",
                    "overhang": float(overhang_text) if overhang_text.strip() else None,
                    "manual_config": manual_config,
                }
                with st.spinner("Running capacity analysis..."):
                    results, visuals = analyze_cartons_with_placements(
                        carton_dataframe, configs_to_run, options, configs=active_configs
                    )
                summary_rows = []
                for config_name, result in results.items():
                    capacity = pd.to_numeric(result["Total Cartons per Bot"], errors="coerce").fillna(0)
                    weighted_average = pd.to_numeric(result["Weighted Average"], errors="coerce").fillna(0)
                    summary_rows.append(
                        {
                            "Configuration": config_name,
                            "Fitted Cartons": int((capacity > 0).sum()),
                            "Total Cartons Analyzed": len(result),
                            "Sum of Weighted Average": weighted_average.sum(),
                        }
                    )
                summary = pd.DataFrame(summary_rows).sort_values(
                    ["Fitted Cartons", "Sum of Weighted Average"], ascending=False
                )

                st.session_state["analysis_results"] = results
                st.session_state["analysis_summary"] = summary
                st.session_state["analysis_visuals"] = visuals
                st.session_state["analysis_visual_schema_version"] = VISUALIZATION_SCHEMA_VERSION
                st.session_state["analysis_is_optimized"] = optimize
            except (ValueError, KeyError, OSError, pd.errors.ParserError) as error:
                st.error(str(error))
            except Exception as error:
                st.exception(error)

    if st.session_state["analysis_results"] is not None:
        results = st.session_state["analysis_results"]
        summary = st.session_state["analysis_summary"]

        if st.session_state["analysis_is_optimized"]:
            st.subheader("Optimization ranking")
            st.success(f"Best configuration: **{summary.iloc[0]['Configuration']}**")
        else:
            st.subheader("Results")
        st.dataframe(summary, use_container_width=True, hide_index=True)

        chart_data = summary.sort_values("Sum of Weighted Average", ascending=True)
        chart = px.bar(
            chart_data,
            x="Sum of Weighted Average",
            y="Configuration",
            orientation="h",
            title="Preview weighted average cartons per bot",
        )
        st.plotly_chart(chart, use_container_width=True)

        detail_config = st.selectbox(
            "Configuration details",
            list(results),
            key="configuration_details_selector",
        )
        detail_results = results[detail_config]
        st.dataframe(detail_results, use_container_width=True, hide_index=True)

        st.subheader("Aisle width recommendations")
        aisle_graphic_data = None
        aisle_mapping = aisle_mappings.get(detail_config)
        if aisle_mapping is None:
            st.info(
                f"No aisle profile is mapped to '{detail_config}'. "
                "Add a mapping in Manage Bot Configurations to calculate aisle widths."
            )
        else:
            st.caption(
                f"Mapped profile: {aisle_mapping['aisle_profile']} · "
                f"Robot width: {aisle_mapping['robot_width_mm']:g} mm. "
                "Carton Length is treated as width (X), Width as depth (Y); "
                "flaps-up height includes the flap extension."
            )
            if AISLE_PROFILES[aisle_mapping["aisle_profile"]]["type"] == "VECTOR":
                st.caption(
                    "Vector aisle recommendations use the editable profile requirements; "
                    "the mapped robot width is recorded for reference."
                )

            input_to_mm = (
                1.0
                if st.session_state.get("analysis_metric", metric)
                else 25.4
            )
            aisle_rows = []
            aisle_calculations = []
            try:
                for row_number, (_, carton) in enumerate(detail_results.iterrows()):
                    carton_height = carton["Height"]
                    if (
                        "Height with Flaps" in carton.index
                        and carton.get("Flap State") == "Flaps Up"
                    ):
                        carton_height = carton["Height with Flaps"]
                    calculation = calculate_aisle_widths(
                        aisle_mapping["aisle_profile"],
                        aisle_mapping["robot_width_mm"],
                        float(carton["Length"]) * input_to_mm,
                        float(carton["Width"]) * input_to_mm,
                        float(carton_height) * input_to_mm,
                        aisle_settings=aisle_settings,
                    )
                    label = format_carton_label(carton, row_number)
                    aisle_calculations.append((label, calculation))
                    row_values = {
                        "Carton": label,
                        "Largest optimal aisle need": "",
                    }
                    for traffic_key, traffic_label in zip(
                        ("one_way", "two_way", "three_way"), TRAFFIC_PATTERNS
                    ):
                        row_values[f"{traffic_label} minimum"] = format_aisle_distance(
                            calculation["minimum_mm"][traffic_key], metric
                        )
                        row_values[f"{traffic_label} optimal"] = format_aisle_distance(
                            calculation["optimal_mm"][traffic_key], metric
                        )
                    row_values["Warnings"] = "; ".join(calculation["warnings"])
                    aisle_rows.append(row_values)
            except (KeyError, TypeError, ValueError) as error:
                st.error(f"Could not calculate aisle recommendations: {error}")
            else:
                if not aisle_calculations:
                    st.info("No carton rows are available for aisle-width analysis.")
                else:
                    limiting_rows = []
                    graphic_scenarios = []
                    limiting_patterns = {}
                    for traffic_key, traffic_label in zip(
                        ("one_way", "two_way", "three_way"), TRAFFIC_PATTERNS
                    ):
                        minimum_index = max(
                            range(len(aisle_calculations)),
                            key=lambda index: aisle_calculations[index][1]["minimum_mm"][
                                traffic_key
                            ],
                        )
                        optimal_width = max(
                            calculation["optimal_mm"][traffic_key]
                            for _, calculation in aisle_calculations
                        )
                        optimal_indexes = [
                            index
                            for index, (_, calculation) in enumerate(aisle_calculations)
                            if math.isclose(
                                calculation["optimal_mm"][traffic_key],
                                optimal_width,
                                rel_tol=0.0,
                                abs_tol=1e-9,
                            )
                        ]
                        minimum_carton, minimum_calculation = aisle_calculations[minimum_index]
                        optimal_cartons = [
                            aisle_calculations[index][0] for index in optimal_indexes
                        ]
                        optimal_calculation = aisle_calculations[optimal_indexes[0]][1]
                        graphic_scenarios.append(
                            {
                                "traffic_pattern": traffic_label,
                                "minimum_width_mm": minimum_calculation["minimum_mm"][
                                    traffic_key
                                ],
                                "minimum_carton": minimum_carton,
                                "optimal_width_mm": optimal_calculation["optimal_mm"][
                                    traffic_key
                                ],
                                "optimal_carton": "; ".join(optimal_cartons),
                            }
                        )
                        for index in optimal_indexes:
                            limiting_patterns.setdefault(index, []).append(traffic_label)
                        limiting_rows.append(
                            {
                                "Traffic pattern": traffic_label,
                                "Minimum limiting carton": minimum_carton,
                                "Minimum aisle width": format_aisle_distance(
                                    minimum_calculation["minimum_mm"][traffic_key], metric
                                ),
                                "Optimal limiting carton": "; ".join(optimal_cartons),
                                "Optimal aisle width": format_aisle_distance(
                                    optimal_calculation["optimal_mm"][traffic_key], metric
                                ),
                            }
                        )
                    for index, traffic_labels in limiting_patterns.items():
                        aisle_rows[index]["Largest optimal aisle need"] = "; ".join(
                            traffic_labels
                        )
                    aisle_dataframe = pd.DataFrame(aisle_rows)
                    aisle_dataframe = aisle_dataframe.style.apply(
                        lambda row: (
                            ["background-color: #fff3cd; font-weight: bold;"]
                            * len(row)
                            if row["Largest optimal aisle need"]
                            else [""] * len(row)
                        ),
                        axis=1,
                    )
                    st.caption(
                        "Highlighted cartons set the largest optimal aisle width for the listed traffic patterns."
                    )
                    st.dataframe(
                        aisle_dataframe,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.markdown("**Limiting carton by traffic pattern**")
                    st.dataframe(
                        pd.DataFrame(limiting_rows),
                        use_container_width=True,
                        hide_index=True,
                    )
                    warnings = sorted(
                        {
                            warning
                            for _, calculation in aisle_calculations
                            for warning in calculation["warnings"]
                        }
                    )
                    if warnings:
                        st.warning("Review the aisle-model warnings: " + " ".join(warnings))
                    aisle_graphic_data = create_aisle_requirements_png(
                        detail_config,
                        aisle_mapping["aisle_profile"],
                        aisle_mapping["robot_width_mm"],
                        graphic_scenarios,
                        metric=metric,
                    )

        visuals = st.session_state["analysis_visuals"]
        config_visuals = visuals.get(detail_config) if isinstance(visuals, dict) else None
        visuals_are_current = (
            st.session_state["analysis_visual_schema_version"] == VISUALIZATION_SCHEMA_VERSION
            and isinstance(config_visuals, list)
            and len(config_visuals) == len(detail_results)
            and all(
                isinstance(visual, dict)
                and {
                    "flap_state",
                    "carton_body_dimensions",
                    "flap_extension",
                    "flap_margin",
                    "shelves",
                }.issubset(visual)
                and all(
                    {
                        "physical_width",
                        "core_depth",
                        "overhang_depth",
                    }.issubset(shelf)
                    for shelf in visual["shelves"]
                )
                for visual in config_visuals
            )
        )
        if not visuals_are_current:
            st.info(
                "These saved results use an older 3D visualization format. "
                "Your capacity results are still available; rerun the analysis to refresh the shelf and overhang view."
            )
        else:
            carton_index = st.selectbox(
                "Carton fit",
                options=list(range(len(detail_results))),
                format_func=lambda row_number: format_carton_label(
                    detail_results.iloc[row_number], row_number
                ),
                key="carton_fit_selector",
            )
            selected_row = detail_results.iloc[carton_index]
            selected_visual = config_visuals[carton_index]
            st.subheader("3D carton fit")
            st.caption(
                f"{selected_row['Fit Status']} · "
                f"{selected_row['Total Cartons per Bot']} cartons per bot · "
                f"{selected_row['Flap State']}"
            )
            st.caption(
                "Tan shows the carton body; teal shows flap panels. "
                "Slate shows the core shelf and teal shows its overhang. "
                "The piece-level view is illustrative and does not change fit calculations."
            )
            if not selected_visual["shelves"]:
                st.info("No shelf geometry is available for this configuration.")
            for shelf_number, shelf in enumerate(selected_visual["shelves"], start=1):
                if shelf.get("hinge"):
                    shelf_label = "Hinge fit"
                elif "identical_shelves" in shelf:
                    shelf_label = f"Representative shelf (1 of {shelf['identical_shelves']} identical)"
                elif len(selected_visual["shelves"]) > 1:
                    shelf_label = f"Shelf {shelf_number}"
                else:
                    shelf_label = "Shelf"
                st.markdown(f"**{shelf_label}**")
                display_factor = 25.4 if metric else 1.0
                shelf_dimensions = " x ".join(
                    f"{shelf[dimension] * display_factor:.2f}"
                    for dimension in ("width", "depth", "height")
                )
                st.caption(
                    f"Usable shelf (W x D x H): {shelf_dimensions} "
                    f"{'mm' if metric else 'in'}"
                )
                display_unit = "mm" if metric else "in"
                core_depth = shelf["core_depth"] * display_factor
                overhang_depth = shelf["overhang_depth"] * display_factor
                total_physical_depth = core_depth + overhang_depth
                st.caption(
                    f"Physical depth — core shelf: {core_depth:.2f} {display_unit}; "
                    f"overhang: {overhang_depth:.2f} {display_unit}; "
                    f"total: {total_physical_depth:.2f} {display_unit}"
                )
                st.plotly_chart(
                    make_fit_figure(shelf, shelf["placements"], metric, selected_visual),
                    use_container_width=True,
                    key=f"carton-fit-{detail_config}-{carton_index}-{shelf_number}",
                )
                if not shelf["placements"]:
                    st.caption("No cartons fit on this shelf.")
        st.download_button(
            "Download Excel results",
            data=make_workbook(results),
            file_name="Bot_Capacity_Results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            on_click="ignore",
        )
        if aisle_graphic_data is not None:
            st.subheader("Aisle requirements image")
            st.image(aisle_graphic_data, use_container_width=True)
            safe_config_name = re.sub(
                r"[^A-Za-z0-9_-]+", "_", detail_config
            ).strip("_")[:60]
            st.download_button(
                "Download aisle requirements PNG",
                data=aisle_graphic_data,
                file_name=f"Aisle_Requirements_{safe_config_name}.png",
                mime="image/png",
                on_click="ignore",
                key="download-aisle-requirements-image",
            )

    st.caption("Calculations run on the hosted service. Avoid uploading data that your organization does not permit to be processed there.")

with configuration_tab:
    st.header("Manage bot configurations")
    st.caption(
        "Changes are shared with all users and apply to new capacity calculations after saving. "
        "Manual Input remains a separate user-defined shelf."
    )
    notice = st.session_state.pop("configuration_notice", None)
    if notice:
        st.success(notice)

    configuration_rows = [
        {
            "Configuration Name": record["name"],
            "Bot Family": record["bot_family"],
            **record["config"],
        }
        for record in config_records
        if record["name"].casefold() != MANUAL_CONFIG_NAME.casefold()
    ]
    st.dataframe(
        pd.DataFrame(configuration_rows).sort_values(
            ["Bot Family", "Configuration Name"],
            key=lambda column: column.str.casefold(),
            ignore_index=True,
        ),
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Add Configuration", expanded=False):
        with st.form("add_bot_configuration"):
            new_name = st.text_input("Configuration name", key="add-config-name")
            new_family = configuration_family_editor("Bot family", "add-config")
            new_fields = configuration_editor_fields(
                {
                    "width": 20.0,
                    "depth": 15.0,
                    "hgt": 16.0,
                    "shelves": 1,
                    "buffer": 0.0,
                    "overhang": 0.0,
                    "hng_width": 0.0,
                    "hng_depth": 0.0,
                    "hinge_hgt": 0.0,
                    "hinge_enabled": False,
                    "payload": 0.0,
                },
                "add-config",
            )
            add_submitted = st.form_submit_button("Add configuration", type="primary")
        if add_submitted:
            try:
                save_config(new_name, new_family, parse_configuration_fields(new_fields))
            except (ValueError, sqlite3.Error, OSError) as error:
                st.error(f"Could not add configuration: {error}")
            else:
                st.session_state["configuration_notice"] = (
                    f"Added '{format_config_label(new_name.strip(), new_family.strip())}'."
                )
                st.session_state.pop("aisle-mapping-editor", None)
                st.rerun()

    if managed_config_names:
        with st.expander("Edit or Delete Configuration", expanded=False):
            selected_label = st.selectbox(
                "Configuration to edit",
                managed_config_names,
                key="managed_config_selection",
            )
            selected_record = managed_config_records[selected_label]
            current_config = selected_record["config"]
            with st.form("edit_bot_configuration"):
                edited_name = st.text_input(
                    "Configuration name",
                    value=selected_record["name"],
                    key=f"edit-config-name-{selected_label}",
                )
                edited_family = configuration_family_editor(
                    "Bot family",
                    f"edit-config-{selected_label}",
                    current_family=selected_record["bot_family"],
                )
                edited_fields = configuration_editor_fields(
                    current_config, f"edit-config-{selected_label}"
                )
                edit_submitted = st.form_submit_button("Save changes", type="primary")
            if edit_submitted:
                try:
                    save_config(
                        edited_name,
                        edited_family,
                        parse_configuration_fields(edited_fields),
                        original_name=selected_record["name"],
                        original_bot_family=selected_record["bot_family"],
                    )
                except (ValueError, sqlite3.Error, OSError) as error:
                    st.error(f"Could not save configuration: {error}")
                else:
                    st.session_state["configuration_notice"] = (
                        "Saved "
                        f"'{format_config_label(edited_name.strip(), edited_family.strip())}'."
                    )
                    st.session_state.pop("aisle-mapping-editor", None)
                    st.rerun()

            confirmed_delete = st.checkbox(
                f"Confirm permanent deletion of '{selected_label}'",
                key=f"confirm-delete-{selected_label}",
            )
            if st.button("Delete configuration", disabled=not confirmed_delete):
                try:
                    delete_config(
                        selected_record["name"],
                        selected_record["bot_family"],
                    )
                except (ValueError, sqlite3.Error, OSError) as error:
                    st.error(f"Could not delete configuration: {error}")
                else:
                    st.session_state["configuration_notice"] = (
                        f"Deleted '{selected_label}'."
                    )
                    st.session_state.pop("aisle-mapping-editor", None)
                    st.rerun()
    else:
        st.info("Add a bot configuration to enable editing and analysis.")

    st.subheader("Aisle width mappings")
    st.caption(
        "Map each capacity configuration to an aisle profile. Robot width is stored in mm; "
        "Origin profiles require their exact catalog width. Vector profiles require a manually "
        "entered width for reference; their aisle requirements are editable on the Aisle Width Configuration page."
    )
    aisle_mapping_rows = []
    for label, record in managed_config_records.items():
        mapping = aisle_mappings.get(label, {})
        aisle_mapping_rows.append(
            {
                "Configuration Name": record["name"],
                "Bot Family": record["bot_family"],
                "Aisle Profile": mapping.get("aisle_profile", ""),
                "Robot width (mm)": mapping.get("robot_width_mm"),
            }
        )
    aisle_mapping_editor = st.data_editor(
        pd.DataFrame(
            aisle_mapping_rows,
            columns=[
                "Configuration Name",
                "Bot Family",
                "Aisle Profile",
                "Robot width (mm)",
            ],
        ),
        key="aisle-mapping-editor",
        use_container_width=True,
        hide_index=True,
        disabled=["Configuration Name", "Bot Family"],
        column_config={
            "Aisle Profile": st.column_config.SelectboxColumn(
                options=[""] + list(AISLE_PROFILES),
                help="Choose the aisle profile that corresponds to this robot configuration.",
            ),
            "Robot width (mm)": st.column_config.NumberColumn(
                min_value=0.01,
                step=1.0,
                format="%.1f",
                help="Required for all mappings. Origin widths must match the selected profile's catalog width.",
            ),
        },
    )
    if st.button("Save aisle mappings", type="primary"):
        mappings_to_save = []
        for row in aisle_mapping_editor.to_dict("records"):
            aisle_profile = str(row.get("Aisle Profile", "") or "").strip()
            if not aisle_profile:
                continue
            mappings_to_save.append(
                {
                    "name": row["Configuration Name"],
                    "bot_family": row["Bot Family"],
                    "aisle_profile": aisle_profile,
                    "robot_width_mm": row["Robot width (mm)"],
                }
            )
        try:
            save_aisle_mappings(mappings_to_save)
        except (ValueError, sqlite3.Error, OSError) as error:
            st.error(f"Could not save aisle mappings: {error}")
        else:
            st.session_state["configuration_notice"] = "Saved aisle width mappings."
            st.session_state.pop("aisle-mapping-editor", None)
            st.rerun()

with aisle_configuration_tab:
    st.header("Aisle width requirements")
    st.caption(
        "Edit the numeric requirements for the existing aisle profiles. Profile names, robot "
        "types, hardware widths, formulas, and bot-to-profile mappings remain fixed. "
        "Saved values are shared and apply to subsequent aisle calculations."
    )

    profile_rows = []
    for profile_key, profile in aisle_settings["profiles"].items():
        row = {
            "Aisle Profile": profile_key,
            "Robot type": profile["type"],
            "Hardware width (mm)": profile["hardware_width_mm"],
            "Tray radius (mm)": None,
            "1-way minimum (mm)": None,
            "2-way minimum (mm)": None,
            "3-way minimum (mm)": None,
            "1-way optimal (mm)": None,
            "2-way optimal (mm)": None,
            "3-way optimal (mm)": None,
        }
        if profile["type"] == "VECTOR":
            for index, traffic_label in enumerate(("1-way", "2-way", "3-way")):
                row[f"{traffic_label} minimum (mm)"] = profile["minimum_mm"][index]
                row[f"{traffic_label} optimal (mm)"] = profile["optimal_mm"][index]
        else:
            row["Tray radius (mm)"] = profile["tray_radius_mm"]
        profile_rows.append(row)

    profile_editor = st.data_editor(
        pd.DataFrame(profile_rows),
        key="aisle-requirements-profile-editor",
        use_container_width=True,
        hide_index=True,
        disabled=["Aisle Profile", "Robot type", "Hardware width (mm)"],
        column_config={
            "Tray radius (mm)": st.column_config.NumberColumn(
                min_value=0.01,
                step=1.0,
                format="%.1f",
                help="Editable for Origin profiles; Vector profiles use fixed aisle values below.",
            ),
            **{
                f"{traffic_label} {kind} (mm)": st.column_config.NumberColumn(
                    min_value=0.01,
                    step=1.0,
                    format="%.1f",
                    help="Editable for Vector profiles; Origin widths are calculated from the shared model settings.",
                )
                for traffic_label in ("1-way", "2-way", "3-way")
                for kind in ("minimum", "optimal")
            },
        },
    )

    origin_field_labels = {
        "Mast to center (mm)": "mast_to_center_mm",
        "Front edge to mast (mm)": "front_edge_to_mast_mm",
        "Buffer (mm)": "buffer_mm",
        "Optimal addition (mm)": "optimal_add_mm",
        "Maximum carton height (mm)": "max_container_height_mm",
        "Baseline depth (mm)": "baseline_depth_mm",
    }
    origin_rows = [
        {
            "Origin model": robot_type,
            **{
                label: constants[field]
                for label, field in origin_field_labels.items()
            },
        }
        for robot_type, constants in aisle_settings["origin_constants"].items()
    ]
    origin_editor = st.data_editor(
        pd.DataFrame(origin_rows),
        key="aisle-requirements-origin-editor",
        use_container_width=True,
        hide_index=True,
        disabled=["Origin model"],
        column_config={
            label: st.column_config.NumberColumn(
                min_value=0.0 if field in ("buffer_mm", "optimal_add_mm") else 0.01,
                step=1.0,
                format="%.5f" if field == "front_edge_to_mast_mm" else "%.1f",
            )
            for label, field in origin_field_labels.items()
        },
    )
    one_way_minimum = st.number_input(
        "Minimum one-way aisle width (mm)",
        min_value=0.01,
        value=float(aisle_settings["minimum_one_way_mm"]),
        step=1.0,
        key="aisle-one-way-minimum",
        help="Floor applied to Origin one-way recommendations; it does not change Vector catalog values.",
    )

    if st.button("Save aisle-width requirements", type="primary"):
        updated_settings = {
            "profiles": {
                profile_key: dict(profile)
                for profile_key, profile in aisle_settings["profiles"].items()
            },
            "origin_constants": {
                robot_type: dict(constants)
                for robot_type, constants in aisle_settings["origin_constants"].items()
            },
            "minimum_one_way_mm": one_way_minimum,
        }
        for row in profile_editor.to_dict("records"):
            profile_key = row["Aisle Profile"]
            profile = updated_settings["profiles"][profile_key]
            if profile["type"] == "VECTOR":
                profile["minimum_mm"] = tuple(
                    row[f"{traffic_label} minimum (mm)"]
                    for traffic_label in ("1-way", "2-way", "3-way")
                )
                profile["optimal_mm"] = tuple(
                    row[f"{traffic_label} optimal (mm)"]
                    for traffic_label in ("1-way", "2-way", "3-way")
                )
            else:
                profile["tray_radius_mm"] = row["Tray radius (mm)"]

        for row in origin_editor.to_dict("records"):
            robot_type = row["Origin model"]
            updated_settings["origin_constants"][robot_type] = {
                field: row[label]
                for label, field in origin_field_labels.items()
            }

        try:
            save_aisle_settings(updated_settings)
        except (ValueError, sqlite3.Error, OSError) as error:
            st.error(f"Could not save aisle-width requirements: {error}")
        else:
            st.success("Saved aisle-width requirements.")
            st.rerun()

with layout_preview_tab:
    st.header("Preview alternative page layouts")
    st.info(
        "Visual-only samples with illustrative data. The live calculator and its results are unchanged."
    )
    layout_choice = st.radio(
        "Choose a layout preview",
        [
            "1 · Guided flow",
            "2 · Control/results workspace",
            "3 · Results workbench",
        ],
        horizontal=True,
        key="layout-preview-choice",
    )

    preview_summary = pd.DataFrame(
        [
            {
                "Configuration": "Origin I | Compact shelf",
                "Fitted Cartons": 3,
                "Total Cartons Analyzed": 3,
                "Sum of Weighted Average": 18.4,
            },
            {
                "Configuration": "Origin II | Multi-level shelf",
                "Fitted Cartons": 2,
                "Total Cartons Analyzed": 3,
                "Sum of Weighted Average": 15.7,
            },
            {
                "Configuration": "Vector | Shelf",
                "Fitted Cartons": 2,
                "Total Cartons Analyzed": 3,
                "Sum of Weighted Average": 12.2,
            },
        ]
    )
    preview_cartons = pd.DataFrame(
        [
            {
                "Carton": "Carton 1 - Small carton",
                "Length": 8,
                "Width": 6,
                "Height": 5,
                "Total Cartons per Bot": 24,
                "Fit Status": "Standard Fit",
            },
            {
                "Carton": "Carton 2 - Long carton",
                "Length": 18,
                "Width": 12,
                "Height": 8,
                "Total Cartons per Bot": 8,
                "Fit Status": "Standard Fit",
            },
            {
                "Carton": "Carton 3 - Tall carton",
                "Length": 12,
                "Width": 10,
                "Height": 17,
                "Total Cartons per Bot": 0,
                "Fit Status": "No Fit",
            },
        ]
    )
    preview_aisle_rows = pd.DataFrame(
        [
            {
                "Carton": "Small carton",
                "No-Pass (1-Way) minimum": "42.0 in",
                "No-Pass (1-Way) optimal": "44.0 in",
                "Pass (2-Way) minimum": "84.0 in",
                "Pass (2-Way) optimal": "86.0 in",
                "High-Density (3-Way) minimum": "126.0 in",
                "High-Density (3-Way) optimal": "128.0 in",
                "Warnings": "",
            },
            {
                "Carton": "Long carton",
                "No-Pass (1-Way) minimum": "46.0 in",
                "No-Pass (1-Way) optimal": "48.0 in",
                "Pass (2-Way) minimum": "92.0 in",
                "Pass (2-Way) optimal": "94.0 in",
                "High-Density (3-Way) minimum": "138.0 in",
                "High-Density (3-Way) optimal": "140.0 in",
                "Warnings": "Container depth may impact scanning.",
            },
            {
                "Carton": "Tall carton",
                "No-Pass (1-Way) minimum": "44.0 in",
                "No-Pass (1-Way) optimal": "46.0 in",
                "Pass (2-Way) minimum": "88.0 in",
                "Pass (2-Way) optimal": "90.0 in",
                "High-Density (3-Way) minimum": "132.0 in",
                "High-Density (3-Way) optimal": "134.0 in",
                "Warnings": "Container height exceeds the robot height limit.",
            },
        ]
    )
    preview_limiting_cartons = pd.DataFrame(
        [
            {
                "Traffic pattern": "No-Pass (1-Way)",
                "Minimum limiting carton": "Long carton",
                "Minimum aisle width": "46.0 in",
                "Optimal limiting carton": "Long carton",
                "Optimal aisle width": "48.0 in",
            },
            {
                "Traffic pattern": "Pass (2-Way)",
                "Minimum limiting carton": "Long carton",
                "Minimum aisle width": "92.0 in",
                "Optimal limiting carton": "Long carton",
                "Optimal aisle width": "94.0 in",
            },
            {
                "Traffic pattern": "High-Density (3-Way)",
                "Minimum limiting carton": "Long carton",
                "Minimum aisle width": "138.0 in",
                "Optimal limiting carton": "Long carton",
                "Optimal aisle width": "140.0 in",
            },
        ]
    )
    preview_graphic_scenarios = [
        {
            "traffic_pattern": traffic_label,
            "minimum_width_mm": 1168.4 * (index + 1),
            "minimum_carton": "Long carton",
            "optimal_width_mm": 1219.2 * (index + 1),
            "optimal_carton": "Long carton",
        }
        for index, traffic_label in enumerate(TRAFFIC_PATTERNS)
    ]
    preview_aisle_graphic = create_aisle_requirements_png(
        "Origin I | Compact shelf",
        "Origin I | 20.25in/508mm Hinged Boxshelf",
        508,
        preview_graphic_scenarios,
    )

    def render_preview_setup():
        with st.container(border=True):
            st.subheader("Analysis setup")
            settings_column, input_column = st.columns([1, 1.4])
            with settings_column:
                st.markdown("**Configurations and options**")
                st.caption("Origin I | Compact shelf · Origin II | Multi-level shelf")
                st.caption("Units: inches · Workflow: P2P · Carton state: Closed/Case")
                st.caption("Stacking: enabled · Overhang override: none")
            with input_column:
                st.markdown("**Carton data**")
                st.dataframe(
                    preview_cartons[["Carton", "Length", "Width", "Height"]],
                    use_container_width=True,
                    hide_index=True,
                )
            st.button(
                "Run capacity analysis",
                disabled=True,
                key="preview-run-analysis",
            )

    def render_preview_overview(chart_key):
        st.subheader("Capacity overview")
        metric_columns = st.columns(3)
        metric_columns[0].metric("Cartons analyzed", "3")
        metric_columns[1].metric("Top configuration", "Origin I | Compact shelf")
        metric_columns[2].metric("Cartons fitting", "3 of 3")
        st.plotly_chart(
            px.bar(
                preview_summary,
                x="Sum of Weighted Average",
                y="Configuration",
                orientation="h",
                title="Weighted average cartons per bot",
            ),
            use_container_width=True,
            key=chart_key,
        )
        st.subheader("Carton-level capacity results")
        st.dataframe(preview_cartons, use_container_width=True, hide_index=True)

    def render_preview_fit(chart_key):
        st.subheader("Carton fit and shelf visualization")
        st.caption(
            "Sample carton: Long carton · 8 cartons per bot · Tan carton body, "
            "slate core shelf, teal overhang."
        )
        st.plotly_chart(
            make_fit_figure(
                {
                    "width": 20,
                    "depth": 18,
                    "height": 16,
                    "physical_width": 20,
                    "core_depth": 15,
                    "overhang_depth": 3,
                    "placements": [],
                },
                [
                    {"x": 2, "y": 2, "z": 0, "l": 8, "w": 6, "h": 5},
                ],
                False,
                {
                    "flap_state": "closed",
                    "carton_body_dimensions": (8, 6, 5),
                    "flap_extension": 0,
                    "flap_margin": 0,
                },
            ),
            use_container_width=True,
            key=chart_key,
        )
        st.caption("Carton fit selector · Sample: Long carton")

    def render_preview_aisle():
        st.subheader("Aisle width recommendations")
        st.caption(
            "Mapped profile: Origin I | 20.25in/508mm Hinged Boxshelf · "
            "Robot width: 508 mm."
        )
        st.dataframe(
            preview_aisle_rows,
            use_container_width=True,
            hide_index=True,
        )
        st.markdown("**Limiting carton by traffic pattern**")
        st.dataframe(
            preview_limiting_cartons,
            use_container_width=True,
            hide_index=True,
        )
        st.image(preview_aisle_graphic, use_container_width=True)

    def render_preview_downloads():
        st.subheader("Downloads")
        excel_column, image_column = st.columns(2)
        excel_column.button(
            "Download Excel results",
            disabled=True,
            key="preview-download-excel",
        )
        image_column.button(
            "Download aisle requirements PNG",
            disabled=True,
            key="preview-download-png",
        )
        st.caption("Downloads shown for layout only; preview values are illustrative.")

    if layout_choice == "1 · Guided flow":
        st.subheader("Step 1 · Configure and enter cartons")
        render_preview_setup()
        st.subheader("Step 2 · Review capacity results")
        render_preview_overview("preview-guided-overview")
        st.subheader("Step 3 · Review aisle requirements and carton fit")
        render_preview_aisle()
        render_preview_fit("preview-guided-carton-fit")
        render_preview_downloads()
    elif layout_choice == "2 · Control/results workspace":
        control_column, results_column = st.columns([0.85, 2.15], gap="large")
        with control_column:
            st.subheader("Controls")
            render_preview_setup()
        with results_column:
            render_preview_overview("preview-workspace-overview")
            with st.container(border=True):
                render_preview_aisle()
            with st.container(border=True):
                render_preview_fit("preview-workspace-carton-fit")
            render_preview_downloads()
    else:
        render_preview_setup()
        overview_tab, fit_tab, aisle_tab, downloads_tab = st.tabs(
            ["Overview", "Carton Fit", "Aisle Planning", "Downloads"]
        )
        with overview_tab:
            render_preview_overview("preview-workbench-overview")
        with fit_tab:
            render_preview_fit("preview-workbench-carton-fit")
        with aisle_tab:
            render_preview_aisle()
        with downloads_tab:
            render_preview_downloads()
