import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)
API_KEY = os.getenv("GEMINI_API_KEY")

print("==================================================")
print("FETCHING ALL OFFICIAL MODELS FROM GOOGLE API...")
print("==================================================")

url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
res = requests.get(url_list, timeout=10)

if res.status_code != 200:
    print(f"Error fetching model list: {res.status_code}")
    exit(1)

all_models = res.json().get("models", [])
print(f"Total models returned by Google: {len(all_models)}\n")

working_models = []
failed_models = []

for m in all_models:
    name = m.get("name", "").replace("models/", "")
    display_name = m.get("displayName", name)
    methods = m.get("supportedGenerationMethods", [])

    if "generateContent" not in methods:
        continue

    test_url = f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent?key={API_KEY}"
    payload = {"contents": [{"parts": [{"text": "Hi"}]}]}

    try:
        r = requests.post(test_url, json=payload, timeout=8)
        if r.status_code == 200:
            print(f"[WORKING - 200 OK] {display_name} ({name})")
            working_models.append((display_name, name))
        else:
            err = r.json().get("error", {}).get("message", "Error")
            failed_models.append((display_name, name, r.status_code, err[:60]))
    except Exception as e:
        failed_models.append((display_name, name, 500, str(e)[:60]))

print("\n==================================================")
print("VERIFIED WORKING MODELS FOR CONTENT GENERATION")
print("==================================================")
for disp, model_id in working_models:
    print(f" ✔ {disp} -> '{model_id}'")

print(f"\nTotal Confirmed Working: {len(working_models)}")
