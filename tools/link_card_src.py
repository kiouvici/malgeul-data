#!/usr/bin/env python3
"""카드 ↔ 원문 조 링크: reg-*.json 카드의 근거 표기(art·src·page)에서 원문 단위를 찾아 `srcs:[{doc, path, ed?}]`를 단다.

쓰는 법  python3 tools/link_card_src.py [src 폴더] [--dry] [--miss 미연결 목록.tsv]

원칙: 근거 표기의 조각마다 원문 단위가 정확히 맞을 때만 단다. 조각 하나라도 못 맞추면 그 카드에는 달지 않는다.
- 법령·조례: '법/영/시행령/규칙/시행규칙/「법령명」/법령명' + 제n조(의m) | 별표 n | 별지 제n호.
  앞말이 없으면 앞 조각의 법령, 그것도 없으면 카드 src(basis). 앞말 없는 조각이 그 법령에 없고 카드 기본 법령에만 있으면 그쪽.
  조 범위 '제10조~제12조'·'제59조~제62조의2'는 원문 순서로 그 사이의 모든 조(가지 조 포함), 별표 범위 '별표 1~4'도 같다(양 끝이 있어야 함).
  basis가 시행 예정판(예: dec27, law0309)이면 그 판(ed)을 적는다.
- 사업안내(HWPX 7월판): '1권 Ⅵ-2-가-(6)③' → guide-child1 'Ⅵ>2>가'(가 아래 세목은 버림), '2권 Ⅳ·Ⅴ' → 'Ⅳ','Ⅴ'.
  같은 경로가 되풀이되면(~2) 꼬리 없는 첫 경로(본문 차례상 그 제목). '참고 n' 같은 덧말이 붙으면 걸지 않는다. 괄호 안 법 조문은 덧말로 보고 버린다.
- 쪽 단위 지침·해설서: page 칸(인쇄 쪽, '5~6', '23~25, 36', '15·36·44·46')을 쪽마다 pagemap으로 원본 PDF 쪽에 맞춰 'p<n>'.
  basis org가 'PDF 쪽'이면 인쇄 쪽 = PDF 쪽. 쪽 수가 40을 넘으면 걸지 않는다. HWPX(편람)는 그 쪽에 걸친 단위 모두.
- 어문: 외래어 표기법 '제1절 제n항'은 갈래 제목의 '제n장', '제2절'은 '제2절 <카드 제목>' 줄이 있는 장(하나일 때만),
  로마자 표기법 '부칙 <…>'은 그 글이 든 장(하나일 때만). 기안문 카드의 '한글 맞춤법 제n항'은 어문 맞춤법 카드의 같은 항 쪽.
- 경로가 지금 판(오늘 날짜로 현행)에 없고 다른 판 하나에만 있으면 그 판(ed)을 적는다(앱이 기본으로 여는 판은 현행).
이미 srcs가 있는 카드는 다시 계산해 덮어쓴다.
"""
import collections, datetime, glob, json, os, re, sqlite3, sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
D = args[0] if args and not sys.argv[sys.argv.index(args[0]) - 1] == '--miss' else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
DRY = '--dry' in sys.argv
MISS = sys.argv[sys.argv.index('--miss') + 1] if '--miss' in sys.argv else None
TODAY = os.environ.get('LINK_TODAY') or datetime.date.today().isoformat()
texts = json.load(open(os.path.join(D, 'texts.json'), encoding='utf-8'))
T = {t['docid']: t for t in texts}


def nt(s): return re.sub(r'(?<=\d)년', '', re.sub(r'[\s·ㆍ･,「」『』]', '', s or ''))


TITLE = {nt(t['title']): t['docid'] for t in texts}
ALIAS = {'한글맞춤법': 'eomun-spell-std', '표준어규정': 'eomun-spell-std', '문장부호': 'eomun-punct',
         '외래어표기법': 'eomun-loan', '국어의로마자표기법': 'eomun-roman', '로마자표기법': 'eomun-roman',
         '재무회계규칙': 'fin-rule'}
