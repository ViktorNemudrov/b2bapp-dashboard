import urllib.request, os, base64, json, sys

def load_env(path=".env"):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

load_env()
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
if not TOKEN or TOKEN == "сюда_вставь_токен":
    sys.exit("GITHUB_TOKEN не задан. Впишите его в .env")
OWNER = "ViktorNemudrov"
REPO  = "b2bapp-dashboard"
BASE  = f"https://api.github.com/repos/{OWNER}/{REPO}"
HDR   = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"}

def push(gh_path, local_path, msg):
    if not os.path.exists(local_path):
        print(f"SKIP {local_path} not found"); return
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    url = f"{BASE}/contents/{gh_path}"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read()).get("sha")
    except: sha = None
    body = {"message": msg, "content": b64}
    if sha: body["sha"] = sha
    req2 = urllib.request.Request(url, headers=HDR, method="PUT")
    req2.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req2) as r:
            res = json.loads(r.read())
        print(f"OK  {gh_path} -> {res['content']['sha'][:8]}")
    except Exception as e:
        print(f"ERR {gh_path}: {e}")

FILES = [
    ("public/index.html",               "public/index.html"),
    ("public/pages/stakeholders.html",  "public/pages/stakeholders.html"),
    ("public/pages/okr.html",           "public/pages/okr.html"),
    ("public/data/manual.json",         "public/data/manual.json"),
]
for gh, loc in FILES:
    push(gh, loc, f"feat: dashboard v5 update {loc.split('/')[-1]}")
print("Done! Vercel deploys automatically.")
