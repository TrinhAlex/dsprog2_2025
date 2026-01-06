import flet as ft
import requests
from datetime import datetime

AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{}.json"


def fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso[:10]


def fetch_json(url: str):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_forecast(code: str):
    return fetch_json(FORECAST_URL.format(code))


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
        if result[d]["min"] is None:
            result[d]["min"] = min(temps)
        if result[d]["max"] is None:
            result[d]["max"] = max(temps)

    # Finalize (convert None -> "-")
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


def weather_icon(weather_text: str):
    t = weather_text
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
    # Show "-" properly
    tmin = f'{item["min"]}℃' if item["min"] != "-" else "-℃"
    tmax = f'{item["max"]}℃' if item["max"] != "-" else "-℃"

    return ft.Card(
        content=ft.Container(
            width=200,
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
    page.title = "天気予報アプリ"
    page.window_width = 1200
    page.window_height = 750

    # ===== Header (like teacher) =====
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

    # ===== Right side =====
    status = ft.Text("", selectable=True)
    title = ft.Text("天気予報", size=30, weight=ft.FontWeight.BOLD)
    subtitle = ft.Text("選択した地域の天気予報", size=18, weight=ft.FontWeight.BOLD)
    cards = ft.Row(wrap=True, spacing=20, run_spacing=20)

    right_panel = ft.Column(
        [title, status, ft.Divider(), subtitle, cards],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    # ===== Left side (like teacher) =====
    sidebar_title = ft.Text("地域を選択", size=16, weight=ft.FontWeight.BOLD)
    selected_line = ft.Text("地域を選択してください。", size=14, weight=ft.FontWeight.BOLD)
    sidebar_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def set_status(msg: str):
        status.value = msg
        page.update()

    def render_forecast(code: str, name: str):
        selected_line.value = f"選択中：{name} ({code})"
        set_status("天気予報を取得中...")
        cards.controls.clear()
        page.update()

        data = fetch_forecast(code)
        daily = pick_daily_weather_and_temp(data)

        if not daily:
            cards.controls.append(ft.Text("予報データが取得できませんでした。"))
        else:
            for item in daily:
                cards.controls.append(make_card(item))

        set_status(f"天気予報取得OK：{len(daily)}日分")
        page.update()

    def build_sidebar():
        set_status("area.json を取得中...")
        area = fetch_json(AREA_URL)

        # centers: groups
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
                        on_click=lambda e, c=office_code, n=name: render_forecast(c, n),
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

    page.add(
        ft.Column(
            [
                header_bar,
                ft.Row(
                    [
                        ft.Container(
                            width=340,
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


