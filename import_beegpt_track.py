"""Трек «Интеграция с beeGPT» из Confluence → public/data/data.json (ключ beegptTrack) для вкладки 08 «Статуса».

Источник — хаб 2693937956 (ведёт Немудров, с 17.11.2026) и его подстраницы. Выгрузка — Blob-download
с bwiki (body.view) в cf/cf_all_ДДММ.json, ключ beegpt = {hub: {id,title,version,when,by,html}, children: [...]}.
С хаба берём разделы из SECTIONS (по началу заголовка h2), с подстраниц — раздел «0. Кратко».

    python import_beegpt_track.py cf/cf_all_ДДММ.json [public/data/data.json]
"""
import html
import json
import re
import sys
from html.parser import HTMLParser

BASE = "https://bwiki.beeline.ru"
# какие разделы хаба показывать руководству (Виктор 18.11.2026) — по началу заголовка без номера
SECTIONS = ("Кратко", "Статус", "Блокеры", "Позиция", "Задачи трека", "Что переиспользуем", "Открытые вопросы")
ALLOWED = {"p", "ul", "ol", "li", "b", "strong", "em", "i", "br", "table", "thead", "tbody", "tr", "td", "th", "a", "h3", "h4", "code"}


class Clean(HTMLParser):
    """Оставляет простую разметку: абзацы, списки, таблицы, ссылки (абсолютные)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style") or "confluence-information-macro-icon" in (a.get("class") or ""):
            self.skip += 1
            return
        if tag not in ALLOWED:
            return
        if tag == "a":
            href = a.get("href") or ""
            if href.startswith("/"):
                href = BASE + href
            self.out.append(f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener">' if href.startswith("http") else "<a>")
        elif tag == "table":
            self.out.append('<table class="tbl">')
        elif tag in ("td", "th") and a.get("colspan"):
            self.out.append(f'<{tag} colspan="{int(a["colspan"])}">')
        else:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in ALLOWED and tag != "br":
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def clean(fragment):
    c = Clean()
    c.feed(fragment)
    s = "".join(c.out)
    s = re.sub(r"<(p|li|td|th)>\s*</\1>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def sections(page_html):
    """[(заголовок h1/h2, html до следующего)]"""
    parts = re.split(r"(<h[12][^>]*>.*?</h[12]>)", page_html, flags=re.S)
    out = []
    for i in range(1, len(parts), 2):
        title = html.unescape(re.sub(r"<[^>]+>", "", parts[i])).strip()
        out.append((title, parts[i + 1] if i + 1 < len(parts) else ""))
    return out


def plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def page_url(pid):
    return f"{BASE}/pages/viewpage.action?pageId={pid}"


def main(src, data_path="public/data/data.json"):
    b = json.load(open(src, encoding="utf-8"))["beegpt"]
    hub = b["hub"]
    secs = []
    for title, body in sections(hub["html"]):
        name = re.sub(r"^\d+\.\s*", "", title)
        if name.startswith(SECTIONS):
            secs.append({"title": name, "html": clean(body)})
    pages = []
    for c in b["children"]:
        short = next((body for t, body in sections(c["html"]) if re.sub(r"^\d+\.\s*", "", t).startswith("Кратко")), "")
        if not short:   # нет «0. Кратко» (h1 у реестра MCP) — первый абзац страницы
            m = re.search(r"<p[^>]*>(.*?)</p>", c["html"], re.S)
            short = m.group(0) if m else ""
        pages.append({"title": c["title"], "url": page_url(c["id"]), "version": c["version"],
                      "updated": (c.get("when") or "")[:10], "by": c.get("by"), "summary": plain(short)[:600]})
    data = json.load(open(data_path, encoding="utf-8"))
    data["beegptTrack"] = {"source": "Confluence, хаб «Трек «Интеграция с beeGPT»» и подстраницы",
                           "hub": {"title": hub["title"], "url": page_url(hub["id"]), "version": hub["version"],
                                   "updated": (hub.get("when") or "")[:10], "by": hub.get("by")},
                           "sections": secs, "pages": pages}
    json.dump(data, open(data_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"OK beegptTrack: разделов {len(secs)} ({', '.join(s['title'][:20] for s in secs)}), подстраниц {len(pages)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
