import os
import subprocess
import glob
from google.cloud import storage

# --- Configuration from Environment Variables ---
BUCKET_NAME = os.environ.get("BUCKET_NAME")
IDF_FILE = os.environ.get("IDF_FILE")       # e.g., "inputs/my_building.idf"
EPW_FILE = os.environ.get("EPW_FILE")        # e.g., "inputs/weather.epw"

# Local working directories inside the container
WORK_DIR = "/tmp/ep_run"
INPUT_DIR = os.path.join(WORK_DIR, "input")
OUTPUT_DIR = os.path.join(WORK_DIR, "output")

# Where EnergyPlus is installed inside the container (we'll set this up in the Dockerfile later)
ENERGYPLUS_PATH = "/usr/local/EnergyPlus-22-1-0/energyplus"

def download_from_gcs(bucket_name, source_blob_path, destination_file_path):
    """Downloads a single file from GCS to the local container filesystem."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(source_blob_path)
    
    # Ensure the local directory exists before downloading
    os.makedirs(os.path.dirname(destination_file_path), exist_ok=True)
    
    blob.download_to_filename(destination_file_path)
    print(f"  Downloaded: gs://{bucket_name}/{source_blob_path}")
    print(f"         -> {destination_file_path}")

def upload_to_gcs(bucket_name, source_file_path, destination_blob_path):
    """Uploads a single file from the local container filesystem to GCS."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_path)
    
    blob.upload_from_filename(source_file_path)
    print(f"  Uploaded: {source_file_path}")
    print(f"       -> gs://{bucket_name}/{destination_blob_path}")

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
    print(f"\nWork directory: {WORK_DIR}")

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

    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    # Print EnergyPlus stdout and stderr for debugging
    print("--- EnergyPlus STDOUT ---")
    print(result.stdout)
    if result.stderr:
        print("--- EnergyPlus STDERR ---")
        print(result.stderr)

    # --- Step 4: Check result and upload outputs ---
    if result.returncode != 0:
        print(f"\nERROR: EnergyPlus exited with code {result.returncode}")
        # Still try to upload outputs — error logs are valuable for debugging
    else:
        print("\nSUCCESS: EnergyPlus simulation completed.")

    print("\n--- Uploading Output Files ---")
    output_files = glob.glob(os.path.join(OUTPUT_DIR, "*"))

    if not output_files:
        print("WARNING: No output files found to upload.")
    else:
        for filepath in output_files:
            filename = os.path.basename(filepath)
            gcs_output_path = f"outputs/{filename}"
            upload_to_gcs(BUCKET_NAME, filepath, gcs_output_path)

    print("\n" + "=" * 60)
    print("EnergyPlus Cloud Run Job - Finished")
    print("=" * 60)

    # Exit with the same code as EnergyPlus so Cloud Run knows if it failed
    if result.returncode != 0:
        exit(1)

if __name__ == "__main__":
    main()