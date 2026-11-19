# Bot Capacity Calculator

A Streamlit web version of the desktop bot capacity analysis tool. The packing calculations and the 54 built-in shelf configurations are reused, while the interface now supports browser-based spreadsheet upload, pasted Excel rows, direct carton entry, and Excel downloads.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Deploy to Render

This repository includes a Render Blueprint in `render.yaml`. In Render, create a new Blueprint from this repository and deploy the `bot-capacity-calculator` web service. Render installs the dependencies and starts Streamlit on the assigned `$PORT`.

## Using the app

- Upload an `.xlsx` or `.csv`, paste tab-separated rows, or enter cartons in the editable table.
- Required carton fields are Length, Width, and Height. Carton Name, SKU, Usage %, Weight, and Flap State are optional. Flap State accepts Closed/Case, Flaps Up, Flaps Down, or No Flaps; blank values use the global Carton state setting.
- Choose shelf configurations and calculation options in the sidebar. The app includes custom shelf dimensions and family-based auto-optimization.
- Open **Manage Bot Configurations** to review every built-in bot configuration and its shelf dimensions, shelf count, buffer, hinge, overhang, and payload inputs. Configuration Name and Bot Family are separate fields; add or select a family when adding/editing configurations. The table and analysis selectors sort by family, then name, and optimization uses the explicit family field. Identical configuration names are allowed in different families, but each name/family pair must be unique. Existing configurations are migrated by moving the suffix after `|` into Bot Family; older custom configurations without a family are placed in **Unassigned** so they remain available to edit. Add, edit (including renaming), or delete configurations; saves are shared by all users and used by subsequent capacity calculations. Configuration management sections are collapsed initially. When hinge fallback is disabled, hinge dimensions are saved as `0`; when enabled, positive hinge width, depth, and height are required. The special **Manual Input** option remains configured in the analysis sidebar.
- In **Manage Bot Configurations**, use **Aisle width mappings** to link each capacity configuration to an aisle profile and enter the robot/hardware width in millimeters. Origin mappings must use the exact catalog width shown by the selected profile; Vector profiles require a positive manually entered width for reference. Mapping changes are shared by all users and follow configuration renames/deletions.
- Open **Aisle Width Configuration** to edit the numerical requirements for existing aisle profiles. Vector minimum/optimal widths, Origin tray radii and shared model constants, and the one-way minimum can be updated. Profile names, robot types, hardware widths, formulas, and mappings are fixed. Changes are shared and apply to future aisle calculations.
- Configuration editing has no app-level sign-in. Restrict access to the service to trusted users; anyone who can access the app can change its shared configurations.
- After importing carton data, the page shows the number of cartons queued for analysis. Imported data is cached in the session until the input changes.
- Review the capacity summary and carton-level results, then download an Excel workbook. Results remain available while switching the Configuration details selector.
- After analysis, use the Configuration details and Carton fit selectors to inspect interactive 3D carton layouts. Tan shows the carton body; teal surfaces and outlines identify the flap panels. The shelf visualization distinguishes the core shelf (slate) from its overhang extension (teal), and labels their physical depths separately from the buffered usable dimensions used for fit calculations. Most built-in configurations default to 3 inches of overhang; the selected configuration's value is used unless the global override is set. This piece-level appearance is illustrative and does not change fit calculations. Manual configurations with multiple shelf heights show a separate view for each shelf. Weight-limited layouts show only the cartons allowed by the payload.
- **Aisle width recommendations** use the mapped aisle profile for the selected Configuration details and calculate minimum and optimal widths for one-way, two-way, and high-density traffic for every input carton. Highlighted rows identify cartons with the largest optimal aisle width separately for each traffic pattern; the summary also identifies minimum and optimal limiting cartons. Carton Length is treated as width (X), Width as depth (Y), and flaps-up height includes the flap extension. Results follow the selected metric/imperial display setting; missing mappings and model warnings are shown in the results.
- At the bottom of the capacity results, the **Aisle requirements image** summarizes the selected bot configuration and its one-way, two-way, and three-way scenarios. Each scenario shows minimum and optimal aisle widths plus their limiting cartons. Use **Download aisle requirements PNG** to insert the generated graphic into proposal documents. The graphic is a schematic (not a product photo) because original bot image assets are not included with the app.
- Open **Layout Previews** to compare three visual-only sample layouts: guided flow, control/results workspace, and results workbench. These samples do not alter calculator inputs, results, or configuration settings; the live capacity-analysis layout remains unchanged until a design is selected for implementation.
- Aisle widths are estimates from the attached robot model and its catalog constants, not site-specific engineering or safety guidance. Validate aisle requirements with the robot manufacturer and facility design/safety teams before implementation.

Each Run click recalculates and replaces the results and visualizations held in the Streamlit session; the app does not automatically write uploaded data or analysis results to persistent files. Configuration changes are stored separately in SQLite. The Excel download remains user-triggered. Data is still processed by the hosting service, so only upload data your organization permits to be handled there.

The Render Blueprint mounts a Persistent Disk at `/var/data` and stores configurations in `/var/data/bot_configs.sqlite3`, so edits survive service restarts and deploys. Render Persistent Disks can require a paid plan and limit the service to one instance. For local development, the database defaults to `bot_configs.sqlite3` beside `app.py`; set `BOT_CONFIG_DB` to override its location. On first startup, built-in configurations are copied from `bot_configs.json` into an empty database.

## Migration notes

The desktop Tkinter interface, local directory/file dialogs, and Excel dashboard formatting were replaced with browser controls and downloadable result sheets. Interactive 3D carton-fit views are available in the results page alongside the capacity comparison chart.
