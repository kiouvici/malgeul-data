#!/usr/bin/env python3
"""말글사전 자료 묶음 만들기: 원본 폴더 → malgeul-data 저장소 모양(manifest.json + packs/*.gz).

쓰는 법
  python3 tools/publish_data.py <원본 폴더> <내보낼 폴더> [--from-app <앱 assets 폴더>]
                                [--min-app N] [--release-base URL] [--release-over MB] [--sign 비밀키 파일]

원본 폴더
  <id>.json | <id>.jsonl | <id>.sqlite  묶음 하나당 파일 하나(id = 파일 이름, 영문 소문자·숫자·-·_)
  packs.json (선택)  {"<id>": {"desc": "설명", "min_app": 1}}
--from-app  앱 assets에서 기본 묶음(dadm, heot, hanja, rad)을 원본 폴더로 복사한 뒤 만든다.

판(version)은 내용이 바뀐 묶음만 'YYYY.MM.DD-N'으로 올린다(같은 내용이면 판 유지).
gzip은 시간 정보 없이 만들어 같은 내용이면 sha256이 같다.
50MB(--release-over)가 넘는 묶음은 <내보낼 폴더>/release/ 에 두고, url을 --release-base 주소로 적는다
(GitHub Release에 첨부로 올린다). --release-base가 없으면 저장소에 그대로 둔다.
--sign  Ed25519 비밀키(seed 64자리 hex, '#' 줄은 설명)로 manifest.json 바이트 전체에 서명해 manifest.sig(base64)를 쓴다.
        앱은 manifest.sig가 없거나 앱에 든 공개키로 확인되지 않으면 자료 목록을 받아들이지 않는다.
"""
import argparse, base64, datetime, gzip, hashlib, io, json, os, re, shutil, sqlite3, sys

APP_PACKS = {'dadm': 'bareun/dadm.json', 'heot': 'bareun/heot.json', 'hanja': 'hanja/hanja.json', 'rad': 'hanja/rad.json',
             'rules': 'bareun/rules.json', 'sets': 'bareun/sets.json', 'admin': 'bareun/admin.json'}
DESC = {'dadm': '다듬은 말', 'heot': '헷갈리는 말', 'hanja': '한자 자료(훈음·급수·부수·획수·필순)', 'rad': '부수 모양·부수 밖 획수', 'features': '기능 설정',
        'rules': '공문서 표기 카드', 'sets': '추천 단어 묶음', 'admin': '행정용어(알기 쉬운 행정용어 2018)'}
FMT = {'.json': 'json', '.jsonl': 'jsonl', '.sqlite': 'sqlite', '.db': 'sqlite'}


def validate(path, fmt):
    if os.path.getsize(path) == 0: raise ValueError('빈 파일')
    if fmt == 'json':
        d = json.load(open(path, encoding='utf-8'))
        if not d: raise ValueError('내용이 비었음')
    elif fmt == 'jsonl':
        n = 0
        for i, l in enumerate(open(path, encoding='utf-8')):
            if l.strip(): json.loads(l); n += 1
        if not n: raise ValueError('내용이 비었음')
    elif fmt == 'sqlite':
        with open(path, 'rb') as f:
            if f.read(15) != b'SQLite format 3': raise ValueError('SQLite 파일 아님')
        sqlite3.connect(path).execute('PRAGMA integrity_check').fetchone()


