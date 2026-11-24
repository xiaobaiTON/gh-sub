#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate public proxy sources, test them through Xray, publish a clean subscription."""
import argparse, base64, itertools, json, os, random, re, socket, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote
from urllib.request import Request, urlopen

SCHEMES = ("vless", "vmess", "trojan", "ss")
UA = {"User-Agent": "Mozilla/5.0 v2rayN/6.0"}


def b64d(text):
    text = re.sub(r"\s+", "", text)
    text += "=" * (-len(text) % 4)
    try:
        return base64.b64decode(text).decode("utf-8", "ignore")
    except Exception:
        return ""


def fetch(url, timeout=25):
    raw = ""
    for attempt in range(3):
        try:
            req = Request(url, headers=UA)
            raw = urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
            break
        except Exception as e:
            if attempt == 2:
                print(f"[skip] {url} {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    if not raw:
        return ""
    if "://" not in raw:
        raw = b64d(raw)
    return raw


def parse_qs(q):
    out = {}
    for kv in q.split("&"):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        out[unquote(k)] = unquote(v)
    return out


def parse_node(link):
    link = link.strip()
    if not link or "://" not in link:
        return None
    scheme = link.split("://", 1)[0]
    if scheme not in SCHEMES:
        return None
    body = link.split("#", 1)[0]
    host, port, extra = None, 0, {}
    try:
        if scheme == "vmess":
            obj = json.loads(b64d(link[8:]))
            host, port = obj.get("add"), int(obj.get("port", 0))
            extra = obj
        else:
            m = re.search(r"@(\[[^\]]+\]|[^:@/?]+):(\d{2,5})", body)
            if m:
                host, port = m.group(1).strip("[]"), int(m.group(2))
            if scheme == "vless":
                q = body.split("?", 1)[1] if "?" in body else ""
                extra = parse_qs(q)
            elif scheme == "trojan":
                q = body.split("?", 1)[1] if "?" in body else ""
                extra = parse_qs(q)
            elif scheme == "ss":
                b = body[5:]
                if "@" in b:
                    ui, hp = b.split("@", 1)
                    dec = b64d(ui)
                    method, pwd = dec.split(":", 1) if ":" in dec else ("", "")
                    m2 = re.match(r"(\[[^\]]+\]|[^:]+):(\d+)", hp)
                    if m2:
                        host, port = m2.group(1).strip("[]"), int(m2.group(2))
                    extra = {"method": method, "password": pwd}
                else:
                    dec = b64d(b)
                    m2 = re.match(r"([^:]+):(.*?)@(\[[^\]]+\]|[^:]+):(\d+)", dec)
                    if m2:
                        extra = {"method": m2.group(1), "password": m2.group(2)}
                        host, port = m2.group(3).strip("[]"), int(m2.group(4))
    except Exception:
        return None
    if not host or not (1 < port < 65536):
        return None
    if re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.|localhost$)", host):
        return None
    return {"proto": scheme, "host": host, "port": port, "link": link, "extra": extra}


def node_key(node):
    e = node["extra"]
    ident = e.get("uuid") or e.get("id") or e.get("password") or e.get("method") or ""
    return f"{node['proto']}|{node['host']}|{node['port']}|{ident}"


