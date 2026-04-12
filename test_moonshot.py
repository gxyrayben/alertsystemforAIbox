import requests
import json

# read config
with open("backend/config.json") as f:
    config = json.load(f)["llm_config"]

payload = {
    "model": config["model_name"],
    "messages": [
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "Hello"}
    ],
    "temperature": 0.7
}
url = f"{config['base_url'].rstrip('/')}/chat/completions"
headers = {"Authorization": f"Bearer {config['api_key']}"}

r = requests.post(url, headers=headers, json=payload)
print(r.status_code)
print(r.text)
