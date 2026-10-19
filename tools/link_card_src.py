#!/usr/bin/env python3
"""카드 ↔ 원문 조 링크: reg-*.json 카드의 근거 표기(art·src·page)에서 원문 단위 후보를 찾아 `src:[{doc, path, ed?}]`를 단다.

쓰는 법  python3 tools/link_card_src.py [src 폴더] [--dry]

원칙: 근거 표기의 조각마다 원문 단위가 '정확히 하나'로 맞을 때만 단다. 조각 하나라도 못 맞추면(조 범위 '제3조~제8조',
우리 원문에 없는 법령, 쪽 범위 등) 그 카드에는 달지 않는다. 이미 src 목록이 있는 카드는 다시 계산해 덮어쓴다.
- 법령: '법/영/시행령/규칙/시행규칙/「법령명」/법령명' + 제n조(의m) | 별표 n | 별지 제n호. 앞말이 없으면 앞 조각의 법령, 그것도 없으면 카드 src(basis).
  basis가 시행 예정판(예: dec27, law0309)이면 그 판(ed)을 적는다.
- 지침(HWPX 판): '1권 Ⅵ-2-가' → 경로 'Ⅵ>2>가'(괄호 이하 세목은 버림).
- 쪽 단위 지침·해설서: page가 한 쪽이면 인쇄 쪽 → 원본 PDF 쪽(쪽번호 기록으로 맞춤) → 'p<n>'.
- 고시(HWP): '제n장 …' → 경로 '제n장'.
"""
import collections, glob, json, os, re, sqlite3, sys

D = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
DRY = '--dry' in sys.argv
texts = json.load(open(os.path.join(D, 'texts.json'), encoding='utf-8'))
T = {t['docid']: t for t in texts}


def nt(s): return re.sub(r'(?<=\d)년', '', re.sub(r'[\s·ㆍ･,「」『』]', '', s or ''))


TITLE = {nt(t['title']): t['docid'] for t in texts}
PATHS = {}
PAGEMAP = {}
for t in texts:
    con = sqlite3.connect(os.path.join(D, f'text-{t["docid"]}.db'))
    ps = collections.defaultdict(set)
    for ed, p in con.execute('SELECT ed, path FROM units'): ps[ed].add(p)
    PATHS[t['docid']] = ps
    try:
        PAGEMAP[t['docid']] = {(ed, int(k)): int(v) for ed, k, v in con.execute("SELECT ed, k, v FROM pagemap")}
    except sqlite3.Error:
        PAGEMAP[t['docid']] = {}
    con.close()


def basis_doc(b, basis):
    """basis 항목 → (docid, ed|None)."""
    title = b.get('title', '')
    org = b.get('org', '') or ''
    m = re.search(r'「([^」]+)」', title)
    name = m.group(1) if m else title
    name = re.sub(r'\(.*?\)', '', name).strip()
    if name.startswith('같은 법'):
        base = None
        for v in basis.values():
            mm = re.search(r'「([^」]+)」', v.get('title', ''))
            if mm and not mm.group(1).endswith(('시행령', '시행규칙')): base = mm.group(1); break
        if not base: return None, None
        name = base + ' ' + name.replace('같은 법', '').strip()
    doc = TITLE.get(nt(name))
    if not doc:
        for mo in re.findall(r'「([^」]+)」', org):
            doc = doc or TITLE.get(nt(mo))
    if not doc:
        for k, v in TITLE.items():
            if nt(name) and (k.startswith(nt(name)) or nt(name).startswith(k)) and abs(len(k) - len(nt(name))) <= 4: doc = v
    if not doc: return None, None
    ed = None
    eds = [e['ed'] for e in T[doc]['editions']]
    md = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*시행', org)
    if md:
        e = f'{int(md.group(1)):04d}-{int(md.group(2)):02d}-{int(md.group(3)):02d}'
        if e in eds and len(eds) > 1 and ('예정' in title + org or '시행판' in org): ed = e
    return doc, ed


def law_family(doc):
    """법/영/규칙 짝."""
    t = T[doc]['title']
    base = re.sub(r'\s*(시행령|시행규칙)$', '', t)
    fam = {'법': TITLE.get(nt(base)), '영': TITLE.get(nt(base + ' 시행령')), '규칙': TITLE.get(nt(base + ' 시행규칙'))}
    if fam['영'] is None and base.endswith('규정'): fam['영'] = fam['법']  # 대통령령인 '규정'은 그 자체가 '영'
    fam['시행령'] = fam['영']; fam['시행규칙'] = fam['규칙']
    return fam


PIECE = re.compile(r'(?:(법|영|시행령|시행규칙|규칙)\s*|「([^」]+)」\s*|([가-힣][가-힣ㆍ·\s]{1,40}?(?:법|령|규칙|조례|법률))\s+)?(제\s*(\d+)\s*조(?:\s*의\s*(\d+))?|별표\s*(\d+)(?:\s*의\s*(\d+))?|별지\s*제?\s*(\d+)\s*호(?:\s*의\s*(\d+))?)')


