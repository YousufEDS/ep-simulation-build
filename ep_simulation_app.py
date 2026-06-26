import streamlit as st
import json
import time
import tempfile
import os
from google.cloud import storage, run_v2
from google.api_core.exceptions import GoogleAPICallError

# ─────────────────────────────────────────────────────────────
# CONFIG — edit these to match your GCP setup
# ─────────────────────────────────────────────────────────────
GCP_PROJECT      = "energyplus-simulation"
GCP_REGION       = "asia-south2"
BUCKET_NAME      = "energyplus-simulation-bucket"
CLOUD_RUN_JOB    = "ep-simulation-job"

INPUT_IDF_BLOB   = "inputs/model.idf"
INPUT_EPW_BLOB   = "inputs/weather.epw"
OUTPUT_HTM_BLOB  = "outputs/eplusout.htm"
OUTPUT_JSON_BLOB = "outputs/results_summary.json"

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EnergyPlus Simulation",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background-color: #0f1117;
    color: #e0e0e0;
}

/* Header */
.header-bar {
    display: flex;
    align-items: baseline;
    gap: 14px;
    padding: 32px 0 8px 0;
    border-bottom: 1px solid #2a2a3a;
    margin-bottom: 32px;
}
.header-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.7rem;
    font-weight: 600;
    color: #ffffff;
    letter-spacing: -0.02em;
}
.header-sub {
    font-size: 0.85rem;
    color: #6b7280;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

/* Upload cards */
.upload-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    font-weight: 600;
    color: #7dd3fc;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}
.upload-hint {
    font-size: 0.78rem;
    color: #6b7280;
    margin-top: 4px;
}

/* Status pill */
.status-pill {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.04em;
}
.status-running { background: #1c3557; color: #7dd3fc; border: 1px solid #2563eb; }
.status-success { background: #14291e; color: #4ade80; border: 1px solid #16a34a; }
.status-error   { background: #2d1515; color: #f87171; border: 1px solid #dc2626; }

/* Result cards */
.metric-card {
    background: #161b27;
    border: 1px solid #2a2a3a;
    border-radius: 8px;
    padding: 18px 20px;
    margin-bottom: 12px;
}
.metric-label {
    font-size: 0.72rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
}
.metric-value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.6rem;
    font-weight: 600;
    color: #f0f0f0;
}
.metric-unit {
    font-size: 0.8rem;
    color: #6b7280;
    margin-left: 4px;
}

/* End use bar chart */
.enduse-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
}
.enduse-label {
    font-size: 0.78rem;
    color: #9ca3af;
    width: 160px;
    flex-shrink: 0;
}
.enduse-bar-bg {
    flex: 1;
    height: 8px;
    background: #1e2433;
    border-radius: 4px;
    overflow: hidden;
}
.enduse-bar-fill {
    height: 8px;
    border-radius: 4px;
    background: linear-gradient(90deg, #2563eb, #7dd3fc);
}
.enduse-val {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: #6b7280;
    width: 70px;
    text-align: right;
    flex-shrink: 0;
}

/* Section header */
.section-header {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    font-weight: 600;
    color: #4b5563;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin: 28px 0 14px 0;
    border-bottom: 1px solid #1e2433;
    padding-bottom: 6px;
}

/* Download button */
.stDownloadButton > button {
    background: #1d4ed8 !important;
    color: white !important;
    border: none !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.8rem !important;
    padding: 10px 20px !important;
    width: 100% !important;
    letter-spacing: 0.03em !important;
}
.stDownloadButton > button:hover {
    background: #1e40af !important;
}

/* Run button */
.stButton > button {
    background: #059669 !important;
    color: white !important;
    border: none !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.85rem !important;
    padding: 12px 24px !important;
    width: 100% !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
}
.stButton > button:hover {
    background: #047857 !important;
}

/* Divider */
hr { border-color: #1e2433 !important; }

/* Hide default streamlit chrome */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# GCS HELPERS
# ─────────────────────────────────────────────────────────────

def upload_file_to_gcs(local_path, blob_name):
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path)

def download_blob_bytes(blob_name):
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)
    return blob.download_as_bytes()

def blob_exists(blob_name):
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(BUCKET_NAME)
    return bucket.blob(blob_name).exists()

def delete_blob_if_exists(blob_name):
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)
    if blob.exists():
        blob.delete()


# ─────────────────────────────────────────────────────────────
# CLOUD RUN JOB HELPERS
# ─────────────────────────────────────────────────────────────

def trigger_cloud_run_job(idf_blob, epw_blob):
    """Triggers the Cloud Run Job and returns the execution name."""
    client = run_v2.JobsClient()
    job_name = f"projects/{GCP_PROJECT}/locations/{GCP_REGION}/jobs/{CLOUD_RUN_JOB}"

    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    env=[
                        run_v2.EnvVar(name="BUCKET_NAME", value=BUCKET_NAME),
                        run_v2.EnvVar(name="IDF_FILE",    value=idf_blob),
                        run_v2.EnvVar(name="EPW_FILE",    value=epw_blob),
                    ]
                )
            ]
        )
    )

    operation = client.run_job(request=request)
    # operation.metadata contains the execution info
    meta = operation.metadata
    return operation, meta.name if meta else None