ORD = {}      # doc → ed → [path] (원문 순서)
PATHS = {}    # doc → ed → set(path)
PAGES = {}    # doc → ed → [(path, page_from, page_to)]
PAGEMAP = {}  # doc → ed → {인쇄 쪽: 물리 쪽}
CON = {}
for t in texts:
    con = sqlite3.connect(os.path.join(D, f'text-{t["docid"]}.db'))
    CON[t['docid']] = con
    o = collections.defaultdict(list); pg = collections.defaultdict(list)
    for ed, p, pf, pt in con.execute('SELECT ed, path, page_from, page_to FROM units ORDER BY ed, ord'):
        o[ed].append(p); pg[ed].append((p, pf, pt))
    ORD[t['docid']] = o; PATHS[t['docid']] = {e: set(v) for e, v in o.items()}; PAGES[t['docid']] = pg
    pm = collections.defaultdict(dict)
    try:
        for ed, k, v in con.execute('SELECT ed, k, v FROM pagemap'): pm[ed][int(k)] = int(v)
    except sqlite3.Error:
        pass
    PAGEMAP[t['docid']] = pm


def cur_ed(doc):
    """앱 Texts.statusOf와 같은 규칙: 오늘(포함) 이전 시행 중 가장 늦은 판."""
    eds = sorted(T[doc]['editions'], key=lambda e: e.get('effective') or '')
    past = [e for e in eds if e.get('effective') and e['effective'][:10] <= TODAY]
    return (past[-1] if past else eds[0])['ed']


def by_title(name):
    k = nt(name)
    if k in TITLE: return TITLE[k]
    for a, d in ALIAS.items():
        if k.startswith(a): return d
    return None


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
    if name.startswith('같은 조례'): return None, None
    doc = TITLE.get(nt(name))
    if not doc:
        for mo in re.findall(r'「([^」]+)」', org):
            doc = doc or TITLE.get(nt(mo))
    if not doc:
        for k, v in TITLE.items():
            if nt(name) and (k.startswith(nt(name)) or nt(name).startswith(k)) and abs(len(k) - len(nt(name))) <= 4: doc = v
    if not doc: doc = by_title(name)
    if not doc: return None, None
    ed = None
    eds = [e['ed'] for e in T[doc]['editions']]
    md = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*시행', org)
    if md:
        e = f'{int(md.group(1)):04d}-{int(md.group(2)):02d}-{int(md.group(3)):02d}'
        if e in eds and len(eds) > 1 and ('예정' in title + org or '시행판' in org): ed = e
    return doc, ed


def law_family(doc):
    t = T[doc]['title']
    base = re.sub(r'\s*(시행령|시행규칙)$', '', t)
    fam = {'법': TITLE.get(nt(base)), '영': TITLE.get(nt(base + ' 시행령')), '규칙': TITLE.get(nt(base + ' 시행규칙'))}
    if fam['영'] is None and base.endswith('규정'): fam['영'] = fam['법']  # 대통령령인 '규정'은 그 자체가 '영'
    fam['시행령'] = fam['영']; fam['시행규칙'] = fam['규칙']
    return fam


ART = r'제\s*(\d+)\s*조(?:\s*의\s*(\d+))?'
PIECE = re.compile(r'(?:(법|영|시행령|시행규칙|규칙)\s*|「([^」]+)」\s*|([가-힣][가-힣ㆍ·\s]{1,40}?(?:법|령|규칙|조례|법률))\s+)?'
                   r'(' + ART + r'(?:\s*[~∼]\s*' + ART.replace('(\\d+)', '(\\d+)') + r')?'
                   r'|별표\s*(\d+)(?:\s*의\s*(\d+))?(?:\s*[~∼]\s*(?:별표\s*)?(\d+))?|별지\s*제?\s*(\d+)\s*호(?:\s*의\s*(\d+))?)')


def art_path(n, b): return f'제{int(n)}조' + (f'의{int(b)}' if b else '')


def span(doc, ed, a, b, pat):
    """원문 순서로 a부터 b까지(양 끝 포함) pat에 맞는 경로."""
    o = ORD[doc].get(ed, [])
    if a not in o or b not in o: return None
    i, j = o.index(a), o.index(b)
    if j < i: return None
    return [p for p in o[i:j + 1] if re.fullmatch(pat, p)]


