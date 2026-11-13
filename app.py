import hashlib
import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from capacity_engine import DEFAULT_CONFIGS, analyze_cartons_with_placements, make_workbook


VISUALIZATION_SCHEMA_VERSION = 1


st.set_page_config(page_title="Bot Capacity Calculator", page_icon="📦", layout="wide")
header_title, header_animation = st.columns([5, 1], vertical_alignment="center")
with header_title:
    st.title("Bot Capacity Calculator")
    st.caption("Estimate carton capacity for Locus robot shelf configurations.")
with header_animation:
    st.html(
        """
        <style>
          #capacity-carton-animation {
            height: 150px; display: grid; place-items: center; perspective: 650px;
          }
          #capacity-carton-animation .carton {
            position: relative; width: 100px; height: 72px;
            transform-style: preserve-3d; animation: capacity-carton-spin 9s linear infinite;
          }
          #capacity-carton-animation .face, #capacity-carton-animation .flap {
            position: absolute; box-sizing: border-box;
            border: 2px solid #754116;
            background:
              repeating-linear-gradient(90deg, rgba(88, 57, 30, 0.035) 0 1px, transparent 1px 6px),
              linear-gradient(145deg, #dfb783, #c38c53);
            backface-visibility: visible;
          }
          #capacity-carton-animation .front, #capacity-carton-animation .back {
            width: 100px; height: 72px;
          }
          #capacity-carton-animation .front { transform: translateZ(34px); }
          #capacity-carton-animation .back { transform: rotateY(180deg) translateZ(34px); }
          #capacity-carton-animation .side {
            top: 0; left: 18px; width: 64px; height: 72px;
          }
          #capacity-carton-animation .left { transform: rotateY(-90deg) translateZ(50px); }
          #capacity-carton-animation .right { transform: rotateY(90deg) translateZ(50px); }
          #capacity-carton-animation .bottom {
            top: 40px; left: 0; width: 100px; height: 64px;
            transform: rotateX(90deg);
            background: #986a40;
          }
          #capacity-carton-animation .flap {
            position: absolute; top: -34px; height: 34px;
            transform-origin: 50% 100%; transform-style: preserve-3d;
          }
          #capacity-carton-animation .flap-front,
          #capacity-carton-animation .flap-back {
            width: 100px; left: 0;
          }
          #capacity-carton-animation .flap-front {
            transform: translateZ(34px) rotateX(90deg);
            animation: capacity-carton-front-flap 6s ease-in-out infinite;
          }
          #capacity-carton-animation .flap-back {
            transform: translateZ(-34px) rotateX(-90deg);
            animation: capacity-carton-back-flap 6s ease-in-out infinite;
          }
          #capacity-carton-animation .flap-side {
            top: -50px; left: -32px; width: 64px; height: 50px;
          }
          #capacity-carton-animation .flap-left {
            transform: rotateZ(90deg) rotateY(90deg);
            animation: capacity-carton-left-flap 6s ease-in-out infinite;
          }
          #capacity-carton-animation .flap-right {
            left: 68px;
            transform: rotateZ(-90deg) rotateY(90deg);
            animation: capacity-carton-right-flap 6s ease-in-out infinite;
          }
          @keyframes capacity-carton-spin {
            from { transform: rotateX(-18deg) rotateY(0deg); }
            to { transform: rotateX(-18deg) rotateY(360deg); }
          }
          @keyframes capacity-carton-front-flap {
            0%, 12% { transform: translateZ(34px) rotateX(90deg); }
            26%, 34% { transform: translateZ(34px) rotateX(0deg); }
            44%, 60% { transform: translateZ(34px) rotateX(-90deg); }
            72%, 78% { transform: translateZ(34px) rotateX(-180deg); }
            94%, 100% { transform: translateZ(34px) rotateX(-270deg); }
          }
          @keyframes capacity-carton-back-flap {
            0%, 12% { transform: translateZ(-34px) rotateX(-90deg); }
            26%, 34% { transform: translateZ(-34px) rotateX(0deg); }
            44%, 60% { transform: translateZ(-34px) rotateX(90deg); }
            72%, 78% { transform: translateZ(-34px) rotateX(180deg); }
            94%, 100% { transform: translateZ(-34px) rotateX(270deg); }
          }
          @keyframes capacity-carton-left-flap {
            0%, 12% { transform: rotateZ(90deg) rotateY(90deg); }
            26%, 34% { transform: rotateZ(0deg) rotateY(90deg); }
            44%, 60% { transform: rotateZ(-90deg) rotateY(90deg); }
            72%, 78% { transform: rotateZ(-180deg) rotateY(90deg); }
            94%, 100% { transform: rotateZ(-270deg) rotateY(90deg); }
          }
          @keyframes capacity-carton-right-flap {
            0%, 12% { transform: rotateZ(-90deg) rotateY(90deg); }
            26%, 34% { transform: rotateZ(0deg) rotateY(90deg); }
            44%, 60% { transform: rotateZ(90deg) rotateY(90deg); }
            72%, 78% { transform: rotateZ(180deg) rotateY(90deg); }
            94%, 100% { transform: rotateZ(270deg) rotateY(90deg); }
          }
          @media (prefers-reduced-motion: reduce) {
            #capacity-carton-animation .carton,
            #capacity-carton-animation .flap { animation: none !important; }
          }
        </style>
        <div id="capacity-carton-animation" role="img" aria-label="A carton spinning as its flaps open and close">
          <div class="carton">
            <div class="face front"></div><div class="face back"></div>
            <div class="face side left"></div><div class="face side right"></div>
            <div class="face bottom"></div>
            <div class="flap flap-front"></div><div class="flap flap-back"></div>
            <div class="flap flap-side flap-left"></div>
            <div class="flap flap-side flap-right"></div>
          </div>
        </div>
        """,
    )

