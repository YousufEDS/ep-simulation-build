import os
import subprocess
import json
from google.cloud import storage
from html.parser import HTMLParser

# --- Configuration from Environment Variables ---
BUCKET_NAME = os.environ.get("BUCKET_NAME")
IDF_FILE = os.environ.get("IDF_FILE")       # e.g., "inputs/my_building.idf"
EPW_FILE = os.environ.get("EPW_FILE")       # e.g., "inputs/weather.epw"

# Local working directories inside the container
WORK_DIR = "/tmp/ep_run"
INPUT_DIR = os.path.join(WORK_DIR, "input")
OUTPUT_DIR = os.path.join(WORK_DIR, "output")

# EnergyPlus install path
ENERGYPLUS_PATH = "/usr/local/EnergyPlus-22-1-0/energyplus"


# ─────────────────────────────────────────────
# GCS HELPERS
# ─────────────────────────────────────────────

def download_from_gcs(bucket_name, source_blob_path, destination_file_path):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(source_blob_path)
    os.makedirs(os.path.dirname(destination_file_path), exist_ok=True)
    blob.download_to_filename(destination_file_path)
    print(f"  Downloaded: gs://{bucket_name}/{source_blob_path}")

def upload_to_gcs(bucket_name, source_file_path, destination_blob_path):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_path)
    blob.upload_from_filename(source_file_path)
    print(f"  Uploaded: {source_file_path} -> gs://{bucket_name}/{destination_blob_path}")


# ─────────────────────────────────────────────
# HTML PARSER — extracts tables from eplusout.htm
# ─────────────────────────────────────────────

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._current_table = None
        self._current_row = None
        self._current_cell = None
        self._in_cell = False
        self._capture = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._current_table = {"headers": [], "rows": []}
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in ("td", "th") and self._current_row is not None:
            self._current_cell = ""
            self._in_cell = True

    def handle_endtag(self, tag):
        if tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None
        elif tag == "tr" and self._current_table is not None and self._current_row is not None:
            if self._current_row:
                self._current_table["rows"].append(self._current_row)
            self._current_row = None
        elif tag in ("td", "th") and self._in_cell:
            if self._current_row is not None:
                self._current_row.append(self._current_cell.strip())
            self._in_cell = False
            self._current_cell = None

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell += data


