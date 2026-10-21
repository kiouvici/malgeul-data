#!/usr/bin/env python3
"""xref 다시 검사(감사 13): 인용 글 앞을 거슬러 올라가 그 번호가 어느 법의 것인지 다시 정한다.
'「다른 법」 제3조부터 제14조', '같은 법 제14조', '법 제51조제2항, …, 제59조제1항'(나열 이어받기)처럼
빌드 규칙이 놓친 경우를 바로잡는다. 맞는 법이 원문 목록에 있고 그 조가 있으면 대상을 고치고, 없으면 링크를 뺀다.
쓰기: python3 tools/fix_xref.py src [--dry]"""
import json, re, sqlite3, sys
SRC = sys.argv[1] if len(sys.argv) > 1 else 'src'
DRY = '--dry' in sys.argv
T = json.load(open(f'{SRC}/texts.json', encoding='utf-8'))
nt = lambda s: re.sub(r'[\s·ㆍ「」]', '', s)
TITLE = {nt(x['title']): x['docid'] for x in T}
IDS = {x['docid'] for x in T}
CHAIN = re.compile(r'(?:같은\s?조|제\s?\d+\s?조(?:\s?의\s?\d+)?|제\s?\d+\s?[항호목](?:\s?의\s?\d+)?|각\s?호|단서|본문|전단|후단|ㆍ|·|,|및|또는|부터|까지|와|과|\s)+$')
def fam(docid, kind):
    if '-' not in docid: return None
    b, s = docid.rsplit('-', 1)
    if s not in ('act', 'dec', 'rule'): return None
    t = {'법': 'act', '영': 'dec', '시행령': 'dec', '규칙': 'rule', '시행규칙': 'rule'}[kind]
    d = f'{b}-{t}'; return d if d in IDS else None
def owner(docid, pre):
    """pre: 인용 바로 앞 글. 돌려줌: 대상 docid, None(코퍼스에 없는 다른 법 → 링크 없음), '' (판단 못 함 → 그대로)"""
    s = CHAIN.sub('', pre)
    m = re.search(r'「([^」]{2,60})」\s*(?:\([^)]{0,30}\)\s*)?$', s)
    if m: return TITLE.get(nt(m.group(1)))
    m = re.search(r'같은\s*법\s*(시행령|시행규칙)?\s*$', s)
    if m:
        lm = list(re.finditer(r'「([^」]{2,60})」', s))
        if not lm: return ''
        t = lm[-1].group(1) + (m.group(1) or '')
        return TITLE.get(nt(t))
    m = re.search(r'(?<![가-힣])(법|영|규칙|시행령|시행규칙)\s*$', s)
    if m: return fam(docid, m.group(1)) or ''
    if s.strip() == '': return ''
    return docid if re.search(r'[^가-힣」]$|[은는이가을를의에서로도]$|따른$|정한$|규정한$|같은$', s) else ''
fixed = dropped = 0
for x in T:
    d = x['docid']; f = f'{SRC}/text-{d}.db'
    con = sqlite3.connect(f)
    paths = {}
    def has(dd, p):
        if dd not in paths:
            try: paths[dd] = {r[0] for r in sqlite3.connect(f'{SRC}/text-{dd}.db').execute('SELECT DISTINCT path FROM units')}
            except Exception: paths[dd] = set()
        return p in paths[dd]
    rows = con.execute('SELECT x.rowid, x.src_uid, x.dst_docid, x.dst_path, x.text, u.body FROM xref x JOIN units u ON u.uid=x.src_uid').fetchall()
    for rid, uid, dd, dp, txt, body in rows:
        b = (body or '').replace('｢', '「').replace('｣', '」')
        mt = re.match(r'^(.*?)(제\s?\d+\s?조.*)$', txt, re.S)
        occ = []; i = b.find(txt)
        while i >= 0:
            occ.append((i, owner(d, b[max(0, i - 400):i] + (mt.group(1) if mt else ''))))
            i = b.find(txt, i + 1)
        if not occ: continue
        # 앱은 본문에서 처음 나온 자리에 링크를 단다: 그 자리가 맞으면 그대로
        if occ[0][1] in ('', dd): continue
        good = [o for o in occ if o[1] == dd]
        if good:
            # 맞는 자리가 뒤에 있으면 뒷글을 붙여 그 자리가 처음이 되게
            j = good[0][0]; t2 = txt
            for n in range(1, 30):
                t2 = b[j:j + len(txt) + n]
                if b.find(t2) == j: break
            if b.find(t2) == j and '\n' not in t2[len(txt):]:
                if not DRY: con.execute('UPDATE xref SET text=? WHERE rowid=?', (t2, rid))
                fixed += 1; print('자리', d, dp, repr(t2)); continue
        own = occ[0][1]; i = occ[0][0]
        if own is None or not has(own, dp):
            if not DRY: con.execute('DELETE FROM xref WHERE rowid=?', (rid,))
            dropped += 1; print('뺌', d, dp, '→', dd, '|', b[max(0, i - 40):i + len(txt)].replace('\n', ' '))
        else:
            if not DRY: con.execute('UPDATE xref SET dst_docid=? WHERE rowid=?', (own, rid))
            fixed += 1; print('고침', d, dp, dd, '→', own, '|', b[max(0, i - 40):i + len(txt)].replace('\n', ' '))
    if not DRY: con.commit()
    con.close()
print('고침', fixed, '뺌', dropped)
