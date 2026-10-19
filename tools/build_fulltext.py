#!/usr/bin/env python3
"""말글사전 원문 전체 자료화 — 원본(PDF/HWPX/HWP) → text-<docid>.db(SQLite) + texts.json.

쓰는 법
  python3 tools/build_fulltext.py <올린 원본 폴더> <작업 폴더> [--out src] [--only docid,...]

단계: 원본 복사(원본은 고치지 않음) → 추출 → 잡음 제거(머리말·쪽번호, 제거 기록 <작업>/log/removed-<docid>.tsv)
     → 분할(법령: 장·절 머리/조/조의n/부칙/별표/별지, 지침: 쪽 'p<n>' 또는 HWPX 장·절 'Ⅵ>2>가')
     → 표 구간 표시(is_table) → 두 글자 조각 색인(grams, 앱 Query.grams와 같은 방식) → 조문 간 인용(xref)
     → <out>/text-<docid>.db, <out>/texts.json
db 형식은 scratchpad 명세(fulltext_spec.md)와 같다. 문서 목록은 tools/fulltext_docs.py.
"""
import argparse, collections, glob, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, unicodedata, zipfile, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fulltext_docs import DOCS  # noqa: E402

SCHEMA = '''
CREATE TABLE docs(docid TEXT, ed TEXT, title TEXT, kind TEXT, effective TEXT, promulgated TEXT, publisher TEXT, kogl TEXT, notice TEXT,
                  PRIMARY KEY(docid, ed));
CREATE TABLE units(uid INTEGER PRIMARY KEY, docid TEXT, ed TEXT, path TEXT, title TEXT, body TEXT, page_from INT, page_to INT, is_table INT, ord INT);
CREATE INDEX units_path ON units(docid, ed, path);
CREATE INDEX units_ord ON units(ed, ord);
CREATE VIRTUAL TABLE grams USING fts4(content="", g);
CREATE TABLE xref(src_uid INTEGER, dst_docid TEXT, dst_path TEXT, text TEXT);
CREATE INDEX xref_src ON xref(src_uid);
CREATE INDEX xref_dst ON xref(dst_docid, dst_path);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE pagemap(ed TEXT, k INT, v INT, PRIMARY KEY(ed, k));  -- 인쇄 쪽 k → 원본 PDF 쪽 v
'''

# ───────────────────────── 공통 ─────────────────────────

PUA = {'\U000f0854': '『', '\U000f0855': '』', '\U000f02eb': '◦', '\U000f02ea': '•'}


def nfc(s):
    s = unicodedata.normalize('NFC', s)
    for a_, b_ in PUA.items(): s = s.replace(a_, b_)
    return s.replace(' ', ' ').replace('　', ' ').replace('﻿', '')


def grams(key):
    """앱 Query.grams와 같음: 두 글자씩 끊어 띄어 쓴 문자열."""
    if len(key) < 2: return key
    return ' '.join(key[i:i + 2] for i in range(len(key) - 1))


def gram_tokens(body):
    """색인용: Query.grams(body)의 조각 중 앱 Query.gramMatch가 실제로 찾는 것(글자·숫자 두 개)만, 중복 없이.
    FTS4 simple 토크나이저는 ASCII를 소문자로 바꾸므로 앱 검색과 같게 된다."""
    seen = []
    s = set()
    for i in range(len(body) - 1):
        g = body[i:i + 2]
        if g in s: continue
        if g[0].isalnum() and g[1].isalnum():
            s.add(g); seen.append(g)
    return ' '.join(seen)


class Log:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, 'w', encoding='utf-8'); self.n = collections.Counter()
        self.f.write('ed\tpage\t이유\t지운 줄\n')
        self.pnum = collections.defaultdict(list)  # ed → [(물리 쪽, 인쇄 쪽 번호)]

    def __call__(self, ed, page, why, text):
        self.n[why] += 1
        if why == '쪽번호' and re.fullmatch(r'[-–—·|\s]*\d{1,4}[-–—·|\s]*', text): self.pnum[ed].append((page, int(re.sub(r'\D', '', text))))
        elif why in ('머리말', '꼬리말'):
            ns = re.findall(r'(?<![\d.])\d{1,3}(?![\d.년월])', text)
            if len(ns) == 1: self.pnum[ed].append((page, int(ns[0])))
        self.f.write(f'{ed}\t{page}\t{why}\t{text}\n')

    def close(self): self.f.close()


# ───────────────────────── PDF 줄 추출 ─────────────────────────

def pdf_pages(path):
    """쪽마다 [(y0, y1, x0, x1, text)] — pymupdf. 글꼴 문제로 pdftotext가 깨지는 파일도 읽힌다."""
    import pymupdf
    d = pymupdf.open(path)
    out = []
    for p in d:
        H = p.rect.height
        lines = []
        for b in p.get_text('dict', flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)['blocks']:
            for l in b.get('lines', []):
                if abs(l['dir'][1]) > 0.5: continue  # 세로 글자(쪽 옆 띠) 제외
                t = ''.join(s['text'] for s in l['spans'])
                t = nfc(t).rstrip()
                if not t.strip(): continue
                x0, y0, x1, y1 = l['bbox']
                lines.append([y0, y1, x0, x1, t])
        # 같은 줄(y가 겹침) 합치기
        lines.sort(key=lambda r: (round(r[0], 0), r[2]))
        merged = []
        for r in lines:
            if merged and abs(merged[-1][0] - r[0]) < 2.5 and r[2] >= merged[-1][3] - 1:
                m = merged[-1]
                gap = r[2] - m[3]
                m[4] = m[4] + (' ' if gap > 2 and not m[4].endswith(' ') else '') + r[4].lstrip()
                m[3] = r[3]; m[1] = max(m[1], r[1])
            else:
                merged.append(r)
        out.append((H, p.rect.width, merged))
    return out


def page_layout(path, pno):
    """표 쪽: pdftotext -layout(고정폭)."""
    r = subprocess.run(['pdftotext', '-layout', '-f', str(pno), '-l', str(pno), path, '-'], capture_output=True)
    t = nfc(r.stdout.decode('utf-8', 'replace')).replace('\f', '')
    t = '\n'.join(l.rstrip() for l in t.split('\n'))
    return re.sub(r'\n{3,}', '\n\n', t).strip('\n')


def broken_ratio(t):
    """깨진 글자 비율: 대체 문자·사용자 정의 영역·제어 문자."""
    if not t: return 0.0
    bad = sum(1 for c in t if c == '�' or 0xE000 <= ord(c) <= 0xF8FF or (ord(c) < 32 and c not in '\n\t'))
    return bad / len(t)


# ───────────────────────── 줄 이어 붙이기(띄어쓰기 복원) ─────────────────────────