def law_refs(art, card_doc, card_ed):
    """근거 표기 → [(doc, path)] 또는 (None, 이유)."""
    s = art.replace('재무·회계', '재무ㆍ회계')
    s = re.sub(r'(?<=[조호표항])\s*·\s*(?=제|별)', ', ', s).replace('·', ',')
    fam = law_family(card_doc) if card_doc else {}
    out = []
    cur = None
    for m in PIECE.finditer(s):
        pre, q, named = m.group(1), m.group(2), m.group(3)
        if pre:
            cur = fam.get(pre)
            if cur is None: return None, f'{pre}: 원문 없음'
        elif q or named:
            nm = re.sub(r'^(및|또는|,)\s*', '', (q or named).strip())
            c2 = TITLE.get(nt(nm)) or by_title(nm)
            if c2 is None: return None, f'원문에 없는 법령: {nm}'
            cur = c2; fam = law_family(cur)
        elif cur is None:
            cur = card_doc
        if cur is None: return None, '법령 모름'
        ed = card_ed if cur == card_doc else None
        e0 = ed or cur_ed(cur)
        g = m.groups()
        if g[4]:  # 조 (범위 포함)
            a = art_path(g[4], g[5])
            if g[6]:
                b = art_path(g[6], g[7])
                ps = span(cur, e0, a, b, r'제\d+조(의\d+)?')
                if not ps:
                    return None, f'조 범위 끝을 원문에서 못 찾음: {a}~{b}'
                out += [(cur, p, ed) for p in ps]; continue
            ps = [a]
        elif g[8]:
            a = f'별표{g[8]}' + (f'의{g[9]}' if g[9] else '')
            if g[10]:
                ps = span(cur, e0, a, f'별표{g[10]}', r'별표\d+(의\d+)?')
                if not ps: return None, f'별표 범위 끝을 원문에서 못 찾음: {a}~별표{g[10]}'
            else: ps = [a]
        else:
            ps = [f'별지{g[11]}' + (f'의{g[12]}' if g[12] else '')]
        for p in ps:
            if not any(p in v for v in PATHS[cur].values()) and not (pre or q or named) and card_doc and cur != card_doc and \
                    any(p in v for v in PATHS[card_doc].values()):
                cur2 = card_doc  # '법 제74조, 영 제43조의3, 제74조의2'의 제74조의2: 영에 없고 법에만 있음
                out.append((cur2, p, card_ed)); continue
            out.append((cur, p, ed))
    if not out: return None, '조·별표 표기 없음'
    return out, ''


ROM = 'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ'
GPIECE = re.compile(r'([12])권\s*([' + ROM + r'])((?:\s*-\s*\d{1,2})?(?:\s*-\s*[가-하])?)((?:\s*-\s*\(\d+\)[①-⑳\d)]*)*)')


def guide_child_refs(art):
    a = re.sub(r'\([^()]*(법|령|규칙|별표)[^()]*\)', '', art)  # 괄호 안 근거 법령은 덧말
    out = []
    # '2권 Ⅳ·Ⅴ' → Ⅳ, Ⅴ
    a = re.sub(r'([12])권\s*([' + ROM + r'])\s*·\s*([' + ROM + r'])(?![-\d])', r'\1권 \2·\1권 \3', a)
    rest = GPIECE.sub('', a)
    if re.search(r'참고|붙임|서식|부록|[' + ROM + r']', rest): return None, f'장·절 밖 덧말: {rest.strip(" ·,")}'
    for m in GPIECE.finditer(a):
        doc = 'guide-child' + m.group(1)
        parts = [m.group(2)] + [x.strip() for x in re.split(r'\s*-\s*', m.group(3)) if x.strip()]
        p = '>'.join(parts)
        out.append((doc, p, None))
    if not out: return None, '사업안내 장·절 표기 없음'
    return out, ''


