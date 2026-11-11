import hashlib
import io

import pandas as pd
import plotly.express as px
import streamlit as st

from capacity_engine import DEFAULT_CONFIGS, analyze_cartons, make_workbook


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
st.session_state.setdefault("analysis_is_optimized", False)

if run_analysis:
    st.session_state["analysis_results"] = None
    st.session_state["analysis_summary"] = None
    st.session_state.pop("configuration_details_selector", None)
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
                results = analyze_cartons(carton_dataframe, configs_to_run, options)
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
    st.dataframe(results[detail_config], use_container_width=True, hide_index=True)
    st.download_button(
        "Download Excel results",
        data=make_workbook(results),
        file_name="Bot_Capacity_Results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        on_click="ignore",
    )

st.caption("Calculations run on the hosted service. Avoid uploading data that your organization does not permit to be processed there.")
