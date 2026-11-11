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
- After importing carton data, the page shows the number of cartons queued for analysis. Imported data is cached in the session until the input changes.
- Review the capacity summary and carton-level results, then download an Excel workbook. Results remain available while switching the Configuration details selector.
- The front-page carton animation spins as its top flaps move from closed, to splayed outward, then folded down over the sides. The bottom remains closed, and the animation respects the system's reduced-motion preference.

The app generates downloads in memory and does not save uploaded workbooks to persistent server storage. Data is still processed by the hosting service, so only upload data your organization permits to be handled there.

## Migration notes

The desktop Tkinter interface, local directory/file dialogs, and Excel dashboard formatting were replaced with browser controls and downloadable result sheets. The legacy 3D carton mesh dashboards are not included in this first web version; the results page provides an interactive capacity comparison chart instead.