def page_list(pg):
    """'5~6' '23~25, 36' '15·36·44·46' '2, 4, 6' → [쪽]."""
    pg = str(pg or '').strip()
    if not pg: return None
    out = []
    for tok in re.split(r'\s*[,·]\s*', pg):
        m = re.fullmatch(r'(\d{1,4})(?:\s*[~∼-]\s*(\d{1,4}))?', tok)
        if not m: return None
        a = int(m.group(1)); b = int(m.group(2) or a)
        if b < a: return None
        out += list(range(a, b + 1))
    return out


def page_refs(card, doc, ed, identity):
    ks = page_list(card.get('page'))
    if not ks: return None, '쪽 표기 없음'
    if len(ks) > 40: return None, f'쪽 범위가 너무 넓음({len(ks)}쪽)'
    pm = PAGEMAP[doc].get(ed, {})
    if not pm and not identity: return None, '원본에 인쇄 쪽 번호가 없어 쪽을 맞출 수 없음'
    vs = []
    for k in ks:
        v = k if identity else pm.get(k)
        if v is None: return None, f'인쇄 {k}쪽을 원본 쪽에 맞추지 못함'
        if v not in vs: vs.append(v)
    units = PAGES[doc][ed]
    out = []
    eo = None if ed == cur_ed(doc) else ed  # 지금 판이면 판을 적지 않는다
    if all(re.fullmatch(r'p\d+', p) for p, _, _ in units):
        for v in vs:
            if f'p{v}' in PATHS[doc][ed]: out.append((doc, f'p{v}', eo))
    else:  # HWPX(편람): 그 쪽에 걸친 단위
        for v in vs:
            for p, pf, pt in units:
                if pf is not None and pf <= v <= (pt or pf) and (doc, p, eo) not in out: out.append((doc, p, eo))
    if not out: return None, '그 쪽의 원문 단위 없음(빈 쪽)'
    return out, ''


def unit_with(doc, ed, rx):
    hits = []
    for p, body in CON[doc].execute('SELECT path, body FROM units WHERE ed=? ORDER BY ord', (ed,)):
        if re.search(rx, body or '', re.M): hits.append(p)
    return hits


# 기안문 '한글 맞춤법 제n항' 용: 어문 맞춤법 카드의 항 → 쪽
SPELL_PAGE = {}
for f in glob.glob(os.path.join(D, 'reg-eomun-spell.json')):
    for g in json.load(open(f, encoding='utf-8'))['groups']:
        for c in g['cards']:
            m = re.fullmatch(r'제(\d+)항', c['art'].strip())
            if m and c.get('page'): SPELL_PAGE.setdefault(int(m.group(1)), str(c['page']))


def eomun_refs(card, group, doc, ed):
    a = card['art'].strip()
    if doc == 'eomun-loan':
        m = re.match(r'제\s*(\d+)\s*절', a)
        if m and not re.search(r'제\s*\d+\s*장', a):
            gm = re.search(r'제\s*(\d+)\s*장', group.get('title', '') or group.get('name', ''))
            if gm and f'제{gm.group(1)}장' in PATHS[doc][ed]: return [(doc, f'제{gm.group(1)}장', None)], ''
            t = re.escape(card.get('title', '').split('(')[0].strip())
            hits = unit_with(doc, ed, rf'^제\s*{m.group(1)}\s*절\s*{t}')
            if len(hits) == 1: return [(doc, hits[0], None)], ''
            return None, f'외래어 표기법 {a}: 장을 하나로 정하지 못함({len(hits)}곳)'
    if doc == 'eomun-roman':
        m = re.match(r'부칙\s*<([^,>]+)', a)
        if m:
            hits = unit_with(doc, ed, r'부칙\s*<\s*' + re.escape(m.group(1).strip()))
            if len(hits) == 1: return [(doc, hits[0], None)], ''
            return None, f'로마자 표기법 부칙: {len(hits)}곳'
    if doc == 'eomun-spell-std' and not card.get('page'):
        m = re.search(r'제\s*(\d+)(?:\s*[·,]\s*(\d+))?\s*항', a)
        if m:
            pgs = [SPELL_PAGE.get(int(x)) for x in m.groups() if x]
            if all(pgs):
                return page_refs(dict(page=', '.join(pgs)), doc, ed, False)
            return None, '맞춤법 항의 쪽을 어문 카드에서 못 찾음'
    return None, None