VOCAB = collections.Counter()
BIG = collections.Counter()
CIN = collections.Counter()
CSP = collections.Counter()
JOSA1 = set('은 는 을 를 의 에 와 과 로'.split())


def vocab_add(text):
    toks = [w for w in re.split(r'\s+', text) if w]
    W = r'[가-힣A-Za-z0-9]+'
    for w in toks:
        runs = re.findall(W, w)
        for r in runs:
            VOCAB[r] += 1
            for i in range(len(r) - 1): CIN[r[i:i + 2]] += 1
    for x, y in zip(toks, toks[1:]):
        mx, my = re.search(W + '$', x), re.match(W, y)
        if mx and my:
            BIG[(mx.group(0), my.group(0))] += 1
            CSP[(mx.group(0)[-1], my.group(0)[0])] += 1


STRUCT = re.compile(r'^(제\d+(장|절|관|편)\s|[①-⑳㉑-㉟]|\d+(의\d+)?\.\s(?!\d)|[가-하]\.\s|\(\d+\)\s|\d+\)\s|[가-하]\)\s|[○◦•⦁·∙※□■▶▷◇◆●◎\-–\*]|<(개정|신설|삭제|전문|본조|제목|종전)|\[(시행일|본조|전문|제목|종전|별표|별지|시행|법률|대통령령)|부칙|별표|【)')
JOIN_NEXT = set('(<[,.)]」』>%ㆍ·:;')


def join_ok(a, b):
    """줄 끝 a와 다음 줄 첫머리 b 사이에 띄어쓰기가 없었으면 True."""
    if not a or not b: return True
    if a[-1] in '.,;:?!': return False
    if b[0] in JOIN_NEXT or a[-1] in 'ㆍ·(「『[<-–/': return True
    if a[-1].isdigit() and b[0] in '.,)호조항': return True
    if a[-1] in ')」”’』':
        mb0 = re.match(r'[가-힣]+', b)
        return bool(mb0) and re.match(r'(은|는|을|를|의|에|와|과|로|으로|이|가|에서|에게|부터|까지|만|도|및)(?![가-힣])', b) is not None
    ma = re.search(r'[가-힣A-Za-z0-9]+$', a)
    mb = re.match(r'[가-힣A-Za-z0-9]+', b)
    if not ma or not mb: return True
    wa, wbs = ma.group(0), mb.group(0)
    j = (wa + wbs)
    cj = VOCAB.get(j, 0)
    ca, cb = VOCAB.get(wa, 0), VOCAB.get(wbs, 0)
    if wbs in JOSA1 or (len(wbs) <= 3 and wbs[0] in '은는을를의에와과로' and wbs in ('으로', '에서', '에게', '로서', '로써', '으로서', '으로써', '에는', '에서는', '와의', '과의')): return True
    if wbs in ('이', '가') and not re.match(r'[가-힣]', b[len(wbs):len(wbs) + 1] or ' '): return True
    pair = BIG.get((wa, wbs), 0)
    if cj or pair:
        if cj != pair and max(cj, pair) >= 2: return cj > pair
    if ca >= 2 and cb >= 2 and cj == 0: return False
    ci, cs = CIN.get(wa[-1] + wbs[0], 0), CSP.get((wa[-1], wbs[0]), 0)
    if ci or cs: return ci >= cs
    if not cb: return True
    if ca and cb: return False
    # 둘 다 모르는 조각: 한 단어의 앞부분(같은 줄 안에 j로 시작하는 낱말)이 있으면 붙임
    if not ca and not cb: return True
    if not ca: return True   # 앞 조각이 낱말로 쓰인 적 없음 → 낱말 중간에서 끊김
    return False


GANADA = '가나다라마바사아자차카타파하'


def join_lines(lines, keep_breaks=True):
    """lines: [text] (이미 잡음 제거). 구조 머리(①, 1., 가., ○ …)에서는 줄을 바꾸고 나머지는 이어 붙인다.
    '다. '처럼 목 번호와 글이 헷갈리는 줄은 앞 목 번호의 다음 글자일 때만 목으로 본다."""
    out = []
    last = None
    for t in lines:
        s = t.strip()
        if not s: continue
        st = bool(STRUCT.match(s))
        m = re.match(r'^([가-하])[.)]\s', s)
        if st and m:
            L = m.group(1)
            ok = L == '가' or (last is not None and GANADA.index(last) + 1 < len(GANADA) and GANADA[GANADA.index(last) + 1] == L)
            if ok: last = L
            else: st = False
        elif st and re.match(r'^(\d+\.|[①-⑳])', s):
            pass
        if out and not st:
            prev = out[-1]
            out[-1] = prev + ('' if join_ok(prev.rstrip(), s) else ' ') + s
        else:
            out.append(s)
    out = [re.sub(r'(?<=\S) {2,}', ' ', o) for o in out]
    return '\n'.join(out) if keep_breaks else ' '.join(out)


# ───────────────────────── 잡음(머리말·꼬리말·쪽번호) ─────────────────────────

LAW_FOOT = re.compile(r'^(법제처|국가법령정보센터|\d{1,4}|-\s*\d{1,4}\s*-|법제처\s+\d+\s+국가법령정보센터)$')


def strip_law_noise(pages, title, ed, log, first_title=True):
    """법령 PDF: 쪽 위 법령 이름(머리말), 아래 '법제처 n 국가법령정보센터'(꼬리말) 제거."""
    res = []
    tnorm = re.sub(r'\s', '', title)
    for pi, (H, W, lines) in enumerate(pages, 1):
        keep = []
        for k, (y0, y1, x0, x1, t) in enumerate(lines):
            s = t.strip()
            if y0 > H * 0.90 and (LAW_FOOT.match(s) or re.fullmatch(r'법제처\s+\d+\s+국가법령정보센터', s)):
                log(ed, pi, '꼬리말', s); continue
            if y0 < H * 0.085 and re.sub(r'\s', '', s) in (tnorm, re.sub(r'\s', '', title.split(' (')[0])):
                log(ed, pi, '머리말', s); continue
            keep.append((pi, x0, x1, s))
        res.append(keep)
    return res


