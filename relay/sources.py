"""خواندن صفحه‌ی اخبار سازمان‌ها، تشخیص خبر جدید و استخراج متن. فقط کتابخانه‌ی استاندارد."""
import hashlib, re, time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
import config

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
      "Accept-Language": "fa,en;q=0.8"}
FA = re.compile(r"[\u0600-\u06FF]")

class _Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links, self.feeds, self._href, self._buf = [], [], None, []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._href, self._buf = a["href"], []
        elif tag == "link" and "xml" in (a.get("type") or "") and a.get("href"):
            self.feeds.append(a["href"])
    def handle_data(self, d):
        if self._href is not None: self._buf.append(d)
    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            t = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self.links.append((t, self._href)); self._href = None

ARTICLE_URL = re.compile(r"\d{4,}|/news/|/fa/news|/content/|/node/|/post/")
BAD_URL = re.compile(r"/(tag|tags|category|service|page|search|contact|about)(/|$)")

def extract_links(html: str, base: str, min_len=22):
    p = _Links(); p.feed(html)
    host = urlparse(base).netloc.replace("www.", "")
    out, seen = [], set()
    for title, href in p.links:
        url = urljoin(base, href.split("#")[0])
        if len(title) < min_len or not FA.search(title) or host not in urlparse(url).netloc:
            continue
        if url in seen or url.rstrip("/") == base.rstrip("/") or BAD_URL.search(url):
            continue
        if not (ARTICLE_URL.search(url) or len(title) >= 45):   # منوها و بخش‌های سایت حذف شوند
            continue
        seen.add(url); out.append({"title": title, "url": url})
    return out, [urljoin(base, f) for f in p.feeds]

def parse_feed(xml_text: str):
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for it in root.iter():
        if it.tag.endswith("item") or it.tag.endswith("entry"):
            title = link = ""
            for ch in it:
                n = ch.tag.split("}")[-1]
                if n == "title": title = (ch.text or "").strip()
                if n == "link": link = (ch.text or ch.attrib.get("href") or "").strip()
            if title and link: out.append({"title": title, "url": link})
    return out

class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "form"}
    def __init__(self):
        super().__init__(); self.parts, self.skip, self.in_p = [], 0, False
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag == "p": self.in_p = True
    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == "p": self.in_p = False
    def handle_data(self, d):
        if self.in_p and not self.skip and d.strip(): self.parts.append(d.strip())

def extract_text(html: str, limit=4500) -> str:
    p = _Text(); p.feed(html)
    txt = "\n".join(x for x in p.parts if len(x) > 25)
    return txt[:limit]

_KW = None
def is_relevant(title: str) -> bool:
    """کلمه باید ابتدای یک واژه باشد (تا «خانه» داخل «وزارتخانه» را نگیرد)."""
    global _KW
    if _KW is None:
        _KW = re.compile(r"(?<![\u0600-\u06FF])(?:" + "|".join(re.escape(k) for k in config.KEYWORDS) + ")")
    return bool(_KW.search(title))

def uid(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]

async def fetch(url: str, timeout=20):
    import httpx
    async with httpx.AsyncClient(timeout=timeout, headers=UA, follow_redirects=True, verify=False) as c:
        t = time.time(); r = await c.get(url)
        return r, round(time.time() - t, 1)

async def list_items(src: dict):
    r, _ = await fetch(src["url"])
    r.raise_for_status()
    items, feeds = extract_links(r.text, src["url"])
    if feeds:
        try:
            fr, _ = await fetch(feeds[0])
            fi = parse_feed(fr.text)
            if fi: return fi
        except Exception:
            pass
    return items

async def article_text(url: str) -> str:
    r, _ = await fetch(url)
    r.raise_for_status()
    return extract_text(r.text)