stats = collections.Counter()
miss = []
before = 0
for f in sorted(glob.glob(os.path.join(D, 'reg-*.json'))):
    d = json.load(open(f, encoding='utf-8'))
    basis = d.get('basis', {}) or {}
    bd = {k: basis_doc(v, basis) for k, v in basis.items()}
    for g in d['groups']:
        for c in g.get('cards', []):
            stats['cards'] += 1
            if c.get('srcs'): before += 1
            doc, bed = bd.get(c.get('src'), (None, None))
            b = basis.get(c.get('src'), {}) or {}
            refs, why = None, ''
            a = c['art']
            if re.match(r'[12]권\s*[' + ROM + r']', a) or re.search(r'·[12]권\s*[' + ROM + r']', a):
                refs, why = guide_child_refs(a)
            elif not doc:
                why = f'근거({c.get("src")}: {b.get("title", "")})의 원문 없음'
            else:
                kind = T[doc]['kind']
                ed0 = bed or cur_ed(doc)
                if kind in ('법령', '조례'):
                    refs, why = law_refs(a, doc, bed)
                elif kind == '어문':
                    refs, why = eomun_refs(c, g, doc, ed0)
                    if refs is None and why is None:
                        if re.search(r'제\s*\d+\s*장', a) and any(re.fullmatch(r'제\d+장', p) for p in PATHS[doc][ed0]):
                            mm = re.search(r'제\s*(\d+)\s*장', a); refs, why = [(doc, f'제{mm.group(1)}장', None)], ''
                        else:
                            refs, why = page_refs(c, doc, ed0, False)
                else:
                    pdf_eds = [e['ed'] for e in T[doc]['editions'] if any(re.fullmatch(r'p\d+', p) for p in PATHS[doc].get(e['ed'], ()))
                               or any(pf for _, pf, _ in PAGES[doc].get(e['ed'], []))]
                    ident = '쪽수는 PDF 쪽' in (b.get('org', '') + b.get('note', ''))
                    if pdf_eds:
                        refs, why = page_refs(c, doc, ed0 if ed0 in pdf_eds else pdf_eds[0], ident)
                    else:
                        why = '쪽 단위가 없는 지침'
            res = []
            ok = bool(refs)
            for (dd, p, e) in refs or []:
                eds = [e] if e else [cur_ed(dd)] + [x['ed'] for x in T[dd]['editions'] if x['ed'] != cur_ed(dd)]
                hit = [x for x in eds if p in PATHS[dd].get(x, ())]
                if not hit: ok = False; why = why or f'{dd} {p} 원문에 없음'; break
                item = {'doc': dd, 'path': p}
                # 판을 정해 둔 basis(예정판)이거나, 지금 판에 없는 경로면 그 판을 적는다
                if e or hit[0] != cur_ed(dd):
                    if not e and len(hit) > 1 and cur_ed(dd) not in hit: pass
                    item['ed'] = e or hit[0]
                if item not in res: res.append(item)
            if ok and res:
                c['_new'] = res; stats['linked'] += 1
            else:
                miss.append((os.path.basename(f), c.get('src', ''), a, str(c.get('page', '')), c.get('title', ''), why or '맞는 단위 없음'))
    for g in d['groups']:
        for c in g.get('cards', []):
            v = c.pop('_new', None)
            if v: c['srcs'] = v
            else: c.pop('srcs', None)
    if not DRY:
        json.dump(d, open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
stats['before'] = before
print(json.dumps(stats, ensure_ascii=False))
why_n = collections.Counter(re.sub(r'[:(].*', '', m[5]) for m in miss)
for k, n in why_n.most_common(): print(f'  {n:4d}  {k}')
if MISS:
    with open(MISS, 'w', encoding='utf-8') as fo:
        fo.write('묶음\t근거\t근거 표기\t쪽\t카드 제목\t이유\n')
        for m in miss: fo.write('\t'.join(m) + '\n')
