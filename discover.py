import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen

TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "proxy-sub"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

QUERIES = [
    "topic:v2ray-configs pushed:>{since}",
    "topic:clash-subscription pushed:>{since}",
    "v2ray free subscription pushed:>{since}",
    "clash subscription free pushed:>{since}",
]
PATHS = [
    "nodes.txt", "sub", "sub.txt", "list.txt", "v2ray.txt", "v2ray-base64.txt",
    "clash.yaml", "clash_config.yaml", "all.txt", "v2",
    "sub/sub_merge_base64.txt", "output/v2ray-base64.txt", "nodes/v2ray-base64.txt",
    "nodes/clash.yaml", "All_Configs_Sub.txt",
]


def api(url):
    try:
        return json.loads(urlopen(Request(url, headers=HEADERS), timeout=20).read())
    except Exception as e:
        print(f"skip {url} {e}", file=sys.stderr)
        return None


def probe(url):
    try:
        req = Request(url, headers={"User-Agent": "proxy-sub"}, method="HEAD")
        r = urlopen(req, timeout=10)
        size = int(r.headers.get("Content-Length") or 0)
        return url if r.status == 200 and size > 200 else None
    except Exception:
        return None


def main():
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400))
    repos, seen = [], set()
    for q in QUERIES:
        query = q.format(since=since).replace(" ", "+").replace(":", "%3A")
        data = api(f"{API}/search/repositories?q={query}&sort=updated&order=desc&per_page=20")
        for repo in (data or {}).get("items", []):
            if repo["full_name"] not in seen:
                seen.add(repo["full_name"])
                repos.append(repo["full_name"])

    tasks = [(r, p) for r in repos[:60] for p in PATHS]
    found, hits = [], {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(probe, f"https://raw.githubusercontent.com/{r}/HEAD/{p}"): r for r, p in tasks}
        for fut in as_completed(futs):
            url = fut.result()
            if not url:
                continue
            repo = futs[fut]
            hits[repo] = hits.get(repo, 0) + 1
            if hits[repo] <= 2:
                found.append(url)

    found = found[:40]
    with open("sources.auto.txt", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(found))
    print(f"repos={len(repos)} discovered={len(found)}")


if __name__ == "__main__":
    main()