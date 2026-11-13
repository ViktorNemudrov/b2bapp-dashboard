"""Статус сценариев от Альфы → public/data/data.json (ключ alfaTrack) для вкладки 07 «Статуса».

Источник — раздел «Статус» на страницах сценариев в Confluence (ведёт Клейменова, с 13.11.2026):
строка «Статус на дд.мм.гггг: …», затем блоки «Ограничения и открытые вопросы» / «Открытые вопросы» /
«Следующие шаги» списками. Выгрузка — Blob-download с bwiki (body.view) в cf/cf_alfa_ДДММ.json:
[{name, short, id, title, version, when, by, html}].

    python import_alfa_status.py cf/cf_alfa_ДДММ.json [public/data/data.json]
"""
import html
import json
import re
import sys
from html.parser import HTMLParser

BLOCK_RE = re.compile(r"^(ограничения|открытые вопросы|следующие шаги|риски|что сделано|блокеры)", re.I)


class Flat(HTMLParser):
    """Текст абзацев, пунктов списка и заголовков по порядку: [(tag, text)]."""
    def __init__(self):
        super().__init__()
        self.out, self.buf, self.tag, self.depth = [], [], None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "br" and self.tag:      # строки внутри одного абзаца — отдельные токены
            t = self.tag
            self.flush()
            self.tag = t
            return
        if tag in ("p", "li", "h1", "h2", "h3", "h4"):
            self.flush()
            self.tag = tag

    def handle_endtag(self, tag):
        if tag in ("p", "li", "h1", "h2", "h3", "h4"):
            self.flush()

    def handle_data(self, data):
        if self.tag:
            self.buf.append(data)

    def flush(self):
        t = re.sub(r"\s+", " ", html.unescape("".join(self.buf))).strip()
        if self.tag and t:
            self.out.append((self.tag, t))
        self.buf, self.tag = [], None


def status_of(page):
    f = Flat()
    f.feed(page["html"])
    toks = f.out
    i = next((k for k, (tg, t) in enumerate(toks) if tg.startswith("h") and t.strip().lower() == "статус"), None)
    if i is None:
        return None
    seg = []
    for tg, t in toks[i + 1:]:
        if tg.startswith("h"):
            break
        seg.append((tg, t))
    headline, date_, blocks, cur = None, None, [], None
    for tg, t in seg:
        m = re.match(r"^Статус на (\d{2})\.(\d{2})\.(\d{4})\s*:?\s*(.*)$", t)
        if m and headline is None:
            date_ = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            headline = m.group(4).strip()
        elif BLOCK_RE.match(t) and len(t) < 60:
            cur = {"title": t.rstrip(":"), "items": []}
            blocks.append(cur)
        elif cur is not None:
            cur["items"].append(t)
        elif headline is not None:
            headline += " " + t
    if headline:
        headline = headline[:1].upper() + headline[1:]
    return {"name": page["name"], "title": page["title"], "url": page["short"], "pageId": page["id"],
            "version": page["version"], "updated": (page.get("when") or "")[:10], "by": page.get("by"),
            "statusDate": date_, "headline": headline, "blocks": blocks}


def main(src, data_path="public/data/data.json"):
    pages = json.load(open(src, encoding="utf-8"))
    rows = [r for r in (status_of(p) for p in pages) if r]
    data = json.load(open(data_path, encoding="utf-8"))
    data["alfaTrack"] = {"source": "Confluence, раздел «Статус» на страницах сценариев (Клейменова)",
                         "collectedAt": max((r["updated"] for r in rows), default=None), "scenarios": rows}
    json.dump(data, open(data_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"OK alfaTrack: {len(rows)} из {len(pages)} страниц — "
          + "; ".join(f"{r['name']}: статус {r['statusDate']}, блоков {len(r['blocks'])}" for r in rows))


if __name__ == "__main__":
    main(*sys.argv[1:])
