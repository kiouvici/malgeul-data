#!/usr/bin/env python3
"""말글사전 자료 참조·형식 검사 — 서명(publish_data.py --sign) 전에 돌려 '실패 0'이어야 한다.

쓰는 법
  python3 tools/verify_refs.py [원본 폴더(기본: src)] [--strict]

검사
  - regs.json: id·order 중복, group(법령/조례/지침/어문)과 order 범위(법령 10~80, 조례 100~199, 지침 200~299, 어문 300~399),
    hidden 묶음의 alias 대상, home 값, 묶음 파일·packs.json 등록, checked(YYYY-MM-DD)
  - reg-*.json: id·title·groups, 갈래 id 중복, 카드 art·title·gist, no/ok 형식, src가 basis에 있음, from/until 날짜와 겹침,
    같은 카드 중복, changes 날짜, checked 날짜
  - 참조 무결성(없는 묶음·조항 0건은 실패): 카드 see, paths.json 단계, deadlines.json 항목, features texts.fmt, sets.json roles 카드,
    admin.json 용어 reg. 참조는 앱과 같은 규칙(정확히 → 조항 표기 느슨 일치 → 제목 t → 낱말 q)으로 찾고, alias 묶음은 대상 묶음에서 찾는다.
  - admin.json: id·no 중복, 갈래가 categories에 있음, 용어 def, 같은 용어 중복
  - deadlines.json: id 중복, rule 형식, basis(법정/지침)
  - sets.json: id 중복, roles 역할별 카드 20장 이상
결과: [실패] 상·중, [참고] 하. 실패가 있으면 종료 코드 1(--strict면 참고도 실패로 셈).
"""
import collections, json, os, re, sys

