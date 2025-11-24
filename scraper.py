import time
import requests
from bs4 import BeautifulSoup
import sqlite3

# GoogleのGithubリポジトリ一覧ページ
BASE_URL = "https://github.com/google?tab=repositories"

# スター数をint型に変換する関数
def normalize_stars(stars_str: str) -> int:
    s = stars_str.strip().replace(",", "")
    if not s:
        return 0
    if s.lower().endswith("k"):   # 例: 2.3k → 2300
        num = float(s[:-1])
        return int(num * 1000)
    return int(s) if s.isdigit() else 0


# SQLiteのDB作成
def init_db():
    conn = sqlite3.connect("repos.db")
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            language TEXT,
            stars INTEGER
        )
        """
    )
    # 毎回削除して重複を防ぐ
    cur.execute("DELETE FROM repositories")
    conn.commit()
    return conn


# DBにデータを保存
def save_repos_to_db(conn, repos):
    cur = conn.cursor()
    for r in repos:
        cur.execute(
            "INSERT INTO repositories (name, language, stars) VALUES (?, ?, ?)",
            (r["name"], r["language"], r["stars"])
        )
    conn.commit()


# DBのデータ表示
def show_data(conn):
    cur = conn.cursor()
    rows = cur.execute("SELECT id, name, language, stars FROM repositories").fetchall()
    for row in rows:
        print(row)


def main():
    time.sleep(1)   # 課題条件：1秒待つ

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # ページをGET
    response = requests.get(BASE_URL, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # リポジトリ項目の取得
    repo_items = soup.select("li.Box-row")
    print(f"Found {len(repo_items)} repos on this page")

    repos = []

    # 各リポジトリの情報を抽出
    for item in repo_items:
        # リポジトリ名
        name_tag = item.find("a", itemprop="name codeRepository")
        if not name_tag:
            h3 = item.find("h3")
            if h3 and h3.find("a"):
                name_tag = h3.find("a")
        name = name_tag.get_text(strip=True) if name_tag else None

        # 主要言語
        lang_tag = item.find("span", itemprop="programmingLanguage")
        language = lang_tag.get_text(strip=True) if lang_tag else "Unknown"

        # スター数
        star_tag = item.find("a", href=lambda x: x and x.endswith("/stargazers"))
        stars_text = star_tag.get_text(strip=True) if star_tag else "0"
        stars = normalize_stars(stars_text)

        repos.append({"name": name, "language": language, "stars": stars})

    # 取得データ確認
    print("Collected repositories:\n")
    for r in repos:
        print(r)

    # DBに保存して確認
    conn = init_db()
    save_repos_to_db(conn, repos)

    print("\nData stored in database:")
    show_data(conn)

    conn.close()


if __name__ == "__main__":
    main()

