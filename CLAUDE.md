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

## 사전 앱 예외(공통 규칙 원본 kiouvici/dev-setup에 더해, 2026-10-24 대표님 결정)
- **inbox**: `~/dev/kdict-docs/inbox/` + kdict-docs PR #1(댓글로 알림). 목업은 노트북이 만들어 대화창에 보고한다.
- **Git**: kdict-data·malgeul-data는 main push = 게시이므로 main에 직접(게시 스크립트·공유 필드 검사 통과 뒤). kdict-docs는 문서·inbox라 main 직접. kdict·malgeul은 Actions 결제가 풀릴 때까지 자동 검사가 돌지 않으므로 노트북 검사(node --check·단위 시험·끝말잇기 162항목) 통과를 녹색으로 대신하고, main 푸시는 `[skip ci]`, 정식 배포는 노트북 빌드(kdict-docs `setup/DECISIONS.md`).
- **승인된 인터넷 사용**: kdict — 자료 꾸러미 받기(raw.githubusercontent.com/kiouvici/kdict-data), 국립국어원 로그인·사전 받기(stdict·krdict.korean.go.kr), 손글씨 한자 인식 모델 1회 받기(ML Kit, 와이파이). 말글사전 — 자료 꾸러미 받기(raw.githubusercontent.com/kiouvici/malgeul-data), 국립국어원 로그인·사전 받기(stdict·opendict.korean.go.kr).
- **감수팀**: 국어국문학 교수·초등학교 교사·사전 편찬 편집장·국립국어원 직원·학부모·아동 심리 전문가(kdict는 아이 보호 기준, 말글사전은 어른앱 기준으로 정확성·오류 중심).
- **프로젝트 금지**: 필순.dat 복호화 금지, 네이버 자동 수집 금지, 두 앱 공유 데이터는 hanja의 h·u·p·ps·od·pv만.