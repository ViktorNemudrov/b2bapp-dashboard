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

def list_remote(gh_dir):
    """Recursively list file paths under gh_dir in the GitHub repo."""
    url = f"{BASE}/contents/{gh_dir}"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req) as r:
            entries = json.loads(r.read())
    except Exception:
        return []
    out = []
    for e in entries:
        if e["type"] == "dir":
            out.extend(list_remote(e["path"]))
        else:
            out.append(e["path"])
    return out

def delete(gh_path, msg):
    url = f"{BASE}/contents/{gh_path}"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read())["sha"]
    except Exception as e:
        print(f"SKIP delete {gh_path}: {e}"); return
    body = json.dumps({"message": msg, "sha": sha}).encode()
    req2 = urllib.request.Request(url, headers=HDR, method="DELETE")
    req2.data = body
    try:
        with urllib.request.urlopen(req2) as r:
            r.read()
        print(f"DEL {gh_path}")
    except Exception as e:
        print(f"ERR delete {gh_path}: {e}")

def prune_removed(root="public", msg="chore: remove files deleted locally"):
    """Delete files that exist on GitHub under public/ but no longer exist locally."""
    local = {gh for gh, _ in collect_files(root)}
    remote = set(list_remote(root))
    for gh_path in sorted(remote - local):
        delete(gh_path, msg)

if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "feat: dashboard update"
    for gh, loc in collect_files():
        push(gh, loc, msg)
    print("Done! Vercel deploys automatically.")
    # Note: prune_removed(msg=msg) is available but NOT run automatically —
    # it deletes files from GitHub/Vercel that no longer exist locally under public/.
    # Run it manually and deliberately (python -c "import update; update.prune_removed()")
    # when a file was intentionally removed, after reviewing what it would delete.