def strip_repeating(pages, ed, log):
    """지침 PDF: 여러 쪽 위·아래에 되풀이되는 줄(쪽 머리말·꼬리말)과 쪽번호 제거."""
    n = len(pages)
    top, bot = collections.Counter(), collections.Counter()

    def key(s): return re.sub(r'\d+', '#', re.sub(r'\s', '', s))
    for H, W, lines in pages:
        for (y0, y1, x0, x1, t) in lines:
            if y0 < H * 0.09: top[key(t)] += 1
            if y1 > H * 0.92: bot[key(t)] += 1
    th = max(3, n * 0.08)
    rep_top = {k for k, c in top.items() if c >= th and len(k) <= 60}
    rep_bot = {k for k, c in bot.items() if c >= th and len(k) <= 60}
    res = []
    for pi, (H, W, lines) in enumerate(pages, 1):
        keep = []
        for (y0, y1, x0, x1, t) in lines:
            s = t.strip(); k = key(s)
            if (y1 > H * 0.90 or y0 < H * 0.07) and re.fullmatch(r'[-–—·|\s]*(\d{1,4}|[ivxlcⅰ-ⅻⅠ-Ⅻ]+)[-–—·|\s]*', s, re.I):
                log(ed, pi, '쪽번호', s); continue
            if y0 < H * 0.09 and k in rep_top: log(ed, pi, '머리말', s); continue
            if y1 > H * 0.92 and k in rep_bot: log(ed, pi, '꼬리말', s); continue
            if (y1 > H * 0.90 or y0 < H * 0.07) and re.fullmatch(r'[-–—·|\s]*(\d{1,4}|[ivxlcⅰ-ⅻⅠ-Ⅻ]+)[-–—·|\s]*', s, re.I):
                log(ed, pi, '쪽번호', s); continue
            keep.append((pi, x0, x1, s))
        res.append(keep)
    return res


# ───────────────────────── 법령 분할 ─────────────────────────

ART = re.compile(r'^제(\d+)조(?:의(\d+))?(?:\(([^)]*(?:\([^)]*\))?[^)]*)\))?(?=\s|$|<|\[)')
CHAP = re.compile(r'^제(\d+)(장|절|관|편)(?:의(\d+))?\s+\S')
ADD = re.compile(r'^부\s*칙(?:\s*[<(]([^>)]*)[>)])?(.*)$')
ANNEX = re.compile(r'^(?:■\s*.{0,80}?)?\[(별표|별지)\s*(?:제\s*)?(\d+)(?:호)?(?:의\s*(\d+))?(?:호)?\s*(?:서식)?\]')
SIHAENG = re.compile(r'^\[시행일\s*:\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]\s*(.*)$')


def art_path(n, m): return f'제{n}조' + (f'의{m}' if m else '')


def parse_toc(lines):
    """앞쪽 목차(조 머리만 있는 줄)를 읽는다. 돌려줌: (목차 조 경로 목록, 본문 시작 줄 번호)."""
    toc = []
    for i, (pi, x0, x1, s) in enumerate(lines):
        m = ART.match(s)
        if m and s[m.end():].strip() == '':
            toc.append(art_path(m.group(1), m.group(2)))
            continue
        if m and s[m.end():].strip():
            return toc, i  # 본문 첫 조
        if toc and CHAP.match(s) and pi > 3 and not toc:  # noqa
            pass
    return toc, 0


def body_start(lines, toc):
    """목차가 있으면 본문의 첫 '장' 또는 첫 조를 찾는다."""
    if not toc: return 0
    first = toc[0]
    for i, (pi, x0, x1, s) in enumerate(lines):
        m = ART.match(s)
        if m and art_path(m.group(1), m.group(2)) == first and s[m.end():].strip():
            j = i
            while j > 0 and (CHAP.match(lines[j - 1][3]) or re.match(r'^제\d+(장|절)', lines[j - 1][3])): j -= 1
            return j
    return 0


def parse_law(pages_lines, pdfpath, ed, title, extra_annex=None):
    """돌려줌: units [dict(path,title,body,page_from,page_to,is_table)], toc 목록, 메모."""
    lines = [r for pg in pages_lines for r in pg]
    # 머리(법령 이름·[시행 …]·소관 부처)는 docs 표에 있으므로 단위로 두지 않음
    toc, _ = parse_toc(lines)
    st = body_start(lines, toc)
    if not toc:
        # 목차 없음: 첫 '제1장' 또는 첫 조
        for i, (pi, x0, x1, s) in enumerate(lines):
            if CHAP.match(s) or (ART.match(s) and s[ART.match(s).end():].strip()) or ADD.match(s) or ANNEX.match(s):
                st = i; break
    units = []
    cur = None
    mode = 'body'
    last_art = (0, 0)
    seen_paths = collections.Counter()

    def close():
        nonlocal cur
        if cur:
            units.append(cur)
        cur = None

    def new(kind, path, ttl, pi):
        nonlocal cur
        close()
        cur = dict(kind=kind, path=path, title=ttl, lines=[], page_from=pi, page_to=pi, is_table=0)

    i = st
    while i < len(lines):
        pi, x0, x1, s = lines[i]
        a = ANNEX.match(s)
        if a and (s.startswith('■') or x0 < 120 or mode == 'annex'):
            kind = a.group(1)
            p = ('별표' if kind == '별표' else '별지') + a.group(2) + (f'의{a.group(3)}' if a.group(3) else '')
            mode = 'annex'
            new('annex', p, s.lstrip('■ ').strip(), pi)
            cur['is_table'] = 1
            cur['lines'].append(s)
            i += 1; continue
        if mode != 'annex':
            ad = ADD.match(s)
            if ad and re.match(r'^부\s*칙', s) and (ad.group(1) is not None or s.strip() in ('부칙', '부 칙')):
                mode = 'add'
                info = (ad.group(1) or '').strip()
                num = re.search(r'(제\s*[\d\-]+호)', info)
                p = '부칙' + (f'<{num.group(1).replace(" ", "")}>' if num else (f'<{info}>' if info else ''))
                new('add', p, s.strip(), pi)
                cur['lines'].append(s)
                i += 1; continue
        if mode == 'body':
            c = CHAP.match(s)
            if c and len(s) < 60 and not ART.match(s):
                new('chap', '', s, pi)  # 경로는 아래에서
                cur['lines'].append(s)
                i += 1; continue
            m = ART.match(s)
            nxt = lines[i + 1][3] if i + 1 < len(lines) else ''
            if m and (m.group(3) is not None or re.match(r'^\s*(<?\s*삭제|\[)', s[m.end():]) or (not s[m.end():].strip() and nxt.startswith('['))):
                n, k = int(m.group(1)), int(m.group(2) or 0)
                ok = (n, k) > last_art or ((n, k) == last_art)
                if ok:
                    p = art_path(m.group(1), m.group(2))
                    new('art', p, s[:m.end()].strip(), pi)
                    last_art = (n, k)
                    cur['lines'].append(s)
                    i += 1; continue
        if cur is None:
            new('head', '머리', s, pi)
        cur['lines'].append(s)
        cur['page_to'] = pi
        i += 1
    close()
    # 장·절 경로
    chap_stack = {}
    for u in units:
        if u['kind'] == 'chap':
            c = CHAP.match(u['title'])
            lv = {'편': 0, '장': 1, '절': 2, '관': 3}[c.group(2)]
            nm = f'제{c.group(1)}{c.group(2)}' + (f'의{c.group(3)}' if c.group(3) else '')
            chap_stack = {k: v for k, v in chap_stack.items() if k < lv}
            chap_stack[lv] = nm
            u['path'] = ''.join(chap_stack[k] for k in sorted(chap_stack))
    # 같은 조가 두 벌(시행일이 다른 조문) → 뒤엣것에 [YYYY-MM-DD]
    out = []
    for u in units:
        body_lines = u['lines']
        sh = None
        for l in body_lines:
            m = SIHAENG.match(l)
            if m: sh = f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
        u['sihaeng'] = sh
    cnt = collections.Counter()
    for u in units:
        if u['kind'] == 'art' and cnt[u['path']]:
            u['path'] = u['path'] + (f'[{u["sihaeng"]}]' if u['sihaeng'] else f'[{cnt[u["path"]] + 1}]')
        cnt[u['path'].split('[')[0]] += 1
    # 부칙·별표 경로 중복 → (2), (3)
    dup = collections.Counter()
    for u in units:
        dup[u['path']] += 1
        if dup[u['path']] > 1 and u['kind'] in ('add', 'annex', 'chap', 'head'):
            u['path'] = u['path'] + f'({dup[u["path"]]})'
    for k_, u in enumerate(units):
        if u['kind'] == 'annex':
            body = '\n\n'.join(annex_layout(pdfpath, u))
            # 같은 쪽에서 다음 별표·별지가 시작하면 그 앞에서 자름(별표 목록만 실린 출력본 대비)
            nx = units[k_ + 1] if k_ + 1 < len(units) else None
            if nx is not None and nx['kind'] == 'annex' and nx['page_from'] == u['page_to']:
                key = re.sub(r'\s', '', nx['lines'][0])[:10]
                flat = []
                for j_, ch in enumerate(body):
                    if not ch.isspace(): flat.append(j_)
                fs = ''.join(body[j_] for j_ in flat)
                first = re.sub(r'\s', '', u['lines'][0])[:10]
                st_ = fs.find(first) + len(first) if fs.find(first) >= 0 else 0
                q = fs.find(key, st_)
                if q > 0: body = body[:flat[q]].rstrip()
            if body.count('\n') < 2: u['is_table'] = 0
        else:
            body = join_lines(u['lines'])
        title = u['title']
        if u['kind'] == 'art':
            title = u['title']
        out.append(dict(path=u['path'], title=title[:200], body=body, page_from=u['page_from'], page_to=u['page_to'],
                        is_table=u['is_table'], kind=u['kind'], sihaeng=u['sihaeng']))
    return out, toc