def law_refs(art, card_doc):
    """근거 표기 → [(doc, path)] 또는 None(못 맞춤)."""
    s = art.replace('재무·회계', '재무ㆍ회계').replace('·', ',')
    if re.search(r'제\s*\d+\s*조(의\s*\d+)?\s*[~∼]\s*제?\s*\d+\s*조', s): return None  # 조 범위
    fam = law_family(card_doc) if card_doc else {}
    out = []
    cur = None
    for m in PIECE.finditer(s):
        pre, q, named = m.group(1), m.group(2), m.group(3)
        if pre:
            cur = fam.get(pre)
            if cur is None: return None
        elif q or named:
            nm = re.sub(r'^(및|또는|,)\s*', '', (q or named).strip())
            nm = nm.replace('재무,회계 규칙', '사회복지법인 및 사회복지시설 재무ㆍ회계 규칙').replace('재무·회계 규칙', '사회복지법인 및 사회복지시설 재무ㆍ회계 규칙')
            cur = TITLE.get(nt(nm))
            if cur is None and nt(nm) in ('재무회계규칙',): cur = TITLE.get(nt('사회복지법인 및 사회복지시설 재무ㆍ회계 규칙'))
            if cur is None: return None
            fam = law_family(cur)
        elif cur is None:
            cur = card_doc
        if cur is None: return None
        if m.group(5):
            p = f'제{m.group(5)}조' + (f'의{m.group(6)}' if m.group(6) else '')
        elif m.group(7):
            p = f'별표{m.group(7)}' + (f'의{m.group(8)}' if m.group(8) else '')
        else:
            p = f'별지{m.group(9)}' + (f'의{m.group(10)}' if m.group(10) else '')
        out.append((cur, p))
    # 근거 표기에 조·별표가 아닌 다른 법령 이름만 있는 경우 등
    rest = PIECE.sub('', s)
    if re.search(r'(법|령|규칙|조례|법률)\b', re.sub(r'\b(법|영|규칙|시행령|시행규칙)\b', '', rest)) and re.search(r'[가-힣]{2,}(법|법률)\s*제', art): return None
    return out or None


def guide_refs(card, doc, ed):
    a = card['art']
    m = re.search(r'([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ])((?:-[0-9]{1,2})?(?:-[가-하])?)(?![·,ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])', a)
    if not m or re.search(r'[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]\s*[·,]', a) or a.count('-') and ',' in a: return None
    parts = [m.group(1)] + [x for x in m.group(2).split('-') if x]
    p = '>'.join(parts)
    return [(doc, p)]


def page_refs(card, doc, ed):
    pg = str(card.get('page', '')).strip()
    if not re.fullmatch(r'\d{1,4}', pg): return None
    k = (ed, int(pg))
    mp = PAGEMAP.get(doc, {})
    if k not in mp: return None
    return [(doc, f'p{mp[k]}')]


stats = collections.Counter()
miss = collections.defaultdict(list)
for f in sorted(glob.glob(os.path.join(D, 'reg-*.json'))):
    d = json.load(open(f, encoding='utf-8'))
    basis = d.get('basis', {}) or {}
    bd = {k: basis_doc(v, basis) for k, v in basis.items()}
    changed = False
    for g in d['groups']:
        for c in g.get('cards', []):
            stats['cards'] += 1
            doc, ed = bd.get(c.get('src'), (None, None))
            refs = None
            if doc:
                fmt_page = all(p.startswith('p') for p in PATHS[doc].get(T[doc]['editions'][0]['ed'], {'p1'}))
                kind = T[doc]['kind']
                ed0 = ed or T[doc]['editions'][0]['ed']
                if kind in ('법령', '조례'):
                    refs = law_refs(c['art'], doc)
                elif any('>' in p for p in PATHS[doc].get(ed0, ())) and re.search(r'[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]', c['art']):
                    refs = None  # HWPX 장·절 경로는 원문 번호 매김이 고르지 않아 자동으로 걸지 않음
                elif re.search(r'제\s*\d+\s*장', c['art']) and any(p.startswith('제') and p.endswith('장') for p in PATHS[doc].get(ed0, ())):
                    mm = re.search(r'제\s*(\d+)\s*장', c['art'])
                    refs = [(doc, f'제{mm.group(1)}장')]
                else:
                    refs = page_refs(c, doc, ed0)
            res = []
            ok = bool(refs)
            for (dd, p) in refs or []:
                e = ed if (dd == doc and ed) else None
                eds = [e] if e else [x['ed'] for x in T[dd]['editions']]
                hit = [x for x in eds if p in PATHS[dd].get(x, ())]
                # 정확히 하나: 지정 판에 있거나, 판 지정 없을 때 현행(첫 판)에 있음
                if not hit: ok = False; break
                item = {'doc': dd, 'path': p}
                if e: item['ed'] = e
                if item not in res: res.append(item)
            old = c.get('src_t') if False else None
            if ok and res:
                if c.get('srcs') != res: pass
                c['_new'] = res
                stats['linked'] += 1
            else:
                miss[os.path.basename(f)].append(c['art'])
            changed = True
    for g in d['groups']:
        for c in g.get('cards', []):
            v = c.pop('_new', None)
            # 카드의 src는 이미 basis 키(문자열)로 쓰이므로 원문 링크는 새 필드 'srcs'(명세 확정).
            if v: c['srcs'] = v
            else: c.pop('srcs', None)
    if not DRY:
        json.dump(d, open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(stats, ensure_ascii=False))
for k, v in miss.items(): print(k, len(v), v[:8])
