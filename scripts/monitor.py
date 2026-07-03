from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from urllib3.poolmanager import PoolManager


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
STATE_PATH = OUTPUT_DIR / "state.json"
REPORT_MD_PATH = OUTPUT_DIR / "report.md"
RESULTS_CSV_PATH = OUTPUT_DIR / "results.csv"
RAW_CSV_PATH = OUTPUT_DIR / "raw_results.csv"

DEFAULT_TZ = "Asia/Seoul"
NAVER_BASE = "https://news.naver.com"
NEWS1_BASE = "https://www.news1.kr"
NEWS1_API = "https://rest.news1.kr/v6/search/article"
YNA_API = "https://ars.yna.co.kr/api/v2/search.basic"
YNA_VIEW_BASE = "https://www.yna.co.kr/view/"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


class LegacyRenegotiationAdapter(HTTPAdapter):
    """Allow connecting to servers that still require legacy TLS renegotiation."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        legacy_option = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        context.options |= legacy_option
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=context,
            **pool_kwargs,
        )


YNA_SESSION = requests.Session()
YNA_SESSION.mount("https://ars.yna.co.kr", LegacyRenegotiationAdapter())


def get_with_retries(
    url: str,
    *,
    session: requests.Session | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: tuple[int, int] = (10, 30),
    attempts: int = 3,
    label: str = "request",
) -> requests.Response:
    client = session or requests
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts:
                sleep_seconds = 2 * attempt
                print(f"WARNING: {label} failed on attempt {attempt}/{attempts}: {exc}. Retrying in {sleep_seconds}s.")
                time.sleep(sleep_seconds)
            else:
                print(f"WARNING: {label} failed after {attempts} attempts: {exc}. Skipping.")
    if last_error:
        raise last_error
    raise RuntimeError(f"{label} failed without an exception.")


@dataclass(frozen=True)
class Media:
    name: str
    source_type: str
    source_id: str
    enabled: bool
    max_pages: int = 5


@dataclass(frozen=True)
class Keyword:
    keyword: str
    enabled: bool
    match_scope: str = "title_summary"


@dataclass(frozen=True)
class Schedule:
    name: str
    enabled: bool
    report_label: str
    timezone: str
    weekdays: set[str]
    run_time: dt_time
    tolerance_minutes: int
    lookback_start_days_ago: int
    lookback_start_time: dt_time
    lookback_end_days_ago: int
    lookback_end_time: dt_time
    telegram_enabled: bool


def truthy(value: str | None) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "Y", "YES", "1", "ON", "사용", "사용함"}


def parse_int(value: str | None, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def parse_time(value: str | None, default: str = "08:10") -> dt_time:
    text = str(value or default).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"Invalid time value: {value!r}")


def normalize_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_sheet_csv_url(sheet_id: str, sheet_name: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
        + urlencode({"tqx": "out:csv", "sheet": sheet_name})
    )


def fetch_csv_sheet(sheet_id: str, sheet_name: str) -> list[dict[str, str]]:
    url = make_sheet_csv_url(sheet_id, sheet_name)
    response = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8-sig"
    return list(csv.DictReader(response.text.splitlines()))


def load_config() -> tuple[list[Media], list[Keyword], list[Schedule]]:
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        raise SystemExit("GOOGLE_SHEET_ID is required.")

    media_rows = fetch_csv_sheet(sheet_id, "media")
    keyword_rows = fetch_csv_sheet(sheet_id, "keywords")
    schedule_rows = fetch_csv_sheet(sheet_id, "schedules")

    media = [
        Media(
            name=row.get("media_name", "").strip(),
            source_type=row.get("source_type", "").strip(),
            source_id=row.get("source_id", "").strip(),
            enabled=truthy(row.get("enabled")),
            max_pages=parse_int(row.get("max_pages"), 5),
        )
        for row in media_rows
        if row.get("media_name", "").strip()
    ]
    keywords = [
        Keyword(
            keyword=row.get("keyword", "").strip(),
            enabled=truthy(row.get("enabled")),
            match_scope=row.get("match_scope", "title_summary").strip() or "title_summary",
        )
        for row in keyword_rows
        if row.get("keyword", "").strip()
    ]
    schedules = []
    for row in schedule_rows:
        if not row.get("schedule_name", "").strip():
            continue
        weekdays = {
            item.strip().upper()
            for item in row.get("weekdays", "MON,TUE,WED,THU,FRI").split(",")
            if item.strip()
        }
        schedules.append(
            Schedule(
                name=row.get("schedule_name", "").strip(),
                enabled=truthy(row.get("enabled")),
                report_label=row.get("report_label", "조간").strip() or "조간",
                timezone=row.get("timezone", DEFAULT_TZ).strip() or DEFAULT_TZ,
                weekdays=weekdays,
                run_time=parse_time(row.get("run_time"), "08:10"),
                tolerance_minutes=parse_int(row.get("tolerance_minutes"), 10),
                lookback_start_days_ago=parse_int(row.get("lookback_start_days_ago"), 1),
                lookback_start_time=parse_time(row.get("lookback_start_time"), "08:00"),
                lookback_end_days_ago=parse_int(row.get("lookback_end_days_ago"), 0),
                lookback_end_time=parse_time(row.get("lookback_end_time"), "08:00"),
                telegram_enabled=truthy(row.get("telegram_enabled")),
            )
        )
    return media, keywords, schedules


def now_for_schedule(schedule: Schedule) -> datetime:
    override = os.environ.get("RUN_AT")
    tz = ZoneInfo(schedule.timezone)
    if override:
        parsed = datetime.fromisoformat(override)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    return datetime.now(tz)


def weekday_key(value: datetime) -> str:
    return ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][value.weekday()]


def due_schedules(schedules: list[Schedule], force: bool = False) -> list[tuple[Schedule, datetime]]:
    due = []
    for schedule in schedules:
        if not schedule.enabled:
            continue
        now = now_for_schedule(schedule)
        if force:
            due.append((schedule, now))
            continue
        if weekday_key(now) not in schedule.weekdays:
            continue
        target = datetime.combine(now.date(), schedule.run_time, tzinfo=now.tzinfo)
        diff = abs((now - target).total_seconds()) / 60
        if diff <= schedule.tolerance_minutes:
            due.append((schedule, now))
    return due


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def schedule_run_key(schedule: Schedule, now: datetime) -> str:
    return f"{schedule.name}:{now.date().isoformat()}:{schedule.run_time.strftime('%H:%M')}"


def compute_window(schedule: Schedule, now: datetime) -> tuple[datetime, datetime]:
    start_date = now.date() - timedelta(days=schedule.lookback_start_days_ago)
    end_date = now.date() - timedelta(days=schedule.lookback_end_days_ago)
    start = datetime.combine(start_date, schedule.lookback_start_time, tzinfo=now.tzinfo)
    end = datetime.combine(end_date, schedule.lookback_end_time, tzinfo=now.tzinfo)
    return start, end


def compute_source_window(schedule: Schedule, now: datetime, source_type: str) -> tuple[datetime, datetime]:
    start, end = compute_window(schedule, now)
    if source_type in {"news1_api", "yna_api"} and weekday_key(now) == "MON":
        start_date = now.date() - timedelta(days=3)
        start = datetime.combine(start_date, schedule.lookback_start_time, tzinfo=now.tzinfo)
    return start, end


def parse_korean_datetime(value: str, default_year: int) -> datetime | None:
    text = normalize_text(value)
    match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\.\s*(오전|오후)\s*(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    year, month, day, ampm, hour, minute = match.groups()
    h = int(hour)
    if ampm == "오후" and h != 12:
        h += 12
    if ampm == "오전" and h == 12:
        h = 0
    return datetime(int(year or default_year), int(month), int(day), h, int(minute), tzinfo=ZoneInfo(DEFAULT_TZ))


def fetch_naver_paper(media: Media, paper_date: datetime) -> list[dict]:
    articles: list[dict] = []
    ymd = paper_date.strftime("%Y%m%d")
    for page in range(1, max(media.max_pages, 1) + 1):
        params = {
            "mode": "LPOD",
            "mid": "sec",
            "oid": media.source_id,
            "listType": "paper",
            "date": ymd,
            "page": str(page),
        }
        url = f"{NAVER_BASE}/main/list.naver?{urlencode(params)}"
        try:
            response = get_with_retries(
                url,
                headers=HTTP_HEADERS,
                label=f"naver_paper:{media.name}:page{page}",
            )
        except requests.RequestException:
            break
        response.encoding = response.apparent_encoding or "euc-kr"
        soup = BeautifulSoup(response.text, "html.parser")

        page_articles = 0
        current_page_name = ""
        for node in soup.select("h4.paper_h4, ul.type13.firstlist > li"):
            if node.name == "h4":
                current_page_name = node.get_text(" ", strip=True)
                continue
            links = node.select('a[href*="/mnews/article/"]')
            if not links:
                continue
            link = links[-1]
            title = normalize_text(link.get_text(" ", strip=True))
            href = link.get("href", "").strip()
            if href.startswith("/"):
                href = NAVER_BASE + href
            date_node = node.select_one(".date")
            lede_node = node.select_one(".lede")
            info_node = node.select_one(".newspaper_info")
            published = parse_korean_datetime(date_node.get_text(" ", strip=True) if date_node else "", paper_date.year)
            articles.append(
                {
                    "source": media.name,
                    "source_type": media.source_type,
                    "title": title,
                    "summary": normalize_text(lede_node.get_text(" ", strip=True) if lede_node else ""),
                    "url": href,
                    "published_at": published.isoformat() if published else "",
                    "writer": "",
                    "paper_page": current_page_name or normalize_text(info_node.get_text(" ", strip=True) if info_node else ""),
                    "raw_keyword": "",
                }
            )
            page_articles += 1
        if page_articles == 0:
            break
        time.sleep(0.2)
    return articles


def fetch_news1(keyword: str, start_dt: datetime, end_dt: datetime, max_pages: int) -> list[dict]:
    articles: list[dict] = []
    for page in range(1, max(max_pages, 1) + 1):
        params = {
            "query": keyword,
            "collection": "article",
            "searchField": "ALL",
            "start": page,
            "limit": 25,
            "startDate": "",
            "endDate": "",
            "sort": "DATE",
            "cal_range": "A",
            "upper_category_ids": "",
            "exactquery": "",
            "andquery": "",
            "exceptquery": "",
            "author": "",
        }
        try:
            response = get_with_retries(
                NEWS1_API,
                params=params,
                headers=HTTP_HEADERS,
                label=f"news1:{keyword}:page{page}",
            )
            data = response.json().get("items", {}).get("data", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"WARNING: news1:{keyword}:page{page} skipped: {exc}")
            break
        if not data:
            break
        oldest_seen: datetime | None = None
        for item in data:
            published = datetime.strptime(item["pubdate"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=start_dt.tzinfo)
            oldest_seen = published if oldest_seen is None else min(oldest_seen, published)
            if start_dt <= published < end_dt:
                articles.append(
                    {
                        "source": "뉴스1",
                        "source_type": "news1_api",
                        "title": normalize_text(item.get("title")),
                        "summary": normalize_text(item.get("summary")),
                        "url": NEWS1_BASE + item.get("url", ""),
                        "published_at": published.isoformat(),
                        "writer": normalize_text(item.get("author")),
                        "paper_page": "",
                        "raw_keyword": keyword,
                    }
                )
        if oldest_seen and oldest_seen < start_dt:
            break
        time.sleep(0.2)
    return articles


def fetch_yna(keyword: str, start_dt: datetime, end_dt: datetime, max_pages: int) -> list[dict]:
    articles: list[dict] = []
    for page in range(1, max(max_pages, 1) + 1):
        params = {
            "query": keyword,
            "page_no": page,
            "page_size": 10,
            "scope": "all",
            "sort": "date",
            "channel": "basic_kr",
            "div_code": "all",
            "cattr": "",
        }
        try:
            response = get_with_retries(
                YNA_API,
                session=YNA_SESSION,
                params=params,
                headers=HTTP_HEADERS,
                label=f"yna:{keyword}:page{page}",
            )
            data = response.json().get("YIB_KR_A", {}).get("result", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"WARNING: yna:{keyword}:page{page} skipped: {exc}")
            break
        if not data:
            break
        oldest_seen: datetime | None = None
        for item in data:
            published = datetime.strptime(item["DATETIME"], "%Y%m%d%H%M%S").replace(tzinfo=start_dt.tzinfo)
            oldest_seen = published if oldest_seen is None else min(oldest_seen, published)
            if start_dt <= published < end_dt:
                title = item.get("EDIT_TITLE") or item.get("TITLE") or ""
                articles.append(
                    {
                        "source": "연합뉴스",
                        "source_type": "yna_api",
                        "title": normalize_text(title),
                        "summary": normalize_text(item.get("BODY")),
                        "url": YNA_VIEW_BASE + item.get("CID", ""),
                        "published_at": published.isoformat(),
                        "writer": normalize_text(item.get("WRITER_NAME")),
                        "paper_page": "",
                        "raw_keyword": keyword,
                    }
                )
        if oldest_seen and oldest_seen < start_dt:
            break
        time.sleep(0.2)
    return articles


def article_text(article: dict, scope: str) -> str:
    if scope == "title":
        return article.get("title", "")
    return " ".join([article.get("title", ""), article.get("summary", "")])


def match_keywords(article: dict, keywords: list[Keyword]) -> list[str]:
    matched = []
    for keyword in keywords:
        if not keyword.enabled:
            continue
        target = article_text(article, keyword.match_scope)
        if keyword.keyword and keyword.keyword.lower() in target.lower():
            matched.append(keyword.keyword)
    return matched


def collect_articles(media: list[Media], keywords: list[Keyword], schedule: Schedule, now: datetime) -> tuple[list[dict], list[dict]]:
    enabled_media = [m for m in media if m.enabled]
    enabled_keywords = [k for k in keywords if k.enabled]
    raw: list[dict] = []

    for item in enabled_media:
        start_dt, end_dt = compute_source_window(schedule, now, item.source_type)
        if item.source_type == "naver_paper":
            raw.extend(fetch_naver_paper(item, end_dt))
        elif item.source_type == "news1_api":
            for keyword in enabled_keywords:
                raw.extend(fetch_news1(keyword.keyword, start_dt, end_dt, item.max_pages))
        elif item.source_type == "yna_api":
            for keyword in enabled_keywords:
                raw.extend(fetch_yna(keyword.keyword, start_dt, end_dt, item.max_pages))

    dedup: dict[str, dict] = {}
    for article in raw:
        matched = match_keywords(article, enabled_keywords)
        if not matched:
            continue
        key_source = article.get("url") or article.get("title", "")
        key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()
        if key not in dedup:
            article["matched_keywords"] = ", ".join(sorted(set(matched)))
            dedup[key] = article
        else:
            existing = set(dedup[key].get("matched_keywords", "").split(", "))
            existing.update(matched)
            dedup[key]["matched_keywords"] = ", ".join(sorted(x for x in existing if x))

    results = sorted(
        dedup.values(),
        key=lambda x: (x.get("published_at") or "", x.get("source") or ""),
        reverse=True,
    )
    return raw, results


def format_report(results: list[dict], schedule: Schedule, now: datetime) -> str:
    start_dt, end_dt = compute_window(schedule, now)
    api_start_dt, _ = compute_source_window(schedule, now, "news1_api")
    lines = [
        f"<{schedule.report_label}>",
        f"조회기간: {start_dt.strftime('%Y-%m-%d %H:%M')}~{end_dt.strftime('%Y-%m-%d %H:%M')}",
    ]
    if api_start_dt != start_dt:
        lines.append(f"뉴스1·연합뉴스 조회기간: {api_start_dt.strftime('%Y-%m-%d %H:%M')}~{end_dt.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    if not results:
        lines.append("-조건에 맞는 기사가 없습니다.")
        return "\n".join(lines).strip() + "\n"

    for article in results:
        lines.extend(
            [
                f'-[{article["source"]}] "{article["title"]}"',
                "= ",
                f'"{article["url"]}"',
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def write_csv(path: Path, rows: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    columns = [
        "source",
        "source_type",
        "matched_keywords",
        "title",
        "summary",
        "url",
        "published_at",
        "writer",
        "paper_page",
        "raw_keyword",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in text.split("\n\n"):
        block_len = len(block) + 2
        if current and current_len + block_len > limit:
            chunks.append("\n\n".join(current))
            current = [block]
            current_len = block_len
        else:
            current.append(block)
            current_len += block_len
    if current:
        chunks.append("\n\n".join(current))
    total = len(chunks)
    if total > 1:
        return [f"{chunk}\n\n({i}/{total})" for i, chunk in enumerate(chunks, 1)]
    return chunks


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram secrets are not set. Skipping Telegram send.")
        return
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_message(text):
        response = requests.post(
            endpoint,
            data={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": "true",
            },
            timeout=30,
        )
        response.raise_for_status()
        time.sleep(0.4)


def run() -> int:
    force = truthy(os.environ.get("FORCE_RUN")) or "--force" in sys.argv
    dry_run = truthy(os.environ.get("DRY_RUN")) or "--dry-run" in sys.argv

    media, keywords, schedules = load_config()
    due = due_schedules(schedules, force=force)
    if not due:
        print("No schedules are due.")
        return 0

    state = load_state()
    combined_reports = []
    all_raw: list[dict] = []
    all_results: list[dict] = []

    for schedule, now in due:
        run_key = schedule_run_key(schedule, now)
        if not force and state.get("last_run_key") == run_key:
            print(f"Already sent: {run_key}")
            continue
        raw, results = collect_articles(media, keywords, schedule, now)
        report = format_report(results, schedule, now)
        combined_reports.append(report)
        all_raw.extend(raw)
        all_results.extend(results)
        if schedule.telegram_enabled and not dry_run:
            send_telegram(report)
        state["last_run_key"] = run_key
        state["last_run_at"] = datetime.now(ZoneInfo(DEFAULT_TZ)).isoformat()

    if not combined_reports:
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_MD_PATH.write_text("\n\n".join(combined_reports), encoding="utf-8")
    write_csv(RESULTS_CSV_PATH, all_results)
    write_csv(RAW_CSV_PATH, all_raw)
    save_state(state)
    print(f"Wrote {REPORT_MD_PATH}")
    print(f"Wrote {RESULTS_CSV_PATH}")
    print(f"Wrote {RAW_CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