def build_config(node, socks_port):
    p, e = node["proto"], node["extra"]
    host, port = node["host"], node["port"]
    if p == "vmess":
        net = e.get("net") or "tcp"
        ss = {"network": net, "security": "tls" if e.get("tls") else "none"}
        if e.get("tls"):
            ss["tlsSettings"] = {"serverName": e.get("sni") or e.get("host") or host}
        if net == "ws":
            ss["wsSettings"] = {"path": e.get("path") or "/", "headers": {"Host": e.get("host") or host}}
        elif net == "grpc":
            ss["grpcSettings"] = {"serviceName": e.get("path") or ""}
        out = {"protocol": "vmess", "settings": {"vnext": [{"address": host, "port": port, "users": [{
            "id": e.get("id"), "alterId": int(e.get("aid", 0) or 0), "security": e.get("scy") or "auto"}]}]},
            "streamSettings": ss}
    elif p == "vless":
        net = e.get("type") or "tcp"
        sec = e.get("security") or "none"
        ss = {"network": net, "security": sec}
        if sec == "tls":
            ss["tlsSettings"] = {"serverName": e.get("sni") or host}
        elif sec == "reality":
            ss["realitySettings"] = {"serverName": e.get("sni"), "fingerprint": e.get("fp") or "chrome",
                                     "publicKey": e.get("pbk"), "shortId": e.get("sid") or "", "spiderX": e.get("spx") or ""}
        if net == "ws":
            ss["wsSettings"] = {"path": e.get("path") or "/", "headers": {"Host": e.get("host") or e.get("sni") or host}}
        elif net == "grpc":
            ss["grpcSettings"] = {"serviceName": e.get("serviceName") or "grpc"}
        user = {"id": e.get("uuid") or node["link"].split("://", 1)[1].split("@", 1)[0], "encryption": "none"}
        if e.get("flow"):
            user["flow"] = e["flow"]
        out = {"protocol": "vless", "settings": {"vnext": [{"address": host, "port": port, "users": [user]}]},
               "streamSettings": ss}
    elif p == "trojan":
        net = e.get("type") or "tcp"
        ss = {"network": net, "security": "tls", "tlsSettings": {"serverName": e.get("sni") or host}}
        if net == "ws":
            ss["wsSettings"] = {"path": e.get("path") or "/", "headers": {"Host": e.get("host") or host}}
        elif net == "grpc":
            ss["grpcSettings"] = {"serviceName": e.get("serviceName") or "grpc"}
        pwd = node["link"].split("://", 1)[1].split("@", 1)[0]
        out = {"protocol": "trojan", "settings": {"servers": [{"address": host, "port": port, "password": pwd}]},
               "streamSettings": ss}
    else:
        out = {"protocol": "shadowsocks", "settings": {"servers": [{
            "address": host, "port": port, "method": e.get("method"), "password": e.get("password")}]}}
    return {"log": {"loglevel": "error"},
            "inbounds": [{"listen": "127.0.0.1", "port": socks_port, "protocol": "socks",
                          "settings": {"udp": False}}],
            "outbounds": [out]}


def build_batch_config(nodes, ports):
    inbounds, outbounds, rules = [], [], []
    for i, (n, port) in enumerate(zip(nodes, ports)):
        cfg = build_config(n, port)
        if cfg is None:
            return None
        ib = cfg["inbounds"][0]
        ib["tag"] = f"in{i}"
        ob = cfg["outbounds"][0]
        ob["tag"] = f"out{i}"
        inbounds.append(ib)
        outbounds.append(ob)
        rules.append({"type": "field", "inboundTag": [f"in{i}"], "outboundTag": f"out{i}"})
    if not inbounds:
        return None
    return {"log": {"loglevel": "error"}, "inbounds": inbounds, "outbounds": outbounds,
            "routing": {"domainStrategy": "AsIs", "rules": rules}}


