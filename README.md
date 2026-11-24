# proxy-sub

![scan](https://github.com/xiaobaiTON/gh-sub/actions/workflows/scan.yml/badge.svg)

全自动代理筛选订阅：多来源发现 → 抓取 → Xray 逐节点真连通性检测 → 两轮复测 → 按延迟排序 → 发布订阅。

## 来源覆盖

| 渠道 | 方式 | 需要凭证 |
| --- | --- | --- |
| GitHub 仓库 | `discover.py`：API 搜索最近 30 天活跃仓库，探测常见文件名 | 无（Actions 自带 token） |
| Telegram 频道 | `discover_web.py`：抓 `t.me/s/<频道>` 公开预览页，解析消息里的节点和订阅 | 无 |
| Bing / DuckDuckGo | `discover_web.py`：搜索结果页解析，抓前 20 个结果页 | 无 |
| 代理聚合站 | `discover_web.py`：clashnode / nodefree / v2rayshare / clashgithub 等 | 无 |
| X（Twitter） | 官方 API v2 recent search，可选 | `X_BEARER_TOKEN`（付费档） |
| Google | Programmable Search JSON API，可选 | `GOOGLE_API_KEY` + `GOOGLE_CX`（每天 100 次免费） |

`verified.txt` 是人工确认的种子节点，永远优先参与测试并排在最前。

## 工作流

```
discover.py       GitHub 仓库发现 → sources.auto.txt
discover_web.py   Telegram / 搜索 / 聚合站 / X / Google → links.web.txt + sources.web.txt
scan.py           sources.txt + sources.auto.txt + sources.web.txt + links.web.txt + verified.txt
                  每个节点起独立 Xray，SOCKS5 → HTTP 204 两轮实测 → 排序 → 输出
Actions           每 6 小时跑一轮，提交到 main
```

## 文件

| 文件 | 用途 |
| --- | --- |
| `sub.txt` | Base64 订阅（v2rayN / v2rayNG / 小火箭 / NekoBox / Hiddify） |
| `nodes.txt` | 明文 URI |
| `clash.yaml` | Clash / Mihomo 配置，含 `AUTO` url-test 组 |
| `stats.json` | 采集数、两轮通过数、协议分布、最快延迟 |
| `sources.txt` | 固定订阅源 |
| `sources.auto.txt` | GitHub 自动发现源 |
| `sources.web.txt` | Telegram / 搜索 / 聚合站发现的可疑订阅 |
| `links.web.txt` | Telegram / 搜索 / 聚合站直接抓到的节点 |
| `verified.txt` | 人工确认种子节点 |

## 检测标准

1. 每个节点生成独立 Xray 配置，监听本地 SOCKS5 端口；
2. SOCKS5 CONNECT `www.gstatic.com:80` → `GET /generate_204` 必须 204；
3. 同一节点再对 `cp.cloudflare.com:80` 复测，两次都过才保留；
4. 按耗时升序，截断到 `--keep`；
5. 输出 Base64、明文、Clash YAML、统计 JSON。

支持 `vless`（tcp/ws/grpc，tls/reality）、`vmess`、`trojan`、`shadowsocks`。Hysteria2/TUIC 需要额外客户端，未纳入自动检测。

## 本地运行

```bash
# 只跑 GitHub 源
python scan.py --limit 300 --workers 16 --keep 80 --xray E:\墙\xray\xray.exe

# 加上 Telegram / 搜索 / 聚合站点
python discover_web.py
python scan.py --limit 300 --workers 16 --keep 80 --xray E:\墙\xray\xray.exe
```

参数：

- `--limit` 每轮测试上限（默认 1500；`verified.txt` 不占名额）
- `--workers` 并发 Xray 实例数（默认 24）
- `--keep` 发布上限（默认 200）
- `--sources` 固定源文件，默认 `sources.txt`
- `--out` 输出目录，默认当前目录

采样策略：`verified.txt` 全测；剩余名额一半给 `links.web.txt`（Telegram/搜索），一半给 GitHub 聚合池。

## 上传到 GitHub

```bash
cd gh-sub
git init -b main
git add .
git commit -m "init proxy-sub"
git remote add origin https://github.com/xiaobaiTON/gh-sub.git
git push -u origin main
```

网页方式：

1. 新建 public 仓库；
2. **Add file → Upload files** 上传根目录文件；
3. **Add file → Create new file**，路径 `.github/workflows/scan.yml`，粘贴本地同名文件；
4. **Settings → Actions → General → Workflow permissions** 选 **Read and write**；
5. **Actions → proxy-sub → Run workflow**。

可选 Secrets（不配也能跑，只是少了 X / Google 渠道）：

```
X_BEARER_TOKEN   X API v2 Bearer Token
GOOGLE_API_KEY   Google Programmable Search API Key
GOOGLE_CX        Google 自定义搜索引擎 ID
```

## 订阅地址

```
https://raw.githubusercontent.com/xiaobaiTON/gh-sub/main/sub.txt
https://raw.githubusercontent.com/xiaobaiTON/gh-sub/main/clash.yaml
https://cdn.jsdelivr.net/gh/xiaobaiTON/gh-sub@main/sub.txt
https://cdn.jsdelivr.net/gh/xiaobaiTON/gh-sub@main/clash.yaml
```

客户端用 `AUTO` / `url-test` 自动选最快线路。

## 实测参考

- `scan.py --limit 120 --workers 8 --keep 50`：采集 4718，第一轮 24 过，第二轮 21 过，最快 338 ms；
- `discover_web.py`：Telegram + 搜索 + 聚合站抓到 737 条直接节点、80 条订阅线索；
- 单独抽测 40 条 Telegram/搜索节点：2 条通过（约 5%），与公共免费源的常见水平一致；
- 扫完把 `links.web.txt` 一起接入后：`--limit 220 --workers 12` 第一轮 23 过、第二轮 21 过，Clash 配置用 `mihomo -t` 校验通过。

## 维护建议

- 公共节点寿命短，订阅每轮都会变化，靠 `AUTO` 组自动切换；
- `stats.json` 的 `round1_pass` / `round2_pass` / `fastest_ms` 可以直接判断当轮源质量；
- 想提高质量：减小 `--keep`、加一条 `l < 3.0` 的延迟过滤、增加第三轮目标域名；
- 想扩来源：改 `discover.py` 的 `QUERIES` / `PATHS`，或 `discover_web.py` 的 `TG_CHANNELS` / `AGGREGATORS` / `QUERIES`。
