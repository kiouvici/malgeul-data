# malgeul-data — 말글사전(어른앱) 데이터 꾸러미 (공개 저장소)

말글사전이 받아 쓰는 자료: 한자(hanja), 헷갈리는 말(heot), 부수(rad), 업무 규정·지침(reg-*), 원문(text-*·fulltext), 서식(admin·dadm) 등.
공통 규칙은 `~/.claude/CLAUDE.md`, 앱 설명은 `../malgeul/CLAUDE.md`.

## 게시
```
python tools/publish_data.py src . --sign ~/.kdict-keys/malgeul_data_signing.key
```
- Ed25519 서명. `--sign` 없이 만들면 manifest.sig가 지워져 앱이 받지 않는다. 키는 절대 커밋하지 않는다.
- 게시 후 commit·push(main).

## 아이앱(kdict)과 공유
- hanja의 h, u(훈음)와 p, ps, od, pv(필순)만 공유. kdict-data에서 바뀐 글자의 해당 필드만 패치한다. hanja.json 통째 복사 금지.
- 말글사전 앱은 0.1.15(malgeul ff03320)부터 pv를 따른다(jp·kr·aj 또는 pv:1일 때만 필순 보기) → 조합 필순도 kdict-data와 같게 p·ps·od·pv를 그대로 둔다(2026-10-24 비워 둔 2,897자 되살림).
- 공유 안 함: 급수 lv, 어른용 훈(女 '계집 녀' 등), heot·rad·reg-*·text-* 등 나머지 전부. 아이앱 자료(kid_block·vocab·받아쓰기 등)를 넣지 않는다.