def gz_bytes(path):
    buf = io.BytesIO()
    with open(path, 'rb') as src, gzip.GzipFile(filename='', mode='wb', fileobj=buf, mtime=0, compresslevel=9) as g:
        shutil.copyfileobj(src, g)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--from-app'); ap.add_argument('--min-app', type=int, default=1)
    ap.add_argument('--release-base', default=''); ap.add_argument('--sign'); ap.add_argument('--release-over', type=float, default=50)
    a = ap.parse_args()
    os.makedirs(a.src, exist_ok=True)
    if a.from_app:
        for i, rel in APP_PACKS.items(): shutil.copyfile(os.path.join(a.from_app, rel), os.path.join(a.src, i + '.json'))

    meta = {}
    mp = os.path.join(a.src, 'packs.json')
    if os.path.exists(mp): meta = json.load(open(mp, encoding='utf-8'))
    oldp = os.path.join(a.out, 'manifest.json')
    old = {p['id']: p for p in json.load(open(oldp, encoding='utf-8')).get('packs', [])} if os.path.exists(oldp) else {}

    today = datetime.date.today().strftime('%Y.%m.%d')
    os.makedirs(os.path.join(a.out, 'packs'), exist_ok=True)
    packs = []
    for name in sorted(os.listdir(a.src)):
        base, ext = os.path.splitext(name)
        if name in ('packs.json',) or ext not in FMT: continue
        if not re.fullmatch(r'[a-z0-9_\-]{1,40}', base): sys.exit(f'묶음 이름이 맞지 않습니다: {name}')
        fmt = FMT[ext]; path = os.path.join(a.src, name)
        try: validate(path, fmt)
        except Exception as e: sys.exit(f'{name}: 검사 실패 — {e}')
        data = gz_bytes(path)
        sha = hashlib.sha256(data).hexdigest()
        m = meta.get(base, {})
        o = old.get(base)
        if o and o.get('sha256') == sha:
            ver = o['version']
        else:
            n = 1
            if o and o.get('version', '').startswith(today + '-'): n = int(o['version'].split('-')[-1]) + 1
            ver = f'{today}-{n}'
        fname = f'{base}.{fmt}.gz'
        big = len(data) > a.release_over * 1048576 and a.release_base
        if big:
            os.makedirs(os.path.join(a.out, 'release'), exist_ok=True)
            open(os.path.join(a.out, 'release', fname), 'wb').write(data)
            url = a.release_base.rstrip('/') + '/' + fname
            if os.path.exists(os.path.join(a.out, 'packs', fname)): os.remove(os.path.join(a.out, 'packs', fname))
        else:
            open(os.path.join(a.out, 'packs', fname), 'wb').write(data)
            url = 'packs/' + fname
        packs.append({'id': base, 'version': ver, 'url': url, 'sha256': sha, 'size': len(data), 'raw_size': os.path.getsize(path),
                      'format': fmt, 'gzip': True, 'min_app': int(m.get('min_app', 1)), 'desc': m.get('desc', DESC.get(base, base))})
        print(f'{base:10s} {ver:14s} {len(data) / 1024:9.1f}KB  {"(Release 첨부)" if big else ""}')
    # 원본에서 빠진 묶음의 옛 gz 정리
    keep = {p['url'].split('/')[-1] for p in packs}
    for f in os.listdir(os.path.join(a.out, 'packs')):
        if f not in keep: os.remove(os.path.join(a.out, 'packs', f))
    man = {'schema': 1, 'generated': datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
           'min_app': a.min_app, 'packs': packs}
    if old and [ {k: v for k, v in p.items()} for p in packs ] == list(old.values()) and os.path.exists(oldp):
        man['generated'] = json.load(open(oldp, encoding='utf-8')).get('generated', man['generated'])
    json.dump(man, open(oldp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if a.sign:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        seed = bytes.fromhex(''.join(l.strip() for l in open(a.sign, encoding='utf-8') if l.strip() and not l.startswith('#')))
        sig = Ed25519PrivateKey.from_private_bytes(seed).sign(open(oldp, 'rb').read())
        open(os.path.join(a.out, 'manifest.sig'), 'w').write(base64.b64encode(sig).decode() + '\n')
        print('manifest.sig: 서명함')
    elif os.path.exists(os.path.join(a.out, 'manifest.sig')):
        os.remove(os.path.join(a.out, 'manifest.sig'))
        print('경고: --sign 없이 만들어 manifest.sig를 지웠습니다(앱이 받아들이지 않음)')
    print(f'manifest.json: 묶음 {len(packs)}개 → {a.out}')


if __name__ == '__main__':
    main()
