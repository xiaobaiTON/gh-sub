import base64, json, os, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API = "https://api.github.com"


def call(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(API + path, method=method, data=data, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "gh-sub push tool",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {detail}")


def push(repo, branch, local, remote, message, token):
    blob = open(local, "rb").read()
    sha = None
    try:
        cur = call("GET", f"/repos/{repo}/contents/{remote}?ref={branch}", token)
        sha = cur.get("sha")
    except SystemExit:
        pass
    body = {"message": message, "content": base64.b64encode(blob).decode(), "branch": branch}
    if sha:
        body["sha"] = sha
    r = call("PUT", f"/repos/{repo}/contents/{remote}", token, body)
    return r["commit"]["sha"][:8], r["content"]["path"]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="update from push.py")
    ap.add_argument("--token-env", default="GITHUB_TOKEN")
    ap.add_argument("files", nargs="+", help="local paths; remote path keeps the same relative name")
    args = ap.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        sys.exit(f"{args.token_env} is empty; create a fine-grained token with Contents: Read and write")

    for local in args.files:
        remote = local.replace("\\\\", "/").lstrip("./")
        sha, path = push(args.repo, args.branch, local, remote, args.message, token)
        print(f"{sha}  {path}")


if __name__ == "__main__":
    main()