def parse_htm_report(htm_path):
    """
    Reads eplusout.htm and extracts:
      - Site:EUI (total energy use intensity)
      - End Use summary (electricity + gas per end use)
      - Peak demand
    Returns a dict of results.
    """
    with open(htm_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    parser = TableParser()
    parser.feed(content)

    results = {
        "site_eui_kWh_per_m2": None,
        "total_electricity_GJ": None,
        "total_natural_gas_GJ": None,
        "end_use_electricity_GJ": {},
        "end_use_natural_gas_GJ": {},
        "peak_electricity_demand_W": None,
    }

    for table in parser.tables:
        for row in table["rows"]:
            if not row:
                continue

            label = row[0].strip()

            # ── Total Site Energy / EUI ──────────────────────
            if "Total Site Energy" in label and len(row) >= 3:
                try:
                    # Column 2 is typically kWh/m2
                    results["site_eui_kWh_per_m2"] = float(row[2].replace(",", ""))
                except ValueError:
                    pass

            # ── Total Electricity ────────────────────────────
            if label in ("Total Electricity", "Electricity Total") and len(row) >= 2:
                try:
                    results["total_electricity_GJ"] = float(row[1].replace(",", ""))
                except ValueError:
                    pass

            # ── Total Natural Gas ────────────────────────────
            if label in ("Total Natural Gas", "Natural Gas Total") and len(row) >= 2:
                try:
                    results["total_natural_gas_GJ"] = float(row[1].replace(",", ""))
                except ValueError:
                    pass

            # ── End Use Distribution ─────────────────────────
            end_uses = [
                "Heating", "Cooling", "Interior Lighting", "Exterior Lighting",
                "Interior Equipment", "Exterior Equipment", "Fans", "Pumps",
                "Heat Rejection", "Humidification", "Heat Recovery",
                "Water Systems", "Refrigeration", "Generators"
            ]
            for eu in end_uses:
                if label == eu and len(row) >= 3:
                    try:
                        results["end_use_electricity_GJ"][eu] = float(row[1].replace(",", ""))
                        results["end_use_natural_gas_GJ"][eu] = float(row[2].replace(",", ""))
                    except ValueError:
                        pass

            # ── Peak Electricity Demand ──────────────────────
            if "Peak Electricity Demand" in label and len(row) >= 2:
                try:
                    results["peak_electricity_demand_W"] = float(row[1].replace(",", ""))
                except ValueError:
                    pass

    return results


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("EnergyPlus Cloud Run Job - Starting")
    print("=" * 60)

    # --- Step 0: Validate environment variables ---
    if not all([BUCKET_NAME, IDF_FILE, EPW_FILE]):
        raise ValueError(
            "Missing required environment variables. "
            "Ensure BUCKET_NAME, IDF_FILE, and EPW_FILE are all set."
        )

    # --- Step 1: Create working directories ---
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # --- Step 2: Download input files from GCS ---
    print("\n--- Downloading Input Files ---")
    local_idf = os.path.join(INPUT_DIR, os.path.basename(IDF_FILE))
    local_epw = os.path.join(INPUT_DIR, os.path.basename(EPW_FILE))
    download_from_gcs(BUCKET_NAME, IDF_FILE, local_idf)
    download_from_gcs(BUCKET_NAME, EPW_FILE, local_epw)

    # --- Step 3: Run EnergyPlus ---
    print("\n--- Running EnergyPlus Simulation ---")
    command = [
        ENERGYPLUS_PATH,
        "--weather", local_epw,
        "--output-directory", OUTPUT_DIR,
        "--idd", "/usr/local/EnergyPlus-22-1-0/Energy+.idd",
        local_idf,
    ]
    print(f"Command: {' '.join(command)}\n")

    result = subprocess.run(command, capture_output=True, text=True)

    print("--- EnergyPlus STDOUT ---")
    print(result.stdout)
    if result.stderr:
        print("--- EnergyPlus STDERR ---")
        print(result.stderr)

    if result.returncode != 0:
        print(f"\nERROR: EnergyPlus exited with code {result.returncode}")
        exit(1)

    print("\nSUCCESS: EnergyPlus simulation completed.")

    # --- Step 4: Upload ONLY the HTML report ---
    print("\n--- Uploading HTML Report ---")
    htm_local = os.path.join(OUTPUT_DIR, "eplusout.htm")

    if not os.path.exists(htm_local):
        print("WARNING: eplusout.htm not found — check your IDF Output:Table:SummaryReports setting.")
    else:
        upload_to_gcs(BUCKET_NAME, htm_local, "outputs/eplusout.htm")

    # --- Step 5: Parse HTML and extract key values ---
    print("\n--- Parsing Energy Results ---")
    if os.path.exists(htm_local):
        energy_results = parse_htm_report(htm_local)

        print("\nExtracted Results:")
        print(f"  Site EUI             : {energy_results['site_eui_kWh_per_m2']} kWh/m2")
        print(f"  Total Electricity    : {energy_results['total_electricity_GJ']} GJ")
        print(f"  Total Natural Gas    : {energy_results['total_natural_gas_GJ']} GJ")
        print(f"  Peak Demand          : {energy_results['peak_electricity_demand_W']} W")
        print(f"  End Use (Electricity): {energy_results['end_use_electricity_GJ']}")

        # Save and upload results as JSON
        json_local = os.path.join(OUTPUT_DIR, "results_summary.json")
        with open(json_local, "w") as f:
            json.dump(energy_results, f, indent=2)

        upload_to_gcs(BUCKET_NAME, json_local, "outputs/results_summary.json")
        print("\n  results_summary.json uploaded successfully.")

    print("\n" + "=" * 60)
    print("EnergyPlus Cloud Run Job - Finished")
    print("=" * 60)


if __name__ == "__main__":
    main()