import flet as ft
import requests
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

# =====================
# API
# =====================
AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{}.json"

# =====================
# DB
# =====================
DB_PATH = Path(__file__).with_name("weather.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # FK dùng được nếu bạn muốn mở rộng, hiện tại vẫn OK
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS areas (
            office_code TEXT PRIMARY KEY,
            office_name TEXT NOT NULL,
            center_code TEXT,
            center_name TEXT,
            updated_at TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS forecasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            office_code TEXT NOT NULL,
            forecast_date TEXT NOT NULL,
            report_datetime TEXT NOT NULL,
            weather TEXT,
            temp_min INTEGER,
            temp_max INTEGER,
            UNIQUE(office_code, forecast_date, report_datetime)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fc_office_report ON forecasts(office_code, report_datetime)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fc_office_date ON forecasts(office_code, forecast_date)")


# =====================
# Helpers
# =====================
def fetch_json(url: str):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso[:10]


def parse_iso_dt(s: str):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def extract_report_datetime(forecast_json):
    try:
        root = forecast_json[0]
        return root.get("reportDatetime") or datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


# =====================
# Parse JMA JSON (có fallback hourly)
# =====================
def pick_daily_weather_and_temp(forecast_json):
    """
    Output: [{"date": "...", "weather": "...", "min": int|"-", "max": int|"-"}, ...]
    - Weather: timeSeries[0]
    - Daily min/max: timeSeries[2] (may be missing)
    - Fallback temps: timeSeries[1] hourly temps -> compute daily min/max
    """
    if not isinstance(forecast_json, list) or len(forecast_json) == 0:
        return []

    root = forecast_json[0]
    ts = root.get("timeSeries", [])

    # 1) Weather
    w_times, weathers = [], []
    try:
        w_times = ts[0]["timeDefines"]
        weathers = ts[0]["areas"][0]["weathers"]
    except Exception:
        pass

    # 2) Daily min/max (may be missing)
    t_daily_times, mins, maxs = [], [], []
    try:
        t_daily_times = ts[2]["timeDefines"]
        mins = ts[2]["areas"][0]["tempsMin"]
        maxs = ts[2]["areas"][0]["tempsMax"]
    except Exception:
        pass

    # 3) Hourly temps (fallback)
    t_hourly_times, temps_hourly = [], []
    try:
        t_hourly_times = ts[1]["timeDefines"]
        temps_hourly = ts[1]["areas"][0]["temps"]
    except Exception:
        pass

    result = {}

    # Fill weather
    for i in range(min(len(w_times), len(weathers))):
        d = fmt_date(w_times[i])
        result.setdefault(d, {"date": d, "weather": "-", "min": None, "max": None})
        result[d]["weather"] = weathers[i]

    # Fill daily min/max if available
    for i in range(len(t_daily_times)):
        d = fmt_date(t_daily_times[i])
        result.setdefault(d, {"date": d, "weather": "-", "min": None, "max": None})
        if i < len(mins) and mins[i]:
            try:
                result[d]["min"] = int(mins[i])
            except Exception:
                pass
        if i < len(maxs) and maxs[i]:
            try:
                result[d]["max"] = int(maxs[i])
            except Exception:
                pass

    # Fallback from hourly temps: group by day, compute min/max
    daily_bucket = {}
    for i in range(min(len(t_hourly_times), len(temps_hourly))):
        d = fmt_date(t_hourly_times[i])
        try:
            temp = int(temps_hourly[i])
        except Exception:
            continue
        daily_bucket.setdefault(d, []).append(temp)

    for d, temps in daily_bucket.items():
        result.setdefault(d, {"date": d, "weather": "-", "min": None, "max": None})
        if result[d]["min"] is None and temps:
            result[d]["min"] = min(temps)
        if result[d]["max"] is None and temps:
            result[d]["max"] = max(temps)

    # Finalize
    out = []
    for k in sorted(result.keys()):
        item = result[k]
        out.append(
            {
                "date": item["date"],
                "weather": item["weather"],
                "min": "-" if item["min"] is None else item["min"],
                "max": "-" if item["max"] is None else item["max"],
            }
        )

    return out[:6]


# =====================
# DB ops
# =====================
def upsert_area(office_code: str, office_name: str, center_code: str | None, center_name: str | None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO areas(office_code, office_name, center_code, center_name, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(office_code) DO UPDATE SET
              office_name=excluded.office_name,
              center_code=excluded.center_code,
              center_name=excluded.center_name,
              updated_at=excluded.updated_at
            """,
            (office_code, office_name, center_code, center_name, datetime.now().isoformat()),
        )


def save_forecasts(code: str, report_dt: str, daily: list[dict]):
    # chống trùng: UNIQUE + INSERT OR IGNORE
    with get_conn() as conn:
        for d in daily:
            tmin = None if d["min"] == "-" else int(d["min"])
            tmax = None if d["max"] == "-" else int(d["max"])
            conn.execute(
                """
                INSERT OR IGNORE INTO forecasts
                (office_code, forecast_date, report_datetime, weather, temp_min, temp_max)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (code, d["date"], report_dt, d["weather"], tmin, tmax),
            )


def get_report_history(code: str, limit: int = 20):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT report_datetime
            FROM forecasts
            WHERE office_code = ?
            ORDER BY report_datetime DESC
            LIMIT ?
            """,
            (code, limit),
        ).fetchall()
        return [r["report_datetime"] for r in rows]


def load_forecasts(code: str, report_dt: str, limit_days: int = 6):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT forecast_date, weather, temp_min, temp_max
            FROM forecasts
            WHERE office_code = ? AND report_datetime = ?
            ORDER BY forecast_date ASC
            LIMIT ?
            """,
            (code, report_dt, limit_days),
        ).fetchall()

        out = []
        for r in rows:
            out.append(
                {
                    "date": r["forecast_date"],
                    "weather": r["weather"] or "-",
                    "min": "-" if r["temp_min"] is None else r["temp_min"],
                    "max": "-" if r["temp_max"] is None else r["temp_max"],
                }
            )
        return out


def latest_report_dt(code: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(report_datetime) AS mx FROM forecasts WHERE office_code = ?",
            (code,),
        ).fetchone()
        return row["mx"] if row and row["mx"] else None


def is_fresh(report_dt: str, minutes: int = 10) -> bool:
    dt = parse_iso_dt(report_dt)
    if not dt:
        return False
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    return (now - dt) <= timedelta(minutes=minutes)


# =====================
# UI
# =====================
def weather_icon(weather_text: str):
    t = weather_text or ""
    if "雪" in t:
        return ft.Icons.AC_UNIT
    if "雷" in t:
        return ft.Icons.FLASH_ON
    if "雨" in t:
        return ft.Icons.UMBRELLA
    if "曇" in t or "くも" in t:
        return ft.Icons.CLOUD
    if "晴" in t:
        return ft.Icons.WB_SUNNY
    return ft.Icons.WB_CLOUDY


def make_card(item: dict):
    # đẹp hơn: "-" => "—"
    tmin = f'{item["min"]}℃' if item["min"] != "-" else "—"
    tmax = f'{item["max"]}℃' if item["max"] != "-" else "—"

    return ft.Card(
        content=ft.Container(
            width=220,
            padding=16,
            border_radius=14,
            content=ft.Column(
                [
                    ft.Text(item["date"], size=16, weight=ft.FontWeight.BOLD),
                    ft.Icon(weather_icon(item["weather"]), size=44, color=ft.Colors.INDIGO_700),
                    ft.Text(item["weather"], max_lines=3, text_align=ft.TextAlign.CENTER),
                    ft.Row(
                        [
                            ft.Text(tmin, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_700),
                            ft.Text(" / "),
                            ft.Text(tmax, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
        )
    )


def main(page: ft.Page):
    init_db()

    page.title = "天気予報アプリ（SQLite版・履歴）"
    page.window_width = 1250
    page.window_height = 760

    # ===== Header =====
    header_bar = ft.Container(
        bgcolor=ft.Colors.INDIGO_800,
        padding=ft.padding.symmetric(horizontal=22, vertical=14),
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.WB_SUNNY, color=ft.Colors.WHITE),
                        ft.Text("天気予報", size=22, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=12,
                )
            ],
            alignment=ft.MainAxisAlignment.START,
        ),
    )

    # ===== State =====
    current_office_code = {"v": None}
    current_office_name = {"v": None}
    current_center_code = {"v": None}
    current_center_name = {"v": None}

    # ===== Right panel widgets =====
    status = ft.Text("", selectable=True)
    last_updated = ft.Text("最終更新：—", size=13, color=ft.Colors.GREY_800)
    cards = ft.Row(wrap=True, spacing=20, run_spacing=20)

    loading = ft.ProgressRing(visible=False)
    refresh_btn = ft.ElevatedButton("更新", icon=ft.Icons.REFRESH)

    history_dd = ft.Dropdown(
        label="過去の予報（更新履歴）",
        options=[],
        width=420,
        dense=True,
    )

    def set_loading(on: bool):
        loading.visible = on
        refresh_btn.disabled = on
        history_dd.disabled = on
        page.update()

    def set_status(msg: str):
        status.value = msg
        page.update()

    def render_from_db(code: str, report_dt: str):
        cards.controls.clear()
        data = load_forecasts(code, report_dt)
        if not data:
            cards.controls.append(ft.Text("DBに予報データがありません。"))
        else:
            for item in data:
                cards.controls.append(make_card(item))
        last_updated.value = f"最終更新：{report_dt}"
        page.update()

    def rebuild_history_dropdown(code: str, select_report_dt: str | None = None):
        hist = get_report_history(code, limit=30)
        history_dd.options = [ft.dropdown.Option(h) for h in hist]
        if select_report_dt and select_report_dt in hist:
            history_dd.value = select_report_dt
        elif hist:
            history_dd.value = hist[0]
        else:
            history_dd.value = None

    def on_history_change(e):
        code = current_office_code["v"]
        if not code or not history_dd.value:
            return
        set_status(f"履歴から表示：{history_dd.value}")
        render_from_db(code, history_dd.value)

    history_dd.on_change = on_history_change

    def fetch_save_and_show(force: bool = False):
        code = current_office_code["v"]
        name = current_office_name["v"]
        if not code or not name:
            return

        # Cache: nếu DB có bản mới trong 10 phút và không force => chỉ đọc DB
        latest = latest_report_dt(code)
        if (not force) and latest and is_fresh(latest, minutes=10):
            set_status("DBの最新データ（キャッシュ）を表示")
            rebuild_history_dropdown(code, select_report_dt=latest)
            render_from_db(code, history_dd.value)
            return

        set_loading(True)
        set_status("API取得中 → DB保存中...")
        try:
            data = fetch_json(FORECAST_URL.format(code))
            report_dt = extract_report_datetime(data)
            daily = pick_daily_weather_and_temp(data)

            if daily:
                # option: lưu area vào DB
                upsert_area(
                    office_code=code,
                    office_name=name,
                    center_code=current_center_code["v"],
                    center_name=current_center_name["v"],
                )
                save_forecasts(code, report_dt, daily)

            # rebuild history + show newest
            rebuild_history_dropdown(code, select_report_dt=report_dt)
            if history_dd.value:
                render_from_db(code, history_dd.value)
            set_status(f"DBから表示OK：{len(daily) if daily else 0}日分（最新reportDatetime）")

        except Exception as ex:
            # Offline mode: nếu API lỗi thì show DB latest
            set_status(f"API失敗 → DBの最新データを表示します：{ex}")
            latest = latest_report_dt(code)
            rebuild_history_dropdown(code, select_report_dt=latest)
            if history_dd.value:
                render_from_db(code, history_dd.value)
        finally:
            set_loading(False)

    def on_refresh_click(e):
        fetch_save_and_show(force=True)

    refresh_btn.on_click = on_refresh_click

    title = ft.Text("天気予報", size=30, weight=ft.FontWeight.BOLD)
    subtitle = ft.Text("選択した地域の天気予報（DBから表示）", size=18, weight=ft.FontWeight.BOLD)

    top_controls = ft.Row(
        [
            refresh_btn,
            history_dd,
            loading,
        ],
        spacing=12,
        alignment=ft.MainAxisAlignment.START,
    )

    right_panel = ft.Column(
        [title, status, last_updated, ft.Divider(), subtitle, top_controls, ft.Divider(), cards],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    # ===== Left sidebar =====
    sidebar_title = ft.Text("地域を選択", size=16, weight=ft.FontWeight.BOLD)
    selected_line = ft.Text("地域を選択してください。", size=14, weight=ft.FontWeight.BOLD)
    sidebar_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def render_forecast(code: str, name: str, center_code: str, center_name: str):
        current_office_code["v"] = code
        current_office_name["v"] = name
        current_center_code["v"] = center_code
        current_center_name["v"] = center_name

        selected_line.value = f"選択中：{name} ({code})"
        page.update()

        fetch_save_and_show(force=False)

    def build_sidebar():
        set_status("area.json を取得中...")
        area = fetch_json(AREA_URL)

        centers = area.get("centers", {})
        offices = area.get("offices", {})

        sidebar_list.controls.clear()

        for center_code, center_info in sorted(centers.items(), key=lambda x: x[0]):
            center_name = center_info.get("name", str(center_code))
            children = center_info.get("children", [])

            tiles = []
            for office_code in children:
                info = offices.get(office_code, {})
                name = info.get("name", str(office_code))

                tiles.append(
                    ft.ListTile(
                        title=ft.Text(name),
                        subtitle=ft.Text(office_code),
                        leading=ft.Icon(ft.Icons.LOCATION_ON_OUTLINED),
                        on_click=lambda e, c=office_code, n=name, cc=center_code, cn=center_name: render_forecast(c, n, cc, cn),
                    )
                )

            sidebar_list.controls.append(
                ft.ExpansionTile(
                    title=ft.Text(center_name),
                    subtitle=ft.Text(center_code),
                    leading=ft.Icon(ft.Icons.MAP_OUTLINED),
                    controls=tiles,
                )
            )

        set_status("地域リスト取得OK")
        page.update()

    # Layout
    page.add(
        ft.Column(
            [
                header_bar,
                ft.Row(
                    [
                        ft.Container(
                            width=360,
                            bgcolor=ft.Colors.BLUE_GREY_100,
                            padding=14,
                            content=ft.Column(
                                [
                                    sidebar_title,
                                    ft.Divider(height=1),
                                    selected_line,
                                    ft.Divider(height=1),
                                    sidebar_list,
                                ],
                                expand=True,
                            ),
                        ),
                        ft.VerticalDivider(width=1),
                        ft.Container(right_panel, expand=True, padding=22),
                    ],
                    expand=True,
                ),
            ],
            expand=True,
        )
    )

    build_sidebar()


ft.app(target=main)

