import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://github.com/google?tab=repositories"

def main():
    time.sleep(1)

    headers = {
        "User-Agent": "Mozilla/5.0 (exercise for scraping class)"
    }

    response = requests.get(BASE_URL, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    repo_items = soup.select("li.Box-row")
    print("Found", len(repo_items), "repos on this page")


    repos = []

    for item in repo_items:
        name_tag = item.find("a", itemprop="name codeRepository")
        name = name_tag.get_text(strip=True) if name_tag else None

        lang_tag = item.find("span", itemprop="programmingLanguage")
        language = lang_tag.get_text(strip=True) if lang_tag else "Unknown"

        star_tag = item.find("a", href=lambda x: x and x.endswith("/stargazers"))
        stars = star_tag.get_text(strip=True) if star_tag else "0"

        repos.append({
            "name": name,
            "language": language,
            "stars": stars
        })

    print("Collected repositories:\n")
    for r in repos:
        print(r)

if __name__ == "__main__":
    main()