with st.sidebar:
    st.header("Analysis settings")
    metric = st.toggle("Metric units (mm / kg)")
    length_unit = "mm" if metric else "in"
    weight_unit = "kg" if metric else "lb"

    config_names = list(DEFAULT_CONFIGS)
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
            options=["OI", "OII", "VS1.2", "VS2.0"],
            default=["OI", "OII", "VS1.2", "VS2.0"],
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

if run_analysis:
    st.session_state["analysis_results"] = None
    st.session_state["analysis_summary"] = None
    st.session_state["analysis_visuals"] = None
    st.session_state["analysis_visual_schema_version"] = 0
    st.session_state["analysis_is_optimized"] = False
    st.session_state.pop("configuration_details_selector", None)
    st.session_state.pop("carton_fit_selector", None)
    if optimize:
        configs_to_run = [
            name
            for name in config_names
            if name != "Manual Input" and any(name.endswith(family) for family in selected_families)
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
                    carton_dataframe, configs_to_run, options
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
        title="Weighted average cartons per bot",
    )
    st.plotly_chart(chart, use_container_width=True)

    detail_config = st.selectbox(
        "Configuration details",
        list(results),
        key="configuration_details_selector",
    )
    detail_results = results[detail_config]
    st.dataframe(detail_results, use_container_width=True, hide_index=True)

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
            for visual in config_visuals
        )
    )
    if not visuals_are_current:
        st.info(
            "These saved results use an older 3D visualization format. "
            "Your capacity results are still available; rerun the analysis to refresh the flap-aware 3D view."
        )
    else:
        def carton_label(row_number):
            row = detail_results.iloc[row_number]
            name = row.get("Carton Name")
            if pd.isna(name) or not str(name).strip():
                name = row.get("SKU")
            label = f"Carton {row_number + 1}"
            if not pd.isna(name) and str(name).strip():
                label += f" - {name}"
            return label

        carton_index = st.selectbox(
            "Carton fit",
            options=list(range(len(detail_results))),
            format_func=carton_label,
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

st.caption("Calculations run on the hosted service. Avoid uploading data that your organization does not permit to be processed there.")