_layout_cache = {}


def annex_layout(pdfpath, u):
    """별표·별지: 고정폭 글. 첫 쪽은 머리 줄부터."""
    res = []
    for p in range(u['page_from'], u['page_to'] + 1):
        k = (pdfpath, p)
        if k not in _layout_cache: _layout_cache[k] = page_layout(pdfpath, p)
        t = _layout_cache[k]
        t = '\n'.join(l for l in t.split('\n') if not re.fullmatch(r'\s*(법제처\s+\d+\s+국가법령정보센터|법제처|국가법령정보센터|\d{1,4})\s*', l))
        if p == u['page_from']:
            head = re.sub(r'\s', '', u['lines'][0])[:12]
            ls = t.split('\n')
            for j, l in enumerate(ls):
                if re.sub(r'\s', '', l).startswith(head[:8]):
                    ls = ls[j:]; break
            t = '\n'.join(ls)
        res.append(t.strip('\n'))
    # 같은 쪽에서 다음 별표가 시작하면 그 뒤를 자름(다음 단위가 같은 쪽에서 시작하는 경우)
    return res


# ───────────────────────── 지침 PDF(쪽 단위) ─────────────────────────

def has_table(page, plpage=None):
    """표 판별(빠른 방법): 그려진 가로선 4줄 이상 + 세로선 3줄 이상이면 표. 테두리 사각형 하나(글 상자)는 표 아님."""
    hs, vs = set(), set()
    try:
        for dr in page.get_drawings():
            for it in dr.get('items', []):
                if it[0] == 'l':
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) < 1 and abs(p1.x - p2.x) > 20: hs.add(round(p1.y))
                    elif abs(p1.x - p2.x) < 1 and abs(p1.y - p2.y) > 8: vs.add(round(p1.x))
                elif it[0] == 're':
                    r = it[1]
                    if r.width > 20 and r.height < 1.5: hs.add(round(r.y0))
                    elif r.height > 8 and r.width < 1.5: vs.add(round(r.x0))
    except Exception:
        return False
    if plpage is not None:  # pdfplumber(선 기준)로도 2행·2열 이상 표가 있으면 표
        try:
            if any(len(t.extract()) >= 2 and max(len(r) for r in t.extract()) >= 2 for t in plpage.find_tables()): return True
        except Exception:
            pass
    if not (len(hs) >= 4 and len(vs) >= 3): return False
    try:  # 정밀 확인: 칸이 2행·2열 이상인 표가 있어야 함
        tf = page.find_tables()
        return any(len(t.extract()) >= 2 and max(len(r) for r in t.extract()) >= 2 for t in tf.tables)
    except Exception:
        return False


def parse_pdfpage(pages_lines, pdfpath, ed):
    import pymupdf, pdfplumber
    d = pymupdf.open(pdfpath)
    pl = pdfplumber.open(pdfpath)
    out = []
    for pi, keep in enumerate(pages_lines, 1):
        txt_lines = [s for (_, x0, x1, s) in keep]
        if not txt_lines: continue
        tbl = has_table(d[pi - 1], pl.pages[pi - 1])
        if tbl:
            body = page_layout(pdfpath, pi)
            # 머리말·꼬리말 제거 반영: 지운 줄은 layout에서도 지움
            gone = set()
            body = '\n'.join(l for l in body.split('\n'))
        else:
            body = join_lines(txt_lines)
        ttl = next((s for s in txt_lines if len(s.strip()) >= 2), '')[:80]
        out.append(dict(path=f'p{pi}', title=ttl, body=body, page_from=pi, page_to=pi, is_table=1 if tbl else 0, kind='page'))
    return out


# ───────────────────────── HWPX ─────────────────────────

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
ROMAN = 'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ'


def hx_text(el):
    """hp:t 안의 글(하위 요소 꼬리 포함). 탭은 공백."""
    parts = []
    for t in el.iter(HP + 't'):
        parts.append(''.join(t.itertext()))
    return nfc(''.join(parts))


def hx_par_text(p):
    """문단 글(표·그림 안 글 제외)."""
    parts = []
    for run in p.findall(HP + 'run'):
        for ch in run:
            if ch.tag == HP + 't': parts.append(''.join(ch.itertext()))
    return nfc(''.join(parts)).strip()