GROUPS = {'법령': (10, 99), '조례': (100, 199), '지침': (200, 299), '어문': (300, 399)}
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
CARD_KEYS = set('art title gist no ok src page check from until note kw see'.split())


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    strict = '--strict' in sys.argv
    D = args[0] if args else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
    issues = []
    def iss(lv, msg): issues.append((lv, msg))
    def J(f):
        p = os.path.join(D, f)
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None

    packs = J('packs.json') or {}
    regs = J('regs.json') or {'books': []}
    if not DATE.match(str(regs.get('checked', ''))): iss('하', 'regs.json: checked 없음')
    books = {}
    for k, n in collections.Counter(b.get('id') for b in regs['books']).items():
        if n > 1: iss('상', f'regs: id 중복 {k}')
    for k, n in collections.Counter(b.get('order') for b in regs['books']).items():
        if n > 1: iss('상', f'regs: order 중복 {k}')
    R = {}
    for b in regs['books']:
        bid = b.get('id', '')
        books[bid] = b
        if not re.fullmatch(r'[a-z0-9_\-]{1,40}', bid): iss('상', f'regs: id 형식 {bid}')
        g = b.get('group')
        if g is not None:
            if g not in GROUPS: iss('상', f'regs {bid}: group {g} 모름')
            elif not (GROUPS[g][0] <= b.get('order', -1) <= GROUPS[g][1]): iss('중', f'regs {bid}: order {b.get("order")}가 {g} 범위 밖')
        else: iss('하', f'regs {bid}: group 없음(앱은 kind로 묶음)')
        if b.get('home') not in (None, 'bareun'): iss('중', f'regs {bid}: home {b.get("home")} 모름')
        if b.get('checked') and not DATE.fullmatch(b['checked']): iss('중', f'regs {bid}: checked 형식 {b["checked"]}')
        pf = b.get('pack') or 'reg-' + bid
        d = J(pf + '.json')
        if d is None: iss('상', f'regs {bid}: 묶음 파일 {pf}.json 없음'); continue
        if pf not in packs: iss('중', f'packs.json에 {pf} 없음')
        R[bid] = d
    for b in regs['books']:
        if b.get('hidden') and b.get('alias'):
            t = books.get(b['alias'])
            if not t: iss('상', f'regs {b["id"]}: alias {b["alias"]} 없음')
            elif t.get('hidden'): iss('상', f'regs {b["id"]}: alias 대상 {b["alias"]}도 숨김')
        elif b.get('alias'): iss('중', f'regs {b["id"]}: hidden 없이 alias')
    for f in sorted(os.listdir(D)):
        n, ext = os.path.splitext(f)
        if ext in ('.json', '.jsonl', '.sqlite') and n != 'packs' and n not in packs: iss('중', f'{f}: packs.json에 없음')
    for k, v in packs.items():
        if not isinstance(v.get('min_app'), int): iss('중', f'packs {k}: min_app 없음')

    def nart(s): return re.sub(r'\s', '', str(s or ''))
    def art_like(c, r):
        c = nart(c); r = re.sub(r'^법(?=제)', '', nart(r))
        if not r: return False
        i = c.find(r)
        return i >= 0 and not re.match(r'[의0-9]', c[i + len(r):i + len(r) + 1] or 'x') and not (i > 0 and c[i - 1].isdigit())
    def target(reg):
        b = books.get(reg)
        if b and b.get('hidden') and b.get('alias'): return b['alias']
        return reg
    def find(ref, where):
        reg = target(ref.get('reg'))
        if reg not in R: iss('상', f'{where}: 없는 묶음 {ref.get("reg")}'); return
        cards = [c for g in R[reg]['groups'] for c in g.get('cards', [])]
        art, t, q = ref.get('art'), ref.get('t'), ref.get('q')
        if not (art or t or q): return
        tok = lambda c: not t or c.get('title') == t
        if [c for c in cards if art and c.get('art') == art and tok(c)]: return
        fz = [c for c in cards if art and art_like(c.get('art'), art) and tok(c)]
        if fz:
            if len({c['art'] for c in fz}) > 1: iss('하', f'{where}: {reg} "{art}" 느슨 일치 {len(fz)}장(첫 장 {fz[0]["art"]} / {fz[0]["title"]})')
            return
        if t and [c for c in cards if c.get('title') == t]: iss('하', f'{where}: {reg} art "{art}" 불일치, 제목 "{t}"로 찾음'); return
        if q and [c for c in cards if q in c.get('title', '') + c.get('gist', '') + c.get('kw', '')]: iss('하', f'{where}: {reg} art "{art}" 불일치, 낱말 "{q}"로 찾음'); return
        iss('상', f'{where}: {reg} 조항 0건 art={art} t={t} q={q}')

    for rid, d in R.items():
        for k in ('id', 'title', 'groups'):
            if k not in d: iss('상', f'{rid}: {k} 없음')
        if d.get('id') != rid and not books[rid].get('pack'): iss('중', f'{rid}: id 불일치 {d.get("id")}')
        if not DATE.match(str(d.get('checked', ''))): iss('중', f'{rid}: checked(YYYY-MM-DD…) 없음')
        for g, n in collections.Counter(g.get('id') for g in d.get('groups', [])).items():
            if n > 1: iss('상', f'{rid}: 갈래 id 중복 {g}')
        seen = collections.Counter(); byk = collections.defaultdict(list)
        for g in d.get('groups', []):
            if not g.get('cards'): iss('중', f'{rid}/{g.get("id")}: 카드 0장')
            for c in g.get('cards', []):
                w = f'{rid}/{g.get("id")}/{c.get("title")}'
                for k in ('art', 'title', 'gist'):
                    if not c.get(k): iss('상', f'{w}: {k} 없음')
                for k in c:
                    if k not in CARD_KEYS: iss('하', f'{w}: 모르는 필드 {k}')
                if c.get('src') and c['src'] not in d.get('basis', {}): iss('중', f'{w}: src {c["src"]} basis에 없음')
                for k in ('no', 'ok'):
                    if k in c and not (isinstance(c[k], list) and all(isinstance(x, str) for x in c[k])): iss('상', f'{w}: {k} 형식')
                for k in ('from', 'until'):
                    if k in c and not DATE.fullmatch(str(c[k])): iss('상', f'{w}: {k} 날짜 형식 {c[k]}')
                if c.get('from') and c.get('until') and c['from'] > c['until']: iss('상', f'{w}: from > until')
                if 'see' in c and not isinstance(c['see'], list): iss('상', f'{w}: see 형식')
                for s in c.get('see', []) or []: find(s, w + ' see')
                seen[(c.get('art'), c.get('title'), c.get('from'))] += 1
                byk[(c.get('art'), c.get('title'))].append(c)
        for k, n in seen.items():
            if n > 1: iss('중', f'{rid}: 카드 중복 {k}')
        for k, cs in byk.items():
            if len(cs) > 1:
                iv = sorted((c.get('from', '0000-00-00'), c.get('until', '9999-12-31')) for c in cs)
                for a, b in zip(iv, iv[1:]):
                    if b[0] <= a[1]: iss('상', f'{rid}: {k} 유효기간 겹침 {a} / {b}')
        for ch in d.get('changes', []) or []:
            if not DATE.fullmatch(str(ch.get('date', ''))): iss('중', f'{rid}: changes 날짜 {ch.get("date")}')

    p = J('paths.json')
    if p:
        for k, n in collections.Counter(x.get('id') for x in p.get('paths', [])).items():
            if n > 1: iss('상', f'paths: id 중복 {k}')
        for x in p.get('paths', []):
            if not x.get('steps'): iss('중', f'paths/{x.get("id")}: 단계 없음')
            for i, s in enumerate(x.get('steps', [])): find(s, f'paths/{x.get("id")}#{i + 1}')
    dl = J('deadlines.json')
    if dl:
        for k, n in collections.Counter(i.get('id') for i in dl.get('items', [])).items():
            if n > 1: iss('상', f'deadlines: id 중복 {k}')
        for it in dl.get('items', []):
            w = f'deadlines/{it.get("id")}'
            r = it.get('rule')
            if r == 'yearly' and not re.fullmatch(r'\d{2}-(\d{2}|L)', str(it.get('md', ''))): iss('상', f'{w}: md 형식')
            elif r == 'monthly' and not re.fullmatch(r'\d{1,2}|L', str(it.get('d', ''))): iss('상', f'{w}: d 형식')
            elif r == 'date' and not DATE.fullmatch(str(it.get('date', ''))): iss('상', f'{w}: date 형식')
            elif r not in ('yearly', 'monthly', 'date'): iss('상', f'{w}: rule {r} 모름')
            if it.get('basis') not in ('법정', '지침'): iss('중', f'{w}: basis(법정/지침) 없음')
            if it.get('reg'): find(it, w)
    fe = J('features.json')
    if fe:
        for k, v in ((fe.get('texts') or {}).get('fmt') or {}).items(): find(v, f'features fmt/{k}')
        sh = (fe.get('texts') or {}).get('share')
        if sh is not None and not (isinstance(sh, dict) and isinstance(sh.get('fmt'), str)): iss('중', 'features texts.share 형식')
    s = J('sets.json')
    if s:
        for k, n in collections.Counter(x.get('id') for x in s.get('sets', []) + s.get('roles', [])).items():
            if n > 1: iss('상', f'sets: id 중복 {k}')
        for x in s.get('sets', []):
            if not isinstance(x.get('words'), list): iss('상', f'sets {x.get("id")}: words 없음(옛 앱이 멈춤)')
        for x in s.get('roles', []):
            cs = x.get('cards', [])
            if len(cs) < 20: iss('중', f'sets role {x.get("role")}: 카드 {len(cs)}장(20장 이상)')
            for k, n in collections.Counter(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in cs).items():
                if n > 1: iss('중', f'sets role {x.get("role")}: 카드 중복 {k}')
            for i, c in enumerate(cs): find(c, f'sets role {x.get("role")}#{i + 1}')
    a = J('admin.json')
    if a:
        cats = {c.get('id') for c in a.get('categories', [])}
        for f in ('id', 'no'):
            for k, n in collections.Counter(i.get(f) for i in a['items']).items():
                if n > 1: iss('상', f'admin: {f} 중복 {k}')
        for k, n in collections.Counter(re.sub(r'\s', '', i['t']) for i in a['items'] if i.get('kind') == 'term').items():
            if n > 1: iss('중', f'admin: 용어 중복 {k}')
        for i in a['items']:
            if cats and i.get('cat') not in cats: iss('상', f'admin {i["id"]}: 갈래 {i.get("cat")}가 categories에 없음')
            if i.get('kind') == 'term':
                if not i.get('def'): iss('상', f'admin 용어 {i["id"]}: def 없음')
                if i.get('reg') and target(i['reg']) not in R: iss('상', f'admin 용어 {i["id"]}: reg {i["reg"]} 없음')

    fail = [m for lv, m in issues if lv in ('상', '중') or strict]
    for lv in ('상', '중', '하'):
        L = [m for l, m in issues if l == lv]
        print(f'[{lv}] {len(L)}')
        for m in L: print('   ', m)
    print(f'실패 {len(fail)}' + (' — 서명하지 마세요' if fail else ' — 통과'))
    sys.exit(1 if fail else 0)


if __name__ == '__main__':
    main()