def socks_probe(socks_port, target, target_port=80, timeout=7.0):
    start = time.time()
    end = start + timeout
    s = socket.create_connection(("127.0.0.1", socks_port), timeout=3)
    s.settimeout(timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            return None
        host = target.encode()
        req = b"\x05\x01\x00\x03" + bytes([len(host)]) + host + bytes([target_port >> 8, target_port & 255])
        s.sendall(req)
        head = s.recv(4)
        if len(head) < 4 or head[1] != 0:
            return None
        atyp = head[3]
        extra = 4 if atyp == 1 else 16 if atyp == 4 else s.recv(1)[0]
        need = extra + 2
        got = b""
        while len(got) < need:
            if time.time() > end:
                return None
            chunk = s.recv(need - len(got))
            if not chunk:
                return None
            got += chunk
        s.sendall(f"GET /generate_204 HTTP/1.1\r\nHost: {target}\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while b"\r\n" not in data:
            if time.time() > end:
                return None
            chunk = s.recv(512)
            if not chunk:
                return None
            data += chunk
        if b" 204 " not in data.split(b"\r\n", 1)[0]:
            return None
        return time.time() - start
    except Exception:
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass


def probe_all(port, targets, budget=8.0):
    end = time.time() + budget
    best = None
    for target in targets:
        left = end - time.time()
        if left <= 0.5:
            return None
        lat = socks_probe(port, target[0], target[1], timeout=min(7.0, left))
        if lat is None:
            return None
        best = lat if best is None else min(best, lat)
    return best


def wait_ports(ports, timeout=15.0):
    pending = set(ports)
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        for p in list(pending):
            try:
                s = socket.create_connection(("127.0.0.1", p), timeout=0.2)
                s.close()
                pending.discard(p)
            except Exception:
                pass
        if pending:
            time.sleep(0.05)
    return pending


def test_batch(nodes, ports, xray_bin, targets):
    cfg = build_batch_config(nodes, ports)
    if cfg is None:
        return []
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen([xray_bin, "-c", path], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        missing = wait_ports(ports)
        live = [(n, p) for n, p in zip(nodes, ports) if p not in missing]
        if not live:
            return []
        found = {}
        with ThreadPoolExecutor(max_workers=len(live)) as ex:
            futs = {ex.submit(probe_all, p, targets): n for n, p in live}
            for fut in as_completed(futs):
                node = futs[fut]
                try:
                    lat = fut.result()
                except Exception:
                    lat = None
                if lat is not None:
                    found[id(node)] = lat
        return [(n, found[id(n)]) for n in nodes if id(n) in found]
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            os.unlink(path)
        except Exception:
            pass


def yq(s):
    return json.dumps(str(s), ensure_ascii=False)


def sid_ok(s):
    if not isinstance(s, str):
        return ""
    t = s.strip().strip("\"'").lower()
    if re.fullmatch(r"[0-9a-f]{2,16}", t) and len(t) % 2 == 0:
        return t
    return ""


def clash_yaml(nodes):
    lines = ["mixed-port: 7890", "allow-lan: false", "mode: rule", "log-level: info", "proxies:"]
    names = []
    for i, n in enumerate(nodes, 1):
        p, e, host, port = n["proto"], n["extra"], n["host"], n["port"]
        if e.get("type") == "raw":
            e["type"] = "tcp"
        if e.get("net") == "raw":
            e["net"] = "tcp"
        name = f"{p.upper()}-{i:02d}-{host[:28]}"
        names.append(name)
        lines.append(f"  - name: {yq(name)}")
        if p == "vmess":
            net = e.get("net") or "tcp"
            lines += [f"    type: vmess", f"    server: {host}", f"    port: {port}",
                      f"    uuid: {yq(e.get('id'))}", f"    alterId: {int(e.get('aid', 0) or 0)}",
                      f"    cipher: {e.get('scy') or 'auto'}",
                      f"    tls: {'true' if e.get('tls') else 'false'}"]
            if e.get("sni"):
                lines.append(f"    servername: {yq(e['sni'])}")
            lines.append(f"    network: {net}")
            if net == "ws":
                lines += ["    ws-opts:", f"      path: {yq(e.get('path') or '/')}", "      headers:",
                          f"        Host: {yq(e.get('host') or host)}"]
            elif net == "grpc":
                lines += ["    grpc-opts:", f"      grpc-service-name: {yq(e.get('path') or 'grpc')}"]
        elif p == "ss":
            lines += ["    type: ss", f"    server: {host}", f"    port: {port}",
                      f"    cipher: {yq(e.get('method'))}", f"    password: {yq(e.get('password'))}", "    udp: true"]
        else:
            net = e.get("type") or "tcp"
            sec = e.get("security") or "none"
            lines += [f"    type: {p}", f"    server: {host}", f"    port: {port}",
                      f"    uuid: {yq(n['link'].split('://', 1)[1].split('@', 1)[0])}",
                      f"    network: {net}", f"    tls: {'true' if sec != 'none' else 'false'}"]
            if e.get("sni"):
                lines.append(f"    servername: {yq(e['sni'])}")
            lines.append(f"    client-fingerprint: {e.get('fp') or 'chrome'}")
            if sec == "reality" and e.get("pbk"):
                lines += ["    reality-opts:", f"      public-key: {yq(e['pbk'])}"]
                sid = sid_ok(e.get("sid"))
                if sid:
                    lines.append(f"      short-id: {yq(sid)}")
            if e.get("alpn"):
                lines.append("    alpn:")
                for a in e["alpn"].split(","):
                    lines.append(f"      - {yq(a)}")
            if net == "ws":
                lines += ["    ws-opts:", f"      path: {yq(e.get('path') or '/')}", "      headers:",
                          f"        Host: {yq(e.get('host') or e.get('sni') or host)}"]
            elif net == "grpc":
                lines += ["    grpc-opts:", f"      grpc-service-name: {yq(e.get('serviceName') or 'grpc')}"]
            if e.get("flow"):
                lines.append(f"    flow: {yq(e['flow'])}")
    lines += ["proxy-groups:", '  - name: "AUTO"', "    type: url-test",
              '    url: "https://www.gstatic.com/generate_204"', "    interval: 300", "    tolerance: 50",
              "    proxies:"]
    lines += [f"      - {yq(x)}" for x in names]
    head = names[:5] or ["DIRECT"]
    lines += ['  - name: "FALLBACK"', "    type: fallback",
              '    url: "https://www.gstatic.com/generate_204"', "    interval: 300", "    proxies:",
              '      - "AUTO"']
    lines += [f"      - {yq(x)}" for x in head]
    lines += ["rules:", "  - MATCH,FALLBACK"]
    return "\n".join(lines) + "\n"


def load_nodes(path):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8-sig"):
        n = parse_node(line)
        if n:
            out.append(n)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="sources.txt")
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--keep", type=int, default=150)
    ap.add_argument("--xray", default=os.environ.get("XRAY_BIN", os.path.join("xray", "xray.exe" if os.name == "nt" else "xray")))
    ap.add_argument("--extra-sources", action="store_true")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    args.batch = max(1, args.batch)
    args.workers = max(1, args.workers)

    if not os.path.exists(args.xray):
        sys.exit(f"xray not found: {args.xray}")

    verified = load_nodes("verified.txt")
    web_nodes = load_nodes("links.web.txt")

    raw_nodes = []
    source_files = [args.sources]
    if os.path.exists("sources.auto.txt"):
        source_files.append("sources.auto.txt")
    if args.extra_sources and os.path.exists("sources.web.txt"):
        source_files.append("sources.web.txt")
    for sf in source_files:
        for line in open(sf, encoding="utf-8-sig"):
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            raw_nodes.extend(load_nodes_from_text(fetch(url)))

    seen, keep, web_pool, pool = set(), [], [], []
    for n in verified:
        k = node_key(n)
        if k not in seen:
            seen.add(k)
            keep.append(n)
    for n in web_nodes:
        k = node_key(n)
        if k in seen:
            continue
        seen.add(k)
        web_pool.append(n)
    for n in raw_nodes:
        k = node_key(n)
        if k in seen:
            continue
        seen.add(k)
        pool.append(n)
    print(f"collected={len(pool) + len(web_pool) + len(keep)} verified={len(keep)} web={len(web_pool)}")
    if args.limit:
        room = max(0, args.limit - len(keep))
        web_take = min(len(web_pool), room // 2)
        if web_take:
            keep += random.sample(web_pool, web_take)
            room -= web_take
        if room:
            keep += random.sample(pool, min(room, len(pool)))
    else:
        keep += web_pool + pool
    nodes = keep
    print(f"testing={len(nodes)} batch={args.batch} workers={args.workers}")

    counter = itertools.count(20000)
    lock = threading.Lock()

    def take_ports(k):
        with lock:
            return [next(counter) for _ in range(k)]

    def run_round(items, targets):
        batches = [items[i:i + args.batch] for i in range(0, len(items), args.batch)]
        passed, total = [], len(items)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(test_batch, b, take_ports(len(b)), args.xray, targets): len(b) for b in batches}
            for i, fut in enumerate(as_completed(futs), 1):
                try:
                    passed.extend(fut.result())
                except Exception as e:
                    print(f"[batch error] {e}", file=sys.stderr)
                print(f"batch {i}/{len(batches)} pass={len(passed)}", flush=True)
        return passed

    t0 = time.time()
    targets_a = (("www.gstatic.com", 80), ("cp.cloudflare.com", 80))
    targets_b = (("cp.cloudflare.com", 80), ("www.gstatic.com", 80))
    first = run_round(nodes, targets_a)
    print(f"round1 pass={len(first)} time={time.time()-t0:.0f}s")

    t1 = time.time()
    second = run_round([n for n, _ in first], targets_b)
    print(f"round2 pass={len(second)} time={time.time()-t1:.0f}s")

    second.sort(key=lambda x: x[1])
    result = second[: args.keep]
    print(f"kept={len(result)}")

    out = args.out
    os.makedirs(out, exist_ok=True)
    links = [n["link"] for n, _ in result]
    with open(os.path.join(out, "nodes.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(links))
    sub = base64.b64encode("\n".join(links).encode()).decode()
    with open(os.path.join(out, "sub.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(sub)
    with open(os.path.join(out, "clash.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(clash_yaml([n for n, _ in result]))
    stats = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collected": len(nodes),
        "round1_pass": len(first),
        "round2_pass": len(second),
        "published": len(result),
        "proxies": {},
        "fastest_ms": round(result[0][1] * 1000) if result else None,
    }
    for n, _ in result:
        stats["proxies"][n["proto"]] = stats["proxies"].get(n["proto"], 0) + 1
    with open(os.path.join(out, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out, "stats.history.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(stats, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


def load_nodes_from_text(text):
    out = []
    for line in text.splitlines():
        n = parse_node(line)
        if n:
            out.append(n)
    return out


if __name__ == "__main__":
    main()