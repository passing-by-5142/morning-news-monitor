# Morning News Monitor Template

주요 신문 지면기사, 뉴스1, 연합뉴스 검색 결과를 사용자가 정한 키워드·매체·스케줄에 맞춰 수집하고 텔레그램으로 보내는 템플릿입니다.

## 구조

- `config/news_monitor_settings_template.xlsx`: 사용자가 복사해 구글시트로 쓰는 설정 템플릿
- `scripts/monitor.py`: 기사 수집, 키워드 필터링, 보고서 생성, 텔레그램 발송
- `.github/workflows/morning_news_monitor.yml`: GitHub Actions 예약 실행
- `outputs/report.md`: 텔레그램으로 보낸 보고서 원문
- `outputs/results.csv`: 키워드 매칭 결과
- `outputs/raw_results.csv`: 수집 원자료

## 수집 대상

- 네이버 뉴스 언론사별 `신문게재기사만` 지면기사
- 뉴스1 검색 API
- 연합뉴스 검색 API 중 일반 뉴스 기사 컬렉션 `YIB_KR_A`

## 1. 설정 시트 만들기

1. `config/news_monitor_settings_template.xlsx`를 구글 드라이브에 업로드합니다.
2. Google Sheets로 엽니다.
3. `media`, `keywords`, `schedules` 탭에서 값을 수정합니다.
4. 시트 공유를 `링크가 있는 모든 사용자: 뷰어`로 설정합니다.
5. 구글시트 URL에서 문서 ID를 복사합니다.

예시:

```text
https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit
```

여기서 `1AbCdEfGhIjKlMnOpQrStUvWxYz`가 `GOOGLE_SHEET_ID`입니다.

## 2. 텔레그램 봇 만들기

1. 텔레그램에서 `@BotFather`를 엽니다.
2. `/newbot`으로 봇을 만들고 토큰을 받습니다.
3. 만든 봇에게 아무 메시지나 보냅니다.
4. 아래 URL을 브라우저에서 열어 `chat.id`를 확인합니다.

```text
https://api.telegram.org/bot<봇토큰>/getUpdates
```

## 3. GitHub Secrets 설정

GitHub 저장소의 `Settings > Secrets and variables > Actions > New repository secret`에서 아래 값을 넣습니다.

| Secret | 설명 |
|---|---|
| `GOOGLE_SHEET_ID` | 설정 구글시트 문서 ID |
| `TELEGRAM_BOT_TOKEN` | BotFather가 발급한 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 수신 채팅방 ID |

## 4. 시트 탭 설명

### `media`

| 컬럼 | 설명 |
|---|---|
| `enabled` | `TRUE`면 사용 |
| `media_name` | 보고서에 표시될 매체명 |
| `source_type` | `naver_paper`, `news1_api`, `yna_api` |
| `source_id` | 네이버 `oid` 또는 API 식별자 |
| `max_pages` | 최대 조회 페이지 수 |

### `keywords`

| 컬럼 | 설명 |
|---|---|
| `enabled` | `TRUE`면 사용 |
| `keyword` | 검색·매칭 키워드 |
| `match_scope` | `title` 또는 `title_summary` |

### `schedules`

| 컬럼 | 설명 |
|---|---|
| `enabled` | `TRUE`면 사용 |
| `schedule_name` | 스케줄 식별명 |
| `report_label` | 보고서 제목. 예: `조간` |
| `timezone` | 기본 `Asia/Seoul` |
| `weekdays` | 예: `MON,TUE,WED,THU,FRI` |
| `run_time` | 실행 기준 시각. 예: `08:10` |
| `tolerance_minutes` | GitHub Actions 실행 오차 허용분 |
| `lookback_start_days_ago` | 조회 시작일. 전날이면 `1` |
| `lookback_start_time` | 조회 시작시각 |
| `lookback_end_days_ago` | 조회 종료일. 오늘이면 `0` |
| `lookback_end_time` | 조회 종료시각 |
| `telegram_enabled` | `TRUE`면 텔레그램 발송 |

월요일 실행 때는 뉴스1·연합뉴스만 자동으로 조회 시작일을 3일 전으로 넓힙니다. 예를 들어 기본 설정이 전날 08:00~당일 08:00이면, 월요일 뉴스1·연합뉴스는 금요일 08:00~월요일 08:00까지 검색해 주말 사이 나온 기사를 함께 커버합니다. 네이버 신문게재기사는 기존처럼 해당 날짜 지면 기준으로 수집합니다.

## 보고서 형식

```text
<조간>
조회기간: 2026-06-30 08:00~2026-07-01 08:00

-[경향신문] "기사 제목"
= 
"https://n.news.naver.com/mnews/article/032/0000000000"
```

`=` 아래는 일부러 비워둡니다. 사용자가 보고할 주요 내용을 직접 적는 공간입니다. 자동 추출 요약은 `outputs/results.csv`의 `summary` 컬럼에 저장됩니다.

## 로컬 테스트

```bash
pip install -r requirements.txt
GOOGLE_SHEET_ID="구글시트ID" DRY_RUN=true FORCE_RUN=true python scripts/monitor.py
```

텔레그램까지 테스트하려면:

```bash
GOOGLE_SHEET_ID="구글시트ID" \
TELEGRAM_BOT_TOKEN="봇토큰" \
TELEGRAM_CHAT_ID="채팅ID" \
FORCE_RUN=true \
python scripts/monitor.py
```

## 배포 방법

동료에게 배포할 때는 이 저장소를 템플릿으로 복사하게 한 뒤, 각자 설정 시트와 텔레그램 봇 토큰을 GitHub Secrets에 넣게 하면 됩니다.