def poll_execution_status(operation, timeout=600, poll_interval=10):
    """
    Polls until the Cloud Run Job execution finishes.
    Returns (success: bool, message: str)
    """
    elapsed = 0
    while not operation.done():
        time.sleep(poll_interval)
        elapsed += poll_interval
        yield elapsed, "RUNNING"
        if elapsed >= timeout:
            yield elapsed, "TIMEOUT"
            return

    if operation.exception():
        yield elapsed, f"ERROR: {operation.exception()}"
    else:
        yield elapsed, "SUCCESS"


# ─────────────────────────────────────────────────────────────
# RESULT RENDERING
# ─────────────────────────────────────────────────────────────

def render_results(results: dict, htm_bytes: bytes):
    st.markdown('<div class="section-header">Simulation Results</div>', unsafe_allow_html=True)

    # ── Top metrics row ──────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        eui = results.get("site_eui_kWh_per_m2")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Site EUI</div>
            <div class="metric-value">{f"{eui:.1f}" if eui else "—"}<span class="metric-unit">kWh/m²</span></div>
        </div>""", unsafe_allow_html=True)

    with col2:
        elec = results.get("total_electricity_GJ")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Total Electricity</div>
            <div class="metric-value">{f"{elec:.1f}" if elec else "—"}<span class="metric-unit">GJ</span></div>
        </div>""", unsafe_allow_html=True)

    with col3:
        peak = results.get("peak_electricity_demand_W")
        peak_kw = peak / 1000 if peak else None
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Peak Demand</div>
            <div class="metric-value">{f"{peak_kw:.1f}" if peak_kw else "—"}<span class="metric-unit">kW</span></div>
        </div>""", unsafe_allow_html=True)

    # ── End Use Distribution ─────────────────────────────────
    end_uses = results.get("end_use_electricity_GJ", {})
    if end_uses:
        st.markdown('<div class="section-header">End Use Distribution — Electricity (GJ)</div>', unsafe_allow_html=True)
        total = sum(end_uses.values()) or 1
        bars_html = ""
        for eu, val in sorted(end_uses.items(), key=lambda x: -x[1]):
            if val > 0:
                pct = (val / total) * 100
                bars_html += f"""
                <div class="enduse-row">
                    <div class="enduse-label">{eu}</div>
                    <div class="enduse-bar-bg">
                        <div class="enduse-bar-fill" style="width:{pct:.1f}%"></div>
                    </div>
                    <div class="enduse-val">{val:.2f} GJ</div>
                </div>"""
        st.markdown(bars_html, unsafe_allow_html=True)

    # ── Download buttons ─────────────────────────────────────
    st.markdown('<div class="section-header">Download</div>', unsafe_allow_html=True)
    dl_col1, dl_col2 = st.columns(2)

    with dl_col1:
        st.download_button(
            label="⬇  Download HTML Report",
            data=htm_bytes,
            file_name="eplusout.htm",
            mime="text/html",
        )

    with dl_col2:
        st.download_button(
            label="⬇  Download Results JSON",
            data=json.dumps(results, indent=2).encode(),
            file_name="results_summary.json",
            mime="application/json",
        )


# ─────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────

def main():
    # Header
    st.markdown("""
    <div class="header-bar">
        <span class="header-title">⚡ EnergyPlus Simulation</span>
        <span class="header-sub">Cloud Run · GCP · asia-south2</span>
    </div>
    """, unsafe_allow_html=True)

    # ── File upload section ──────────────────────────────────
    col_idf, col_epw = st.columns(2)

    with col_idf:
        st.markdown('<div class="upload-label">Building Model</div>', unsafe_allow_html=True)
        idf_file = st.file_uploader(
            label="IDF file",
            type=["idf"],
            label_visibility="collapsed",
            key="idf_uploader"
        )
        st.markdown('<div class="upload-hint">EnergyPlus Input Data File (.idf)</div>', unsafe_allow_html=True)

    with col_epw:
        st.markdown('<div class="upload-label">Weather File</div>', unsafe_allow_html=True)
        epw_file = st.file_uploader(
            label="EPW file",
            type=["epw"],
            label_visibility="collapsed",
            key="epw_uploader"
        )
        st.markdown('<div class="upload-hint">EnergyPlus Weather File (.epw)</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Run button ───────────────────────────────────────────
    both_uploaded = idf_file is not None and epw_file is not None

    if not both_uploaded:
        st.info("Upload both an IDF and an EPW file to run the simulation.", icon="ℹ️")

    run_clicked = st.button(
        "▶  Run Simulation",
        disabled=not both_uploaded,
    )

    # ── Simulation flow ──────────────────────────────────────
    if run_clicked and both_uploaded:

        status_box = st.empty()
        progress_bar = st.progress(0)

        try:
            # Step 1: Upload IDF
            status_box.markdown('<span class="status-pill status-running">Uploading IDF to GCS...</span>', unsafe_allow_html=True)
            with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as tmp:
                tmp.write(idf_file.read())
                tmp_idf_path = tmp.name
            upload_file_to_gcs(tmp_idf_path, INPUT_IDF_BLOB)
            os.unlink(tmp_idf_path)
            progress_bar.progress(15)

            # Step 2: Upload EPW
            status_box.markdown('<span class="status-pill status-running">Uploading EPW to GCS...</span>', unsafe_allow_html=True)
            with tempfile.NamedTemporaryFile(suffix=".epw", delete=False) as tmp:
                tmp.write(epw_file.read())
                tmp_epw_path = tmp.name
            upload_file_to_gcs(tmp_epw_path, INPUT_EPW_BLOB)
            os.unlink(tmp_epw_path)
            progress_bar.progress(25)

            # Step 3: Clear old outputs
            status_box.markdown('<span class="status-pill status-running">Clearing previous outputs...</span>', unsafe_allow_html=True)
            delete_blob_if_exists(OUTPUT_HTM_BLOB)
            delete_blob_if_exists(OUTPUT_JSON_BLOB)
            progress_bar.progress(30)

            # Step 4: Trigger Cloud Run Job
            status_box.markdown('<span class="status-pill status-running">Triggering Cloud Run Job...</span>', unsafe_allow_html=True)
            operation, exec_name = trigger_cloud_run_job(INPUT_IDF_BLOB, INPUT_EPW_BLOB)
            progress_bar.progress(35)

            # Step 5: Poll until done
            final_status = "UNKNOWN"
            for elapsed, status in poll_execution_status(operation, timeout=600, poll_interval=8):
                if status == "RUNNING":
                    pct = min(35 + int((elapsed / 600) * 55), 88)
                    progress_bar.progress(pct)
                    status_box.markdown(
                        f'<span class="status-pill status-running">Simulation running... {elapsed}s elapsed</span>',
                        unsafe_allow_html=True
                    )
                else:
                    final_status = status
                    break

            if "ERROR" in final_status or "TIMEOUT" in final_status:
                progress_bar.progress(100)
                status_box.markdown(
                    f'<span class="status-pill status-error">Job failed: {final_status}</span>',
                    unsafe_allow_html=True
                )
                st.error("The simulation job failed. Check Cloud Run logs in GCP Console for details.")
                return

            progress_bar.progress(92)

            # Step 6: Download results from GCS
            status_box.markdown('<span class="status-pill status-running">Fetching results...</span>', unsafe_allow_html=True)

            if not blob_exists(OUTPUT_HTM_BLOB):
                st.error("Simulation completed but eplusout.htm was not found. Check your IDF output settings.")
                return

            htm_bytes = download_blob_bytes(OUTPUT_HTM_BLOB)
            progress_bar.progress(97)

            results = {}
            if blob_exists(OUTPUT_JSON_BLOB):
                json_bytes = download_blob_bytes(OUTPUT_JSON_BLOB)
                results = json.loads(json_bytes.decode("utf-8"))

            progress_bar.progress(100)
            status_box.markdown(
                '<span class="status-pill status-success">✓ Simulation complete</span>',
                unsafe_allow_html=True
            )

            # Step 7: Render results
            render_results(results, htm_bytes)

        except GoogleAPICallError as e:
            status_box.markdown(
                '<span class="status-pill status-error">GCP API Error</span>',
                unsafe_allow_html=True
            )
            st.error(f"Google Cloud API error: {str(e)}")
        except Exception as e:
            status_box.markdown(
                '<span class="status-pill status-error">Unexpected Error</span>',
                unsafe_allow_html=True
            )
            st.error(f"Error: {str(e)}")

    # ── Previous results (if outputs already exist in bucket) ─
    elif not run_clicked:
        try:
            if blob_exists(OUTPUT_HTM_BLOB) and blob_exists(OUTPUT_JSON_BLOB):
                st.markdown(
                    '<div class="section-header">Previous Run Results</div>',
                    unsafe_allow_html=True
                )
                htm_bytes = download_blob_bytes(OUTPUT_HTM_BLOB)
                json_bytes = download_blob_bytes(OUTPUT_JSON_BLOB)
                results = json.loads(json_bytes.decode("utf-8"))
                render_results(results, htm_bytes)
        except Exception:
            pass  # No previous results or auth not set up yet — silent


if __name__ == "__main__":
    main()
