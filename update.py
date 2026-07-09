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

def collect_files(root="public"):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            local_path = os.path.join(dirpath, fn).replace("\\", "/")
            files.append((local_path, local_path))
    return sorted(files)

if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "feat: dashboard update"
    for gh, loc in collect_files():
        push(gh, loc, msg)
    print("Done! Vercel deploys automatically.")
