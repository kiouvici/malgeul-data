# malgeul-data — 말글사전 자료 묶음

말글사전 앱이 **앱을 다시 만들지 않고** 받아 쓰는 자료입니다. 이 저장소는 공개(public)여야 합니다.
앱은 `https://raw.githubusercontent.com/kiouvici/malgeul-data/main/manifest.json`을 하루 한 번 확인하고,
판이 바뀐 묶음만 받아 sha256·크기·형식을 검사한 뒤 적용합니다. 실패하면 지금 쓰는 자료를 그대로 씁니다.

## 폴더

| 위치 | 내용 |
|---|---|
| `src/` | 원본(사람이 고치는 곳). 묶음 하나 = 파일 하나: `<id>.json`, `<id>.jsonl`, `<id>.sqlite` |
| `src/packs.json` | 묶음 설명과 필요한 앱 판(`min_app`) |
| `packs/` | 앱이 받는 압축 파일(직접 고치지 않음) |
| `manifest.json` | 묶음 목록(직접 고치지 않음) |
| `tools/publish_data.py` | `src/` → `packs/` + `manifest.json` 만들기 |

## 지금 묶음

| id | 내용 | 앱에서 쓰는 곳 |
|---|---|---|
| `dadm` | 다듬은 말(행정용어 순화어) | 바른 말 › 다듬은 말, 검색 꼬리표 |
| `heot` | 헷갈리는 말 | 바른 말 › 헷갈리는 말, 오늘의 바른 말 |
| `hanja` | 한자 훈음·급수·부수·획수·필순 | 한자 상세·찾기 |
| `rad` | 부수 모양 목록, 부수 밖 획수 | 부수로 찾기 |
| `features` | 기능 설정(켜고 끄기) | 앱 화면 `feature('이름', 기본값)` |

## 자료 고치기·새 판 올리기

1. `src/` 안의 파일을 고칩니다(형식은 지금 파일과 같게).
2. 묶음을 다시 만듭니다.
   ```
   python3 tools/publish_data.py src .
   ```
   내용이 바뀐 묶음만 판이 `YYYY.MM.DD-N`으로 올라가고, 같은 내용은 판이 그대로입니다.
   JSON이 깨졌거나 비어 있으면 여기서 멈추므로 잘못된 자료가 올라가지 않습니다.
3. 커밋하고 올립니다.
   ```
   git add -A && git commit -m "자료: 다듬은 말 30개 추가" && git push
   ```
4. 앱: 하루 안에 저절로 받습니다. 바로 받으려면 **더보기 › 자료 업데이트 확인 › 지금 업데이트**.
   (raw.githubusercontent.com은 몇 분 동안 옛 파일을 보여 줄 수 있습니다.)

## 새 묶음 더하기(새 기능용)

1. `src/<새 id>.json`(또는 `.jsonl`, `.sqlite`)을 넣고 `src/packs.json`에 설명을 적습니다.
   그 자료를 쓰는 앱 기능이 나중 판에 들어간다면 `min_app`에 그 앱의 versionCode(빌드 번호)를 적습니다.
   더 옛 앱은 이 묶음을 받지 않고 "앱 업데이트 필요"로 보여 줍니다.
2. 위 2~3번처럼 만들고 올립니다.
3. 앱 코드에서는 `DataPacks.open("<id>")` / `DataPacks.path("<id>")` / `DataPacks.version("<id>")`로 읽습니다.
   앱이 모르는 묶음도 미리 받아 두므로, 자료를 먼저 올리고 기능은 나중에 넣어도 됩니다.

## 기능 켜고 끄기

`src/features.json`의 `flags`를 고쳐 올립니다. 예: `{"schema": 1, "flags": {"today_card": false}}`
앱 화면에서는 `feature('today_card', true)`처럼 읽습니다(없으면 기본값).

## 큰 파일(50MB 넘음)

GitHub 저장소에는 큰 파일을 올리기 어려우니 Release 첨부로 올립니다.
```
python3 tools/publish_data.py src . --release-base https://github.com/kiouvici/malgeul-data/releases/download/data-1
```
50MB 넘는 묶음은 `release/` 폴더에 만들어지고 manifest에는 그 주소가 적힙니다.
`data-1` 태그로 Release를 만들어 `release/` 안 파일을 첨부한 뒤, manifest를 push 합니다(`release/`는 커밋하지 않음).
데이터 요금이 드는 망에서는 앱이 20MB 넘는 묶음을 저절로 받지 않습니다.

## 되돌리기

앱은 바로 앞 판을 하나 남겨 두고, 받은 자료를 읽다 실패하면 앞 판(없으면 앱 기본 자료)으로 돌아갑니다.
잘못 올렸다면 `src/`를 고쳐 다시 올리면 됩니다(`git revert` 후 다시 만들기도 됨).
