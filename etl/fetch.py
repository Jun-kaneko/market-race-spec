"""一覧ページ -> 月ページ -> CSV の取得 (P0)。

使い方:
    python -m etl.fetch                 # 未取得の月だけ取得し、レポートを出力
    python -m etl.fetch --force         # 取得済みの月も再取得
    python -m etl.fetch --months 2023-01,2026-08
    python -m etl.fetch --report-only   # 取得せず data/raw から集計だけ行う

取得失敗が 1 件でもあれば終了コード 1。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .common import (
    DIVISIONS, EXPECTED_CATEGORIES, EXPECTED_HEADERS, FILENAME_RE, INDEX_URL, RAW_DIR, TABLE_KINDS,
    USER_AGENT, decode_csv, norm_text,
)

MONTH_LINK_RE = re.compile(r"(\d{4})年(\d{1,2})月分")
KIND_NAMES = {"11": "items", "12": "origins"}
SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


class Fetcher:
    def __init__(self, interval: float = 1.0, timeout: float = 30.0, retries: int = 3):
        self.interval = max(interval, 1.0)  # 仕様: 1 秒以上
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        # certifi ではなく OS の CA ストアを使う（社内プロキシ等の独自CA対策）。
        # REQUESTS_CA_BUNDLE が指定されていればそちらを優先する。
        if not os.environ.get("REQUESTS_CA_BUNDLE") and os.path.exists(SYSTEM_CA_BUNDLE):
            self.session.verify = SYSTEM_CA_BUNDLE
        self._last = 0.0

    def get(self, url: str) -> requests.Response:
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            wait = self.interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, timeout=self.timeout)
                self._last = time.monotonic()
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                self._last = time.monotonic()
                last_err = e
                if attempt < self.retries:
                    time.sleep(2 * attempt)
        raise RuntimeError(f"GET failed: {url}: {last_err}")


# ---------------------------------------------------------------- 一覧ページ

def parse_index(html: bytes, base_url: str = INDEX_URL) -> list[dict]:
    """一覧から月リンクを抽出。年月はリンク文言から取る（URL は使わない）。"""
    soup = BeautifulSoup(html, "lxml")
    seen: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        text = norm_text(a.get_text())
        m = MONTH_LINK_RE.search(text)
        if not m or "月報" not in text:
            continue
        url = urljoin(base_url, a["href"])
        if url in seen:
            continue
        seen[url] = {
            "year_month": f"{int(m.group(1)):04d}-{int(m.group(2)):02d}",
            "link_text": a.get_text(" ", strip=True),
            "page_url": url,
        }
    return sorted(seen.values(), key=lambda e: e["year_month"])


# ---------------------------------------------------------------- 月ページ

def parse_month_page(html: bytes, page_url: str) -> dict:
    """「各種データ」配下の部門見出し(h3)とリンク文言から CSV を特定する。"""
    soup = BeautifulSoup(html, "lxml")
    h2 = next((h for h in soup.find_all("h2") if norm_text(h.get_text()) == "各種データ"), None)
    if h2 is None:
        raise ValueError("「各種データ」見出しが見つからない")

    text = soup.get_text("\n", strip=True)
    note = re.search(r"補足\s*\n(.+)", text)
    released = re.search(r"リリース日\s*\n(.+)", text)

    warnings: list[str] = []
    headings: list[str] = []
    divisions: dict[str, dict] = {}
    csv_links = 0
    current: str | None = None

    for el in h2.find_all_next(["h2", "h3", "a"]):
        if el.name == "h2":
            break
        if el.name == "h3":
            label = norm_text(el.get_text())
            current = None
            for name, code in DIVISIONS.items():
                if name in label:
                    current = code
                    headings.append(name)
                    divisions.setdefault(code, {})
                    break
            else:
                warnings.append(f"未知の部門見出し: {el.get_text(strip=True)!r}")
            continue
        href = el.get("href") or ""
        if not href.lower().split("?")[0].endswith(".csv"):
            continue
        csv_links += 1
        label = norm_text(el.get_text())
        kind = next((k for t, k in TABLE_KINDS.items() if t in label), None)
        if kind is None:
            continue
        if current is None:
            warnings.append(f"部門見出しの外にある順位表リンク: {label}")
            continue
        slot = divisions[current]
        key = KIND_NAMES[kind]
        if key in slot:
            warnings.append(f"{current}: {key} のリンクが重複")
            continue
        url = urljoin(page_url, href)
        fname = urlparse(url).path.rsplit("/", 1)[-1]
        slot[key] = {"url": url, "link_text": el.get_text(" ", strip=True), "original_name": fname}
        m = FILENAME_RE.search(fname)
        if m is None:
            warnings.append(f"{current}/{key}: ファイル名が既知パターンに一致しない: {fname}")
        elif m.group(2).upper() != current or m.group(3) != kind:
            warnings.append(
                f"{current}/{key}: ファイル名の部門/表番号が見出し・文言と不一致: {fname}"
            )

    for code, slot in divisions.items():
        for key in KIND_NAMES.values():
            if key not in slot:
                warnings.append(f"{code}: {key} のリンクが無い")

    return {
        "released": released.group(1).strip() if released else None,
        "note": note.group(1).strip() if note else None,
        "division_headings": headings,
        "csv_links_total": csv_links,
        "divisions": divisions,
        "warnings": warnings,
    }


# ---------------------------------------------------------------- 取得

def month_dir(ym: str):
    return RAW_DIR / ym.replace("-", "")


def is_complete(ym: str) -> bool:
    mf = month_dir(ym) / "manifest.json"
    if not mf.exists():
        return False
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if data.get("status") != "ok":
        return False
    return all(
        (month_dir(ym) / t["saved"]).exists()
        for d in data["divisions"].values() for t in d.values()
    )


def fetch_month(f: Fetcher, entry: dict) -> dict:
    ym = entry["year_month"]
    page = f.get(entry["page_url"])
    info = parse_month_page(page.content, entry["page_url"])
    if not info["divisions"]:
        raise ValueError("部門が 1 つも検出できない")
    out = month_dir(ym)
    out.mkdir(parents=True, exist_ok=True)
    for code, slot in info["divisions"].items():
        for key, t in slot.items():
            kind = "11" if key == "items" else "12"
            resp = f.get(t["url"])
            body = resp.content
            if body.lstrip()[:1] == b"<":
                raise ValueError(f"CSV ではなく HTML が返った: {t['url']}")
            saved = f"{code}{kind}.csv"
            (out / saved).write_bytes(body)
            t["saved"] = saved
            t["bytes"] = len(body)
    manifest = {
        **entry,
        **info,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "ok",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


# ---------------------------------------------------------------- 検査・レポート

def _base(h: str) -> str:
    """列名から［…］の注記を除いた基本名。"""
    return re.sub(r"［.*?］$", "", h.strip())


def inspect_csv(path, kind: str) -> dict:
    text, enc = decode_csv(path.read_bytes())
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0] if rows else []
    expected = EXPECTED_HEADERS[kind]
    # 数量列の単位は部門で違うので、単位部分だけ除外して比較する。単位が無い月もある
    unit = None
    exact = list(header)
    for i, h in enumerate(header):
        um = re.fullmatch(r"数量合計［(.+)］", h)
        if um:
            unit = um.group(1)
            exact = header[:i] + ["数量合計［単位］"] + header[i + 1:]
            break
    rank_idx = 4 if kind == "11" else 3
    yms = set()
    cats: list[str] = []
    ranked: dict[str, int] = {}
    others: dict[str, int] = {}
    max_rank: dict[str, int] = {}
    cur = None
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        if r[0].strip():
            cur = r[0]
            if cur not in cats:
                cats.append(cur)
        if len(r) > 2 and r[1].strip() and r[2].strip():
            yms.add(f"{int(r[1]):04d}-{int(r[2]):02d}")
        if r[rank_idx].strip().isdigit():
            ranked[cur] = ranked.get(cur, 0) + 1
            max_rank[cur] = max(max_rank.get(cur, 0), int(r[rank_idx]))
        else:
            others[cur] = others.get(cur, 0) + 1
    return {
        "encoding": enc,
        "header_ok": [_base(h) for h in header] == [_base(h) for h in expected],
        "header_exact": exact == expected,
        "header": header,
        "unit": unit,
        "rows": max(len(rows) - 1, 0),
        "year_months": sorted(yms),
        "categories": cats,
        "ranked": ranked,
        "others": others,
        "max_rank": max_rank,
    }


def build_report(index: list[dict], failures: dict[str, str]) -> dict:
    listed = [e["year_month"] for e in index]
    fetched: list[str] = []
    encodings: dict[str, list[str]] = {}
    division_months: dict[str, list[str]] = {c: [] for c in DIVISIONS.values()}
    categories: dict[str, set] = {}
    units: dict[str, set] = {}
    exceptions: list[str] = []
    irregular_names: dict[str, list[str]] = {}
    for ym in listed:
        mf = month_dir(ym) / "manifest.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text(encoding="utf-8"))
        if m.get("status") != "ok":
            continue
        fetched.append(ym)
        if ym.replace("-", "") not in m["page_url"]:
            exceptions.append(f"{ym}: 月ページURLに年月が含まれない ({m['page_url'].rsplit('/', 1)[-1]})")
        for w in m["warnings"]:
            if "既知パターンに一致しない" in w:
                irregular_names.setdefault(ym, []).append(w.split(": ")[-1])
            else:
                exceptions.append(f"{ym}: {w}")
        for code, slot in m["divisions"].items():
            if "items" in slot or "origins" in slot:
                division_months[code].append(ym)
            for key, t in slot.items():
                kind = "11" if key == "items" else "12"
                p = month_dir(ym) / t["saved"]
                try:
                    r = inspect_csv(p, kind)
                except Exception as e:  # noqa: BLE001
                    exceptions.append(f"{ym} {code}{kind}: 読み込み失敗 {e}")
                    continue
                encodings.setdefault(r["encoding"], []).append(f"{ym}/{code}{kind}")
                tag = f"{ym} {code}{kind}"
                if not r["header_ok"]:
                    exceptions.append(f"{tag}: ヘッダー不一致 {r['header']}")
                elif not r["header_exact"]:
                    exceptions.append(f"{tag}: 列名の表記ゆれ（単位/［西暦］注記なし）{r['header']}")
                if r["unit"] is None:
                    exceptions.append(f"{tag}: 数量の単位が列名に無い")
                if r["year_months"] != [ym]:
                    exceptions.append(f"{tag}: CSV内の年月が一覧と不一致 {r['year_months']}")
                unknown = [c for c in r["categories"] if c not in EXPECTED_CATEGORIES[code]]
                if unknown:
                    exceptions.append(
                        f"{tag}: 想定外の大品目 {unknown}（想定: {sorted(EXPECTED_CATEGORIES[code])}）"
                    )
                for cat in r["categories"]:
                    n, o, mx = r["ranked"].get(cat, 0), r["others"].get(cat, 0), r["max_rank"].get(cat, 0)
                    if mx > 20:
                        exceptions.append(f"{tag}: {cat} の順位が20を超える（{mx}位まで・{n}行）")
                    elif n != 20:
                        exceptions.append(f"{tag}: {cat} の順位行が {n} 行（20行ではない）")
                    if o != 1:
                        exceptions.append(f"{tag}: {cat} の「その他」行が {o} 行")
                categories.setdefault(code, set()).update(r["categories"])
                units.setdefault(code, set()).add(r["unit"] or "不明(列名に無し)")

    # 月の連続性（一覧の最小〜最大の間で欠けている月）
    gaps: list[str] = []
    if listed:
        y, mo = map(int, listed[0].split("-"))
        ey, em = map(int, listed[-1].split("-"))
        while (y, mo) <= (ey, em):
            ym = f"{y:04d}-{mo:02d}"
            if ym not in listed:
                gaps.append(ym)
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)

    return {
        "generated": datetime.now().date().isoformat(),
        "index_links": len(listed),
        "fetched_months": len(fetched),
        "range": [listed[0], listed[-1]] if listed else None,
        "not_fetched": [ym for ym in listed if ym not in fetched],
        "gaps_in_index": gaps,
        "failures": failures,
        "division_months": {
            c: {"start": v[0] if v else None, "end": v[-1] if v else None, "count": len(v),
                "missing_in_range": [ym for ym in fetched if ym not in v]}
            for c, v in division_months.items()
        },
        "categories": {c: sorted(v) for c, v in categories.items()},
        "units": {c: sorted(v) for c, v in units.items()},
        "encodings": {k: len(v) for k, v in encodings.items()},
        "non_utf8_files": encodings.get("cp932", []),
        "irregular_filenames": irregular_names,
        "exceptions": exceptions,
    }


def format_report(r: dict) -> str:
    L = ["# 取得レポート", ""]
    L.append(f"- 生成日: {r['generated']}")
    L.append(f"- 一覧のリンク数: {r['index_links']}（{r['range'][0]} 〜 {r['range'][1]}）" if r["range"] else "- 一覧のリンク数: 0")
    L.append(f"- 取得済み月数: {r['fetched_months']}")
    L.append(f"- 未取得: {r['not_fetched'] or 'なし'}")
    L.append(f"- 一覧内の欠損月: {r['gaps_in_index'] or 'なし'}")
    L.append(f"- 取得失敗: {len(r['failures'])} 件")
    for ym, e in r["failures"].items():
        L.append(f"  - {ym}: {e}")
    L += ["", "## 部門ごとの開始月"]
    for c, d in r["division_months"].items():
        L.append(f"- {c}: {d['start']} 〜 {d['end']}（{d['count']} か月）")
    L += ["", "## 大品目（CSVから検出）"]
    for c, v in r["categories"].items():
        L.append(f"- {c}: {' / '.join(v)}")
    L += ["", "## 数量の単位（CSVの列名から検出）"]
    for c, v in r["units"].items():
        L.append(f"- {c}: {' / '.join(v)}")
    L += ["", "## 文字コード"]
    for k, n in r["encodings"].items():
        L.append(f"- {k}: {n} ファイル")
    if r["non_utf8_files"]:
        L.append(f"- utf-8 で読めなかった: {r['non_utf8_files']}")
    L += ["", f"## ファイル名が既知パターン(YYYYMM_?[RTV]NN)に一致しない月（{len(r['irregular_filenames'])} か月）"]
    L += [f"- {ym}: {', '.join(v)}" for ym, v in r["irregular_filenames"].items()] or ["- なし"]
    L += ["", f"## 例外・警告（{len(r['exceptions'])} 件）"]
    L += [f"- {e}" for e in r["exceptions"]] or ["- なし"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--force", action="store_true", help="取得済みの月も再取得")
    ap.add_argument("--months", help="YYYY-MM をカンマ区切りで指定（対象を絞る）")
    ap.add_argument("--interval", type=float, default=1.0, help="リクエスト間隔(秒)。1 未満は 1 に丸める")
    ap.add_argument("--report-only", action="store_true", help="取得せず保存済みデータからレポートだけ出す")
    args = ap.parse_args(argv)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    index_path = RAW_DIR / "index.json"
    fetcher = Fetcher(interval=args.interval)

    if args.report_only and index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = parse_index(fetcher.get(INDEX_URL).content)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"一覧のリンク数: {len(index)}", flush=True)

    targets = index
    if args.months:
        want = set(args.months.split(","))
        targets = [e for e in index if e["year_month"] in want]

    failures: dict[str, str] = {}
    if not args.report_only:
        todo = [e for e in targets if args.force or not is_complete(e["year_month"])]
        print(f"取得対象: {len(todo)} / {len(targets)} か月", flush=True)
        for e in todo:
            ym = e["year_month"]
            try:
                m = fetch_month(fetcher, e)
                print(f"  OK  {ym} {sorted(m['divisions'])} warnings={len(m['warnings'])}", flush=True)
            except Exception as ex:  # noqa: BLE001
                failures[ym] = f"{type(ex).__name__}: {ex}"
                print(f"  NG  {ym} {failures[ym]}", flush=True)

    report = build_report(index, failures)
    (RAW_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text = format_report(report)
    (RAW_DIR / "report.md").write_text(text, encoding="utf-8")
    print("\n" + text)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
