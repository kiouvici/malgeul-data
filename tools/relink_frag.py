#!/usr/bin/env python3
"""감사 13: 지침·어문 카드 srcs가 절 머리·장 차례(짧은 단위)에 걸려 카드 내용이 그 단위에 없을 때,
같은 절의 이어진 조각(path~N)·하위 단위(path>…)·같은 문서 쪽 단위 중 카드의 숫자·낱말이 가장 많이 든 곳으로 옮긴다.
쓰기: python3 tools/relink_frag.py src [--dry]"""
import json, re, sqlite3, sys, glob, os
SRC = sys.argv[1]; DRY = '--dry' in sys.argv
T = {x['docid']: x for x in json.load(open(f'{SRC}/texts.json', encoding='utf-8'))}
DB = {}
def units(d):
    if d not in DB:
        cur = max((e for e in T[d]['editions']), key=lambda e: e['effective'])['ed']
        con = sqlite3.connect(f'{SRC}/text-{d}.db')
        eds = [e['ed'] for e in T[d]['editions'] if e['effective'] <= '2026-10-21'] or [cur]
        ed = max(eds)
        DB[d] = [(p, t or '', b or '') for p, t, b in con.execute('SELECT path,title,body FROM units WHERE ed=? ORDER BY ord', (ed,))]
    return DB[d]
sq = lambda s: re.sub(r'\s', '', s).replace(',', '').replace('･', '·')
NUM = re.compile(r'\d[\d,.]*\s*(?:만\s*원|천\s*원|원|%|퍼센트|일|개월|년|세|명|시간|회)?')
def feats(c):
    txt = ' '.join(str(c.get(k, '')) for k in ('title', 'gist', 'kw', 'art'))
    nums = {sq(m.group(0)) for m in NUM.finditer(txt) if len(sq(m.group(0))) >= 2}
    words = {w for w in re.findall(r'[가-힣]{2,}', str(c.get('title', '')) + ' ' + str(c.get('kw', '')))}
    return nums, words
def score(body, f):
    b = sq(body); return sum(2 for n in f[0] if n in b) + sum(1 for w in f[1] if w in b)
changed = 0
for fn in sorted(glob.glob(f'{SRC}/reg-*.json')):
    J = json.load(open(fn, encoding='utf-8')); hit = False
    def walk(o):
        global changed
        nonlocal_hit = False
        if isinstance(o, dict):
            v = o.get('srcs')
            if isinstance(v, list) and v and 'gist' in o:
                f = feats(o)
                for r in v:
                    d = r.get('doc')
                    if d not in T or T[d]['kind'] not in ('지침', '어문') or r.get('ed'): continue
                    us = units(d); p = r['path']
                    own = ' '.join(t + ' ' + b for (pp, t, b) in us if pp == p)
                    if len(sq(own)) >= 400 and score(own, f) >= max(2, len(f[0])): continue
                    cand = [(score(t + ' ' + b, f), pp) for (pp, t, b) in us if pp.startswith(p + '~') or pp.startswith(p + '>')]
                    if not cand: continue
                    s0 = score(own, f); best = max(cand)
                    if best[0] > s0 and best[0] >= 2:
                        print(os.path.basename(fn), o.get('title'), d, p, '→', best[1], s0, best[0])
                        if len(sq(own)) < 150: r['path'] = best[1]
                        else: r['_add'] = best[1]
                        changed += 1; o['_c'] = 1
                if any('_add' in r for r in v):
                    nv = []
                    for r in v:
                        a = r.pop('_add', None); nv.append(r)
                        if a and not any(x.get('doc') == r['doc'] and x.get('path') == a for x in v): nv.append({'doc': r['doc'], 'path': a})
                    o['srcs'] = nv
            for x in o.values(): walk(x)
        elif isinstance(o, list):
            for x in o: walk(x)
    walk(J)
    def clean(o):
        if isinstance(o, dict):
            if o.pop('_c', None): globals()['hit'] = True
            for x in o.values(): clean(x)
        elif isinstance(o, list):
            for x in o: clean(x)
    hit = False; clean(J)
    if hit and not DRY:
        open(fn, 'w', encoding='utf-8').write(json.dumps(J, ensure_ascii=False, indent=1) + '\n')
print('옮김', changed)
