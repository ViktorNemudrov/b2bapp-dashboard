"""Реестры рисков/допущений из Confluence (выгрузка cf_registers_*.json) → data.json.
Таблицу «вопросов» из реестра рисков не берём (Виктор 10.11.2026)."""
import json, re, sys
src, data_path = sys.argv[1], sys.argv[2]
cf = json.load(open(src, encoding='utf-8'))
d = json.load(open(data_path, encoding='utf-8'))
LVL = [('крит', 5), ('высок', 4), ('средн', 3), ('низк', 2)]
def lvl(t):
    t = (t or '').lower()
    for k, v in LVL:
        if t.startswith(k):
            return str(v)
    return '3'
R_URL = 'https://bwiki.beeline.ru/spaces/B2BAPP/pages/2107528200'
A_URL = 'https://bwiki.beeline.ru/spaces/B2BAPP/pages/2030573244'
rk = cf['Реестр рисков']; ak = cf['Реестр допущений']
risks = []
for r in rk['tables'][0][1:]:
    rid, desc, p, i, mit, owner, srcs, st = (r + [''] * 8)[:8]
    if not re.match(r'^R\d+', rid): continue
    risks.append({'id': rid, 'desc': desc, 'prob': lvl(p), 'impact': lvl(i), 'probText': p, 'impactText': i,
                  'mitigation': mit if mit.strip() not in ('', '—') else '—', 'owner': owner,
                  'status': st, 'source': srcs, 'link': R_URL})
assum = []
for r in ak['tables'][0][1:]:
    aid, desc, imp, owner, st = (r + [''] * 5)[:5]
    if not re.match(r'^A\d+', aid): continue
    assum.append({'id': aid, 'desc': desc, 'impact': imp, 'owner': owner, 'status': st,
                  'source': f'Confluence «Реестр допущений» v{ak["v"]}', 'link': A_URL})
d['risks'], d['assumptions'] = risks, assum
d['registersSource'] = {'risks': {'pageId': '2107528200', 'version': rk['v']},
                        'assumptions': {'pageId': '2030573244', 'version': ak['v']}, 'collectedAt': '2026-11-10'}
json.dump(d, open(data_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(len(risks), 'рисков,', len(assum), 'допущений;', [(r['id'], r['prob'], r['impact']) for r in risks])
