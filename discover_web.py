import html as H
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
SCHEMES = ("vless", "vmess", "trojan", "ss", "hysteria2", "hy2", "tuic")
LINK_RE = re.compile(r"(?:vless|vmess|trojan|ss|hysteria2|hy2|tuic)://[^\s\"'<>\\]+")
URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")
SKIP_HOSTS = ("t.me", "telegram", "twitter.com", "x.com", "youtube", "google.",
              "facebook", "instagram", "github.com", "t.me", "apple.com")


def get(url, timeout=20, data=None):
    try:
        req = Request(url, headers=UA, data=data)
        raw = urlopen(req, timeout=timeout).read()
        return raw.decode("utf-8", "ignore")
    except Exception as e:
        print(f"[skip] {url} {e}", file=sys.stderr)
        return ""


def clean_url(u):
    u = H.unescape(u).strip().rstrip('.,;)]}>"\'')
    return u


def nodes_from(text):
    out = []
    for m in LINK_RE.finditer(H.unescape(text)):
        out.append(clean_url(m.group(0)))
    return out


def subs_from(text):
    out = []
    for m in URL_RE.finditer(H.unescape(text)):
        u = clean_url(m.group(0))
        host = urlparse(u).netloc.lower()
        if any(s in host for s in SKIP_HOSTS):
            continue
        path = urlparse(u).path.lower()
        low = u.lower()
        if path.endswith((".txt", ".yaml", ".yml", ".json", ".conf", ".sub")) or \
           any(k in low for k in ("sub", "node", "clash", "v2ray", "vless", "vmess", "trojan", "subscribe", "free")):
            out.append(u)
    return out
TG_CHANNELS = [
    "v2ray_configs", "v2rayfree", "v2rayng", "freev2ray", "clash_config",
    "sublink", "v2ray_subscribe", "freenode", "nodefree", "v2ray_channel",
    "proxyfree", "shadowsocks", "vpnfree", "free_vpn", "jichangtuijian",
]
QUERIES = ["vless 订阅", "vmess 订阅", "clash 订阅 免费节点", "免费节点 订阅",
           "vless subscription", "free v2ray subscription"]
AGGREGATORS = [
    ("https://clashnode.com", ["/", "/free-nodes/", "/clash/"]),
    ("https://nodefree.org", ["/", "/free-nodes/"]),
    ("https://www.v2rayshare.com", ["/", "/free-v2ray/"]),
    ("https://clashgithub.com", ["/"]),
    ("https://freeclashnode.com", ["/"]),
]


def telegram():
    nodes, subs = [], []
    for ch in TG_CHANNELS:
        page = get(f"https://t.me/s/{ch}")
        if not page:
            continue
        nodes += nodes_from(page)
        for url in subs_from(page):
            if "t.me" in url:
                continue
            subs.append(url)
        print(f"[tg] {ch} nodes={len(nodes)} subs={len(subs)}", file=sys.stderr)
    return nodes, subs


X_TOKEN = os.environ.get("X_BEARER_TOKEN", "")
GOOGLE_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CX = os.environ.get("GOOGLE_CX", "")


def x_search():
    if not X_TOKEN:
        return [], []
    headers = {"Authorization": f"Bearer {X_TOKEN}", "User-Agent": "proxy-sub"}
    nodes, subs = [], []
    for q in ("vless", "vmess", "clash 订阅", "免费节点 订阅"):
        url = ("https://api.x.com/2/tweets/search/recent?max_results=50"
               "&tweet.fields=entities,text&expansions=entities.urls&query=" + quote_plus(q))
        try:
            raw = urlopen(Request(url, headers=headers), timeout=20).read().decode("utf-8", "ignore")
            data = json.loads(raw)
        except Exception as e:
            print(f"[x] skip {q} {e}", file=sys.stderr)
            continue
        for tw in data.get("data", []) or []:
            text = tw.get("text", "")
            nodes += nodes_from(text)
            subs += subs_from(text)
            for ent in (tw.get("entities", {}) or {}).get("urls", []) or []:
                u = ent.get("expanded_url", "")
                if u:
                    subs += subs_from(u)
    return nodes, subs


def google_search():
    if not GOOGLE_KEY or not GOOGLE_CX:
        return [], []
    nodes, subs = [], []
    for q in ("vless 订阅", "vmess 订阅", "clash 订阅 免费节点", "free v2ray subscription"):
        url = (f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_KEY}&cx={GOOGLE_CX}"
               f"&num=10&q=" + quote_plus(q))
        try:
            data = json.loads(urlopen(Request(url, headers=UA), timeout=20).read().decode("utf-8", "ignore"))
        except Exception as e:
            print(f"[google] skip {q} {e}", file=sys.stderr)
            continue
        for item in data.get("items", []) or []:
            u = item.get("link", "")
            page = get(u, 15)
            if page:
                nodes += nodes_from(page)
                subs += subs_from(page)
    return nodes, subs


def results(query):
    urls = []
    ddg = get("https://html.duckduckgo.com/html/?q=" + quote_plus(query))
    for m in re.finditer(r"uddg=([^&\"]+)", ddg):
        urls.append(unquote(m.group(1)))
    bing = get("https://www.bing.com/search?q=" + quote_plus(query))
    for m in re.finditer(r"<h2><a href=\"(https?://[^\"]+)\"", bing):
        urls.append(m.group(1))
    out = []
    for u in urls:
        host = urlparse(u).netloc.lower()
        if any(s in host for s in SKIP_HOSTS) or host.endswith("bing.com") or host.endswith("duckduckgo.com"):
            continue
        out.append(u)
    return out


def web_pages():
    nodes, subs = [], []
    queries = []
    for q in QUERIES:
        queries += results(q)
    seen, pages = set(), []
    for u in queries:
        host = urlparse(u).netloc.lower()
        if host in seen:
            continue
        seen.add(host)
        pages.append(u)
        if len(pages) >= 20:
            break
    print(f"[web] pages={len(pages)}", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(get, u, 15): u for u in pages}
        for fut in as_completed(futs):
            page = fut.result()
            if not page:
                continue
            nodes += nodes_from(page)
            subs += subs_from(page)
    return nodes, subs


def aggregators():
    nodes, subs = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
        for host, paths in AGGREGATORS:
            for p in paths:
                futs.append(ex.submit(get, host + p, 15))
        for fut in as_completed(futs):
            page = fut.result()
            if not page:
                continue
            nodes += nodes_from(page)
            subs += subs_from(page)
    return nodes, subs


def dedupe(items):
    seen, out = set(), []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def main():
    n, s = telegram()
    n2, s2 = web_pages()
    n3, s3 = aggregators()
    n4, s4 = x_search()
    n5, s5 = google_search()
    nodes = dedupe(n + n2 + n3 + n4 + n5)[:1500]
    subs = dedupe(s + s2 + s3 + s4 + s5)[:80]
    with open("links.web.txt", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(nodes))
    with open("sources.web.txt", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(subs))
    print(f"nodes={len(nodes)} subs={len(subs)}")


if __name__ == "__main__":
    main()
