import json

with open(r"C:\Users\ruchi\Downloads\energyplus-simulation-875a7a99591f.json", "r") as f:
    data = json.load(f)

print("[gcp_service_account]")
for k, v in data.items():
    print(f"{k} = {json.dumps(v)}")