def hx_table(tbl):
    """표 → 줄마다 칸을 ' | '로. 셀 안 문단은 ' / '."""
    rows = []
    for tr in tbl.findall(HP + 'tr'):
        cells = []
        for tc in tr.findall(HP + 'tc'):
            ps = [hx_text(p).strip() for p in tc.iter(HP + 'p') if not _in_nested(p, tc)]
            cells.append(' / '.join(x for x in ps if x))
        rows.append(cells)
    return rows


def _in_nested(p, tc):
    a = p.getparent()
    while a is not None and a is not tc:
        if a.tag == HP + 'tbl': return True
        a = a.getparent()
    return False


def hx_flatten(sec_root):
    """문단 흐름: ('p', text) | ('tbl', rows). 한 칸짜리 표(글상자)는 안의 문단을 풀어 넣는다. 머리말·꼬리말·각주 컨트롤은 제외."""
    out = []

    def walk_p(p):
        txt = hx_par_text(p)
        if txt: out.append(('p', txt))
        for run in p.findall(HP + 'run'):
            for ch in run:
                if ch.tag == HP + 'tbl': walk_tbl(ch)
                elif ch.tag in (HP + 'rect', HP + 'drawText', HP + 'container', HP + 'ellipse', HP + 'polygon'):
                    for dt in ch.iter(HP + 'subList'):
                        for pp in dt.findall(HP + 'p'): walk_p(pp)
                        break

    def walk_tbl(tbl):
        rows = tbl.findall(HP + 'tr')
        ncell = sum(len(r.findall(HP + 'tc')) for r in rows)
        if ncell <= 1:
            for tc in tbl.iter(HP + 'tc'):
                sl = tc.find(HP + 'subList')
                if sl is not None:
                    for pp in sl.findall(HP + 'p'): walk_p(pp)
                break
            return
        out.append(('tbl', hx_table(tbl)))

    for p in sec_root.findall(HP + 'p'):
        walk_p(p)
    return out


H1 = re.compile(r'^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ])\s*[.．]?\s*(\S.*)?$')
H2 = re.compile(r'^(\d{1,2})\s*[.．]\s*(\S.{0,50})$')
H3 = re.compile(r'^([가-하])\s*[.．]\s*(\S.{0,50})$')
HCH = re.compile(r'^제\s*(\d+)\s*장\s*(\S.{0,50})?$')
HSEC = re.compile(r'^제\s*(\d+)\s*절\s*(\S.{0,50})?$')


def is_heading_text(t):
    return len(t) <= 60 and not re.search(r'(다|함|음|임|것)\s*\.?$', t)


def parse_hwpx(path, workdir):
    """HWPX → 장·절 단위. 경로: 장(구역 파일마다 첫머리의 Ⅰ~Ⅻ, 없으면 '부록n')>번호(1.)>가. ; 큰 표는 '…>표n'(is_table=1).
    칸이 4개 이하이고 글이 짧은 표(제목 상자)는 표가 아니라 제목 줄로 읽는다. 목차 줄(제목 뒤에 쪽 번호)은 제목으로 보지 않는다."""
    from lxml import etree
    d = os.path.join(workdir, 'hwpx', os.path.basename(path)[:8])
    if not os.path.exists(d):
        with zipfile.ZipFile(path) as z: z.extractall(d)
    secs = sorted(glob.glob(d + '/Contents/section*.xml'), key=lambda p: int(re.findall(r'\d+', os.path.basename(p))[0]))
    units = []
    used = collections.Counter()
    napp = 0
    last_roman = -1
    for si, sp in enumerate(secs):
        flow = []
        for typ, val in hx_flatten(etree.parse(sp).getroot()):
            if typ == 'tbl':
                cells = [c for r in val for c in r if c.strip()]
                if len([c for r in val for c in r]) <= 4 and sum(len(c) for c in cells) <= 80:
                    if cells: flow.append(('h', ' '.join(c.strip() for c in cells)))
                    continue
            flow.append((typ, val))
        if not flow: continue
        chap = None
        for typ, val in flow[:8]:
            if typ in ('p', 'h'):
                m = re.match(r'^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ])(?:\s*[.．]?\s*(\S.{0,40}))?$', val.strip())
                if m and not re.search(r'\d{1,3}$', val.strip()): chap = m.group(1); break
        if chap is not None and ROMAN.index(chap) <= last_roman: chap = None
        if chap is not None: last_roman = ROMAN.index(chap)
        if chap is None:
            napp += 1; chap = f'부록{napp}'
        lv1 = lv2 = None
        cur = dict(path=chap, title=flow[0][1][:60] if flow[0][0] in ('p', 'h') else chap, lines=[], is_table=0)
        tcount = collections.Counter()

        def flush():
            if cur['lines']: units.append(cur)

        for typ, val in flow:
            if typ in ('p', 'h'):
                t = val.strip()
                if not t: continue
                toc = re.search(r'\S\s*\d{1,3}$', t) and len(t) < 70
                m2 = re.match(r'^(\d{1,2})\s*[.．]\s*(\S.{0,50})$', t) or (re.match(r'^(\d{1,2})\s+([가-힣].{0,50})$', t) if typ == 'h' else None)
                m3 = re.match(r'^([가-하])\s*[.．]\s*(\S.{0,50})$', t)
                if m2 and not toc and is_heading_text(t):
                    flush(); lv1, lv2 = m2.group(1), None
                    cur = dict(path=f'{chap}>{lv1}', title=t, lines=[t], is_table=0); continue
                if m3 and lv1 and not toc and is_heading_text(t):
                    flush(); lv2 = m3.group(1)
                    cur = dict(path=f'{chap}>{lv1}>{lv2}', title=t, lines=[t], is_table=0); continue
                cur['lines'].append(t)
            else:
                body = '\n'.join(' | '.join(c.replace('\n', ' ') for c in r) for r in val)
                if not body.strip(): continue
                flush()
                base = cur['path'].split('>표')[0]
                tcount[base] += 1
                first = next((c for r in val for c in r if c.strip()), '')[:60]
                units.append(dict(path=f'{base}>표{tcount[base]}', title=f'표: {first}', lines=[body], is_table=1))
                cur = dict(path=base, title=cur['title'], lines=[], is_table=0)
        flush()
    out = []
    for u in units:
        if not u['is_table'] and out and out[-1]['path'] == u['path'] and not out[-1]['is_table']:
            out[-1]['body'] += '\n' + '\n'.join(u['lines']); continue
        used[u['path']] += 1
        p = u['path'] if used[u['path']] == 1 else f'{u["path"]}~{used[u["path"]]}'
        out.append(dict(path=p, title=(u['title'] or '')[:200], body='\n'.join(u['lines']), page_from=None, page_to=None, is_table=u['is_table'], kind='sec'))
    return out


def map_pages(units, pdf_pages_lines):
    """HWPX 단위를 같은 판 PDF의 쪽에 맞춤(본문 앞 글자 조각으로 찾기). 못 찾으면 앞 단위 쪽."""
    pages = [re.sub(r'\s', '', ''.join(s for (_, _, _, s) in pg)) for pg in pdf_pages_lines]
    allt = ''.join(pages)
    starts = []
    acc = 0
    for p in pages: starts.append(acc); acc += len(p)
    import bisect
    pos = 0; last = 1; hit = 0
    for u in units:
        b = re.sub(r'\s', '', u['body'].replace(' | ', '').replace(' / ', ''))
        found = None
        for off in (0, 20, 60, 120):
            key = b[off:off + 14]
            if len(key) < 8: continue
            j = allt.find(key, pos)
            if j < 0 or j - pos > 400000: j = allt.find(key)
            if j >= 0: found = j; break
        if found is not None:
            pg = bisect.bisect_right(starts, found)
            endk = b[-14:]
            e = allt.find(endk, found) if len(endk) >= 8 else -1
            pe = bisect.bisect_right(starts, e) if e >= 0 and e - found < len(b) * 3 + 2000 else pg
            u['page_from'], u['page_to'] = pg, max(pg, pe)
            pos = found; last = u['page_to']; hit += 1
        else:
            u['page_from'] = u['page_to'] = None
    return hit


# ───────────────────────── HWP(고시) ─────────────────────────

def hwp_paragraphs(path):
    """HWP 5 BodyText에서 문단 글(HWPTAG_PARA_TEXT=67)과 표 셀 여부(LIST_HEADER 깊이)를 읽는다."""
    import olefile, struct
    o = olefile.OleFileIO(path)
    hdr = o.openstream('FileHeader').read()
    compressed = hdr[36] & 1
    out = []
    i = 0
    while o.exists(f'BodyText/Section{i}'):
        data = o.openstream(f'BodyText/Section{i}').read()
        if compressed: data = zlib.decompress(data, -15)
        pos = 0
        tbl_level = None
        while pos < len(data):
            h = struct.unpack_from('<I', data, pos); pos += 4
            tag, level, size = h[0] & 0x3ff, (h[0] >> 10) & 0x3ff, (h[0] >> 20) & 0xfff
            if size == 0xfff: size = struct.unpack_from('<I', data, pos)[0]; pos += 4
            rec = data[pos:pos + size]; pos += size
            if tag == 77:  # CTRL_HEADER
                cid = rec[:4][::-1].decode('latin1', 'replace')
                if cid == 'tbl ': tbl_level = level
            if tag == 67:
                t = []
                k = 0
                while k + 1 < len(rec):
                    c = struct.unpack_from('<H', rec, k)[0]
                    if c in (1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23):
                        k += 16; continue
                    if c in (4, 5, 6, 7, 8, 19, 20):
                        k += 16; continue
                    if c == 9: t.append('\t')
                    elif c in (10, 13): t.append('\n')
                    elif c == 24: t.append('-')
                    elif c >= 32: t.append(chr(c))
                    k += 2
                intbl = tbl_level is not None and level > tbl_level
                if tbl_level is not None and level <= tbl_level: tbl_level = None; intbl = False
                out.append((nfc(''.join(t)).strip(), intbl))
        i += 1
    return out


def parse_hwp(path):
    paras = hwp_paragraphs(path)
    units = []
    cur = None
    chap = None
    tno = 0

    def close():
        if cur and cur['lines']: units.append(cur)
    for t, intbl in paras:
        if not t: continue
        m = re.match(r'^제\s*(\d+)\s*장\s*(.*)$', t)
        if m and not intbl and len(t) < 40:
            close(); chap = f'제{m.group(1)}장'
            cur = dict(path=chap, title=t, lines=[t], is_table=0); continue
        mt = re.match(r'^표\s*(\d+)\s+\S', t)
        if mt and not intbl and len(t) < 60:
            close(); tno = int(mt.group(1))
            cur = dict(path=f'{chap or "앞"}>표{tno}', title=t, lines=[t], is_table=1); continue
        if cur is None: cur = dict(path='머리', title=t[:60], lines=[], is_table=0)
        if intbl and not cur['is_table']:
            # 장 안의 표: 표 단위로 떼어 냄
            close(); tno += 1
            cur = dict(path=f'{chap or "앞"}>표{tno}', title='표', lines=[], is_table=1)
        elif not intbl and cur['is_table'] and not cur['path'].endswith(f'표{tno}') is False and not mt:
            pass
        if not intbl and cur['is_table'] and cur['title'] == '표':
            close(); cur = dict(path=f'{chap or "앞"}~{tno}', title=t[:60], lines=[], is_table=0)
        cur['lines'].append(t.replace('\t', ' | ') if intbl else t)
    close()
    seen = collections.Counter(); out = []
    for u in units:
        seen[u['path']] += 1
        p = u['path'] if seen[u['path']] == 1 else f'{u["path"]}({seen[u["path"]]})'
        out.append(dict(path=p, title=u['title'][:200], body='\n'.join(u['lines']), page_from=None, page_to=None, is_table=u['is_table'], kind='sec'))
    return out


# ───────────────────────── 인용(xref) ─────────────────────────

def norm_title(s): return re.sub(r'[\s·ㆍ]', '', s)


def build_xref(docmap, units_by_doc):
    """units_by_doc[docid] = [(uid, ed, path, body, kind)].
    규칙(불확실하면 넣지 않음): 「법령명」 제n조 / 같은 법(같은 법 시행령) 제n조 / '법'·'영'·'규칙'(정의된 약칭 또는 하위 법령 기본값) 제n조 /
    법령 본문 안 맨 '제n조'(같은 법). 부칙·머리 단위는 제외(다른 법 개정문이 섞임). 대상 경로가 그 문서에 실제로 있을 때만."""
    titles = {}
    for d in docmap.values():
        titles[norm_title(d['title'])] = d['docid']
    paths = {k: {p for (_, _, p, _, _) in v} for k, v in units_by_doc.items()}
    res = []
    REF = re.compile(r'(「([^」]{2,60})」\s*|같은\s*법\s*(시행령|시행규칙)?\s*|(?<![가-힣])(법|영|규칙|시행령|시행규칙)\s+|(?<![가-힣」\s])\s?)?제\s?(\d+)\s?조(?:\s?의\s?(\d+))?')
    for docid, us in units_by_doc.items():
        d = docmap[docid]
        if d['fmt'] != 'law' and d['kind'] not in ('지침', '어문'): continue
        is_law = d['fmt'] == 'law'
        # 약칭 정의: 「X」(이하 “법”이라 한다)
        alias = {}
        for (_, _, _, body, _) in us[:6]:
            for m in re.finditer(r'「([^」]{2,60})」\s*(?:\([^)]*\)\s*)?\(이하\s*[“"]([^”"]{1,6})[”"]이라\s*한다\)', body):
                t = titles.get(norm_title(m.group(1)))
                if t: alias.setdefault(m.group(2), t)
        if is_law and d.get('parent'):
            alias.setdefault('법', d['parent'])
            if d.get('dec'): alias.setdefault('영', d['dec'])
        for (uid, ed, path, body, kind) in us:
            if kind in ('add', 'head', 'chap'): continue
            last_law = None
            prev_end = -1
            # 연혁 꼬리표('[제11조의4에서 이동 …]', '[종전 제27조는 …]')의 조 번호는 옛 번호라 링크하지 않음(같은 길이 공백으로 가림)
            bt = body.replace('｢', '「').replace('｣', '」')
            bt = re.sub(r'\[[^\]\n]*(이동|종전|본조|전문개정|제목개정|시행일)[^\]\n]*\]', lambda mm: ' ' * len(mm.group(0)), bt)
            for m in REF.finditer(bt):
                full, lt, same, abbr = m.group(1), m.group(2), m.group(3), m.group(4)
                n, k = m.group(5), m.group(6)
                dst = None
                if lt is not None:
                    dst = titles.get(norm_title(lt))
                    last_law = dst if dst else ('?' + lt)
                    if not dst:
                        prev_end = m.end(); continue
                elif full and full.strip().startswith('같은'):
                    if not last_law or last_law.startswith('?'): continue
                    if same:
                        base = docmap.get(last_law)
                        cand = [x for x in docmap.values() if norm_title(x['title']) == norm_title(base['title'] + same)] if base else []
                        if not cand: continue
                        dst = cand[0]['docid']
                    else:
                        dst = last_law
                elif abbr:
                    dst = alias.get(abbr)
                    if abbr in ('시행령', '시행규칙') and is_law:
                        root = d.get('parent') or docid
                        cand = [x for x in docmap.values() if norm_title(x['title']) == norm_title(docmap[root]['title'] + ' ' + abbr)]
                        dst = cand[0]['docid'] if cand else None
                    if not dst: continue
                else:
                    if not is_law: continue
                    if re.search(r'[」』]\s*$', bt[max(0, m.start() - 4):m.start()]): continue  # 줄 바뀐 법령 이름 뒤
                    md_ = re.search(r'「([^」]{2,60})」\s*\(이하[^)]{0,20}\)\s*$', bt[max(0, m.start() - 90):m.start()])
                    if md_:
                        dst = titles.get(norm_title(md_.group(1)))
                        if not dst: continue
                        last_law = dst
                        prev_end = m.end()
                        p = art_path(n, k)
                        if p in paths.get(dst, ()) and not (dst == docid and p == path.split('[')[0]): res.append((uid, dst, p, m.group(0).strip()))
                        continue
                    # 바로 앞이 다른 법 인용의 연속('「A」 제3조 및 제5조')이면 그 법
                    pre = body[max(0, m.start() - 12):m.start()]
                    if last_law and m.start() - prev_end <= 12 and re.search(r'(및|또는|,|ㆍ|부터|와|과|제\d+[항호목]|제\d+호(의\d+)?)\s*$', pre):
                        if last_law.startswith('?'):
                            prev_end = m.end(); continue
                        dst = last_law
                    else:
                        dst = docid
                        if re.search(r'(같은|이|동)\s*$', pre): pass
                prev_end = m.end()
                if not (full and full.strip().startswith('같은') and same): last_law = dst
                p = art_path(n, k)
                if dst not in paths or p not in paths[dst]: continue
                if dst == docid and p == path.split('[')[0]: continue
                txt = m.group(0).strip()
                res.append((uid, dst, p, txt))
    # 같은 단위에서 같은 대상 중복 제거
    seen = set(); out = []
    for r in res:
        k = (r[0], r[1], r[2])
        if k in seen: continue
        seen.add(k); out.append(r)
    return out


# ───────────────────────── 주 흐름 ─────────────────────────

def find_src(updir, prefix):
    fs = [f for f in os.listdir(updir) if f.startswith(prefix)]
    if len(fs) != 1: raise SystemExit(f'원본 {prefix}: {len(fs)}개')
    return os.path.join(updir, fs[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('up'); ap.add_argument('work')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    only = set(x for x in a.only.split(',') if x)
    W = a.work
    os.makedirs(os.path.join(W, 'orig'), exist_ok=True)
    docs = [d for d in DOCS if not only or d['docid'] in only]
    docmap = {d['docid']: d for d in DOCS}
    # 1. 복사(원본은 읽기만)
    for d in DOCS:
        for e in d['editions']:
            for pre in [e['file']] + e.get('extra', []) + ([e['pdf']] if e.get('pdf') else []):
                s = find_src(a.up, pre)
                t = os.path.join(W, 'orig', os.path.basename(s))
                if not os.path.exists(t): shutil.copyfile(s, t)
    # 2. 낱말 목록(띄어쓰기 복원용): 모든 PDF 줄 안의 낱말
    cache = os.path.join(W, 'pages'); os.makedirs(cache, exist_ok=True)

    def pages_of(pre):
        cp = os.path.join(cache, pre + '.json')
        if os.path.exists(cp): return json.load(open(cp, encoding='utf-8'))
        src = find_src(os.path.join(W, 'orig'), pre)
        pg = pdf_pages(src)
        json.dump(pg, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
        return pg
    for d in DOCS:
        for e in d['editions']:
            for pre in [e['file']] + e.get('extra', []) + ([e['pdf']] if e.get('pdf') else []):
                if find_src(os.path.join(W, 'orig'), pre).endswith('.pdf'):
                    for H, Wd, lines in pages_of(pre):
                        for l in lines: vocab_add(l[4])
    report = {}
    allunits = {}
    for d in docs:
        log = Log(os.path.join(W, 'log', f'removed-{d["docid"]}.tsv'))
        eds = []
        for e in d['editions']:
            src = find_src(os.path.join(W, 'orig'), e['file'])
            fmt = e.get('fmt') or d['fmt']
            info = {}
            if fmt == 'law':
                pg = pages_of(e['file'])
                pl = strip_law_noise(pg, d['title'], e['ed'], log)
                units, toc = parse_law(pl, src, e['ed'], d['title'])
                for x in e.get('extra', []):
                    xs = find_src(os.path.join(W, 'orig'), x)
                    if xs.endswith('.hwpx'):
                        # 따로 받은 별표 HWPX(국가법령정보센터 별표 파일): 표 전체를 한 단위로, 본문 PDF의 안내 쪽(별표 제목+링크)을 바꿈
                        hu = parse_hwpx(xs, W)
                        body = '\n'.join(u['body'] for u in hu)
                        m_ = re.search(r'\[(별표)\s*(\d+)(?:의\s*(\d+))?\]', body)
                        if not m_: continue
                        pth = '별표' + m_.group(2) + (f'의{m_.group(3)}' if m_.group(3) else '')
                        nu = dict(path=pth, title=body.split('\n')[0].lstrip('■ ').strip()[:200], body=body, page_from=None, page_to=None,
                                  is_table=1, kind='annex', sihaeng=None)
                        same = [k for k, v in enumerate(units) if v['path'] == pth]
                        if same: units[same[0]] = nu
                        else: units.append(nu)
                        continue
                    xpl = strip_law_noise(pages_of(x), d['title'], e['ed'] + '+' + x, log)
                    xu, _ = parse_law(xpl, xs, e['ed'], d['title'])
                    for u in xu:
                        if u['kind'] == 'annex': u['page_from'] = u['page_to'] = None  # 따로 받은 별표 파일: 본문 PDF 쪽이 아님
                    for u in [u for u in xu if u['kind'] == 'annex']:
                        same = [k for k, v in enumerate(units) if v['path'] == u['path']]
                        if same and units[same[0]]['body'].count('\n') < 2:
                            units[same[0]] = u  # 본문 PDF에는 별표 제목만 있음 → 따로 받은 별표 본문으로 바꿈
                        elif same:
                            u['path'] += '(2)'; units.append(u)
                        else:
                            units.append(u)
                arts = [u for u in units if u['kind'] == 'art']
                info = dict(toc=len(toc), arts=len(arts), toc_missing=[p for p in toc if p not in {u['path'].split('[')[0] for u in arts}],
                            extra=[u['path'] for u in arts if u['path'].split('[')[0] not in set(toc)] if toc else [],
                            toc_dup=len(toc) - len(set(toc)), art_variants=sum(1 for u in arts if '[' in u['path']))
            elif fmt == 'pdfpage':
                pg = pages_of(e['file'])
                info['broken_pages'] = [i + 1 for i, (H, Wd, ls) in enumerate(pg) if broken_ratio(''.join(l[4] for l in ls)) > 0.02]
                pl = strip_repeating(pg, e['ed'], log)
                units = parse_pdfpage(pl, src, e['ed'])
                info['pages'] = len(pg)
            elif fmt == 'hwpx':
                units = parse_hwpx(src, W)
                if e.get('pdf'):
                    pg = pages_of(e['pdf'])
                    pl = strip_repeating(pg, e['ed'], log)
                    info['page_hit'] = map_pages(units, pl)
            elif fmt == 'hwp':
                units = parse_hwp(src)
            pm = {}
            pairs = log.pnum.get(e['ed'], [])
            byk = collections.defaultdict(set)
            for (pi, k) in pairs: byk[k].add(pi)
            # 인쇄 쪽 번호 = 물리 쪽 - 상수인 구간이 대부분: 쪽번호가 단조 증가하는 것만
            offs = collections.Counter(next(iter(v)) - k for k, v in byk.items() if len(v) == 1)
            for k, v in byk.items():
                if len(v) == 1: pm[k] = next(iter(v))
            # 쪽번호가 빠진 쪽: 앞뒤가 같은 차이면 채움
            if pm:
                ks = sorted(pm)
                for a_, b_ in zip(ks, ks[1:]):
                    if pm[b_] - pm[a_] == b_ - a_:
                        for k in range(a_ + 1, b_): pm[k] = pm[a_] + (k - a_)
            info['pagemap'] = len(pm)
            e['_pagemap'] = pm
            info['units'] = len(units)
            info['tables'] = sum(u['is_table'] for u in units)
            eds.append((e, units, info))
        log.close()
        report[d['docid']] = [(e['ed'], info) for e, u, info in eds]
        allunits[d['docid']] = eds
    # 3. db 쓰기 + xref
    uid = 0
    ubd = {}
    for docid, eds in allunits.items():
        lst = []
        for e, units, info in eds:
            for o, u in enumerate(units):
                uid += 1
                u['uid'] = uid; u['ord'] = o
                lst.append((uid, e['ed'], u['path'], u['body'], u['kind']))
        ubd[docid] = lst
    xr = build_xref(docmap, ubd) if not only else build_xref(docmap, ubd)
    xr_by = collections.defaultdict(list)
    for r in xr: xr_by[r[0]].append(r)
    texts = []
    os.makedirs(a.out, exist_ok=True)
    sizes = {}
    for docid, eds in allunits.items():
        d = docmap[docid]
        fn = os.path.join(a.out, f'text-{docid}.db')
        if os.path.exists(fn): os.remove(fn)
        con = sqlite3.connect(fn)
        con.executescript(SCHEMA)
        for e, units, info in eds:
            con.execute('INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?)', (docid, e['ed'], d['title'], d['kind'], e['effective'], e.get('promulgated'),
                                                                   d['publisher'], d['kogl'], d['notice']))
            for u in units:
                con.execute('INSERT INTO units VALUES(?,?,?,?,?,?,?,?,?,?)', (u['uid'], docid, e['ed'], u['path'], u['title'], u['body'],
                                                                            u['page_from'], u['page_to'], u['is_table'], u['ord']))
                con.execute('INSERT INTO grams(docid, g) VALUES(?,?)', (u['uid'], gram_tokens(u['title'] + '\n' + u['body'])))
                for r in xr_by.get(u['uid'], []):
                    con.execute('INSERT INTO xref VALUES(?,?,?,?)', r)
        for e, units, info in eds:
            for k, v in sorted(e.get('_pagemap', {}).items()): con.execute('INSERT INTO pagemap VALUES(?,?,?)', (e['ed'], k, v))
        con.execute('INSERT INTO meta VALUES(?,?)', ('schema', '1'))
        con.execute('INSERT INTO meta VALUES(?,?)', ('docid', docid))
        con.execute("INSERT INTO grams(grams) VALUES('optimize')")
        con.commit(); con.execute('VACUUM'); con.close()
        sha = hashlib.sha256(open(fn, 'rb').read()).hexdigest()
        srcs = []
        for e, _, _ in eds:
            srcs.append(hashlib.sha256(open(find_src(os.path.join(W, 'orig'), e['file']), 'rb').read()).hexdigest())
        texts.append(dict(docid=docid, title=d['title'], kind=d['kind'], group=d['group'], publisher=d['publisher'],
                          editions=[dict(ed=e['ed'], promulgated=e.get('promulgated'), effective=e['effective'], status_hint=e.get('status_hint'),
                                         **({'label': e['label']} if e.get('label') else {})) for e, _, _ in eds],
                          kogl=d['kogl'], notice=d['notice'], source_url=d['source_url'], fetched='2026-10-19', sha256=sha,
                          pack=f'text-{docid}', src_sha256=srcs))
    json.dump(report, open(os.path.join(W, 'report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if not only:
        order = {d['docid']: i for i, d in enumerate(DOCS)}
        texts.sort(key=lambda t: order[t['docid']])
        json.dump(texts, open(os.path.join(a.out, 'texts.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in report.items()}, ensure_ascii=False)[:20000])
    print('xref', len(xr))


if __name__ == '__main__':
    main()
