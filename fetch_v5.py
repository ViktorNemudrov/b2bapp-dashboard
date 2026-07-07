import os, base64, json, urllib.request, urllib.error

# Читаем токен из .env
env = {}
if os.path.exists('.env'):
    for line in open('.env'):
        if '=' in line:
            k,v = line.strip().split('=',1)
            env[k] = v

tok = env.get('GITHUB_TOKEN','')
if not tok:
    raise Exception('.env не найден или GITHUB_TOKEN не задан')

owner = 'ViktorNemudrov'
repo  = 'b2bapp-dashboard'
base  = f'https://api.github.com/repos/{owner}/{repo}'
hdr   = {'Authorization': f'token {tok}', 'Accept': 'application/vnd.github.v3+json', 'Content-Type': 'application/json'}

def api_get(url):
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def create_blob(b64):
    req = urllib.request.Request(f'{base}/git/blobs', headers=hdr, method='POST')
    req.data = json.dumps({'content': b64, 'encoding': 'base64'}).encode()
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())['sha']

def create_tree(base_tree, items):
    req = urllib.request.Request(f'{base}/git/trees', headers=hdr, method='POST')
    req.data = json.dumps({'base_tree': base_tree, 'tree': items}).encode()
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())['sha']

def create_commit(msg, tree, parent):
    req = urllib.request.Request(f'{base}/git/commits', headers=hdr, method='POST')
    req.data = json.dumps({'message': msg, 'tree': tree, 'parents': [parent]}).encode()
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())['sha']

def update_ref(sha):
    req = urllib.request.Request(f'{base}/git/refs/heads/main', headers=hdr, method='PATCH')
    req.data = json.dumps({'sha': sha}).encode()
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# Файлы для пуша
FILES = [
    ('public/index.html',              'public/index.html'),
    ('public/pages/stakeholders.html', 'public/pages/stakeholders.html'),
    ('public/pages/okr.html',          'public/pages/okr.html'),
    ('public/data/manual.json',        'public/data/manual.json'),
]

# Получаем HEAD
print('Getting HEAD...')
ref = api_get(f'{base}/git/ref/heads/main')
head_sha = ref['object']['sha']
commit = api_get(f'{base}/git/commits/{head_sha}')
base_tree = commit['tree']['sha']
print(f'HEAD: {head_sha[:8]}, tree: {base_tree[:8]}')

# Создаём blobs
tree_items = []
for local, gh_path in FILES:
    if not os.path.exists(local):
        print(f'SKIP {local} - not found')
        continue
    print(f'Creating blob for {gh_path}...')
    with open(local, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    blob_sha = create_blob(b64)
    tree_items.append({'path': gh_path, 'mode': '100644', 'type': 'blob', 'sha': blob_sha})
    print(f'  blob: {blob_sha[:8]}')

# Создаём tree
print('Creating tree...')
new_tree = create_tree(base_tree, tree_items)
print(f'  tree: {new_tree[:8]}')

# Создаём commit
print('Creating commit...')
new_commit = create_commit('feat: dashboard v5 - auth, themes, OKR, RACI, fixes', new_tree, head_sha)
print(f'  commit: {new_commit[:8]}')

# Обновляем ref
print('Updating main...')
update_ref(new_commit)
print('Done! Vercel deploys automatically.')
