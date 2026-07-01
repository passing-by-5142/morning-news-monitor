import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputPath = fileURLToPath(new URL("../config/news_monitor_settings_template.xlsx", import.meta.url));

const workbook = Workbook.create();

function writeSheet(name, rows) {
  const sheet = workbook.worksheets.add(name);
  const rowCount = rows.length;
  const colCount = Math.max(...rows.map((row) => row.length));
  const normalized = rows.map((row) => [...row, ...Array(colCount - row.length).fill("")]);
  sheet.getRangeByIndexes(0, 0, rowCount, colCount).values = normalized;
  return sheet;
}

writeSheet("guide", [
  ["Morning News Monitor 설정 시트"],
  [""],
  ["1", "media 탭에서 수집할 매체만 enabled=TRUE로 둡니다."],
  ["2", "keywords 탭에서 원하는 키워드를 추가·삭제합니다."],
  ["3", "schedules 탭에서 발송 시각과 조회기간을 수정합니다."],
  ["4", "이 파일을 Google Sheets로 열고, 링크가 있는 모든 사용자에게 보기 권한을 부여합니다."],
  ["5", "GitHub Secrets에 GOOGLE_SHEET_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 저장합니다."],
]);

writeSheet("media", [
  ["enabled", "media_name", "source_type", "source_id", "max_pages", "memo"],
  [true, "경향신문", "naver_paper", "032", 5, "종합지"],
  [true, "국민일보", "naver_paper", "005", 5, "종합지"],
  [true, "동아일보", "naver_paper", "020", 5, "종합지"],
  [true, "문화일보", "naver_paper", "021", 5, "종합지"],
  [true, "서울신문", "naver_paper", "081", 5, "종합지"],
  [true, "세계일보", "naver_paper", "022", 5, "종합지"],
  [true, "조선일보", "naver_paper", "023", 5, "종합지"],
  [true, "중앙일보", "naver_paper", "025", 5, "종합지"],
  [true, "한겨레", "naver_paper", "028", 5, "종합지"],
  [true, "한국일보", "naver_paper", "469", 5, "종합지"],
  [true, "매일경제", "naver_paper", "009", 5, "경제지"],
  [true, "머니투데이", "naver_paper", "008", 5, "경제지"],
  [true, "서울경제", "naver_paper", "011", 5, "경제지"],
  [true, "아시아경제", "naver_paper", "277", 5, "경제지"],
  [true, "이데일리", "naver_paper", "018", 5, "경제지"],
  [true, "파이낸셜뉴스", "naver_paper", "014", 5, "경제지"],
  [true, "한국경제", "naver_paper", "015", 5, "경제지"],
  [true, "헤럴드경제", "naver_paper", "016", 5, "경제지"],
  [true, "뉴스1", "news1_api", "news1", 8, "검색 API"],
  [true, "연합뉴스", "yna_api", "yna", 8, "검색 API 일반뉴스만"],
]);

writeSheet("keywords", [
  ["enabled", "keyword", "match_scope", "memo"],
  [true, "공정위", "title_summary", "예시"],
  [true, "산업부", "title_summary", "예시"],
  [true, "관세", "title_summary", "예시"],
  [false, "전력망", "title_summary", "필요시 TRUE"],
]);

writeSheet("schedules", [
  [
    "enabled",
    "schedule_name",
    "report_label",
    "timezone",
    "weekdays",
    "run_time",
    "tolerance_minutes",
    "lookback_start_days_ago",
    "lookback_start_time",
    "lookback_end_days_ago",
    "lookback_end_time",
    "telegram_enabled",
  ],
  [true, "weekday_morning", "조간", "Asia/Seoul", "MON,TUE,WED,THU,FRI", "08:10", 10, 1, "08:00", 0, "08:00", true],
]);

writeSheet("sample_report", [
  ["output_example"],
  ["<조간>"],
  ["-[경향신문] \"기사 제목\""],
  ["= "],
  ["\"https://n.news.naver.com/mnews/article/032/0000000000\""],
]);

await fs.mkdir(new URL("../config/", import.meta.url), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`Saved ${outputPath}`);
