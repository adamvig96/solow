#!/usr/bin/env python3
"""
Download EU KLEMS INTANProd-LLEE data needed for Solow decomposition.

Default download set (all countries, from 1995):
- national accounts
- labour accounts
- capital accounts
- variable list (metadata)

Optional datasets can be enabled with CLI flags.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DOWNLOAD_PAGE = "https://euklems-intanprod-llee.luiss.it/download/"

CORE_MODULES = [
    "national_accounts",
    "labour_accounts",
    "capital_accounts",
    "variable_list",
]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download EU KLEMS files required for Solow decomposition."
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/euklems",
        help="Directory where files will be saved (default: %(default)s).",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "dta", "rds"],
        default="csv",
        help="File format for accounts modules (default: %(default)s).",
    )
    parser.add_argument(
        "--include-growth-basic",
        action="store_true",
        help="Also download growth accounts basic.",
    )
    parser.add_argument(
        "--include-growth-extended",
        action="store_true",
        help="Also download growth accounts extended.",
    )
    parser.add_argument(
        "--include-intangibles",
        action="store_true",
        help="Also download intangibles analytical dataset.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite files that already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve URLs and print planned downloads without writing files.",
    )
    return parser.parse_args()


def fetch_download_page() -> str:
    req = Request(
        DOWNLOAD_PAGE,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; euklems-solow-downloader/1.0)"
        },
    )
    with urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_dropbox_links(page_html: str) -> List[str]:
    href_pattern = re.compile(r'href\s*=\s*"([^"]+)"', flags=re.IGNORECASE)
    links = set()
    for match in href_pattern.finditer(page_html):
        link = html.unescape(match.group(1).strip())
        if "dropbox.com" in link:
            links.add(link)
    return sorted(links)


def classify_dataset(url: str) -> Optional[Tuple[str, str]]:
    parsed = urlsplit(url)
    filename = unquote(Path(parsed.path).name).strip().lower()
    if not filename or "." not in filename:
        return None

    stem, ext = filename.rsplit(".", 1)
    if stem.startswith("variable-list"):
        return "variable_list", ext
    if stem in {"national accounts", "national-accounts"}:
        return "national_accounts", ext
    if stem in {"labour accounts", "labour-accounts"}:
        return "labour_accounts", ext
    if stem in {"capital accounts", "capital-accounts"}:
        return "capital_accounts", ext
    if stem == "growth-accounts":
        return "growth_accounts_basic", ext
    if stem == "growth accounts":
        return "growth_accounts_extended", ext
    if stem == "intangibles analytical":
        return "intangibles_analytical", ext
    return None


def force_download_query(url: str) -> str:
    parsed = urlsplit(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["dl"] = "1"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment)
    )


def build_dataset_index(links: List[str]) -> Dict[str, Dict[str, str]]:
    index: Dict[str, Dict[str, str]] = {}
    for url in links:
        classified = classify_dataset(url)
        if not classified:
            continue
        module, fmt = classified
        index.setdefault(module, {})
        # Keep first discovered URL for deterministic behavior.
        index[module].setdefault(fmt, force_download_query(url))
    return index


def choose_modules(args: argparse.Namespace) -> List[str]:
    modules = list(CORE_MODULES)
    if args.include_growth_basic:
        modules.append("growth_accounts_basic")
    if args.include_growth_extended:
        modules.append("growth_accounts_extended")
    if args.include_intangibles:
        modules.append("intangibles_analytical")
    return modules


def expected_format(module: str, selected_format: str) -> str:
    if module == "variable_list":
        return "xlsx"
    return selected_format


def sanitize_filename(filename: str) -> str:
    name = re.sub(r"\s+", "_", filename.strip())
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def download_file(url: str, destination: Path) -> int:
    req = Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; euklems-solow-downloader/1.0)"}
    )
    with urlopen(req, timeout=120) as response, destination.open("wb") as output:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            total += len(chunk)
    return total


def main() -> int:
    args = parse_args()
    modules = choose_modules(args)

    try:
        page_html = fetch_download_page()
    except Exception as exc:
        print(f"ERROR: failed to load {DOWNLOAD_PAGE}: {exc}", file=sys.stderr)
        return 1

    links = extract_dropbox_links(page_html)
    index = build_dataset_index(links)

    missing = []
    for module in modules:
        fmt = expected_format(module, args.format)
        if module not in index or fmt not in index[module]:
            missing.append((module, fmt))

    if missing:
        print("ERROR: missing required resources on download page:", file=sys.stderr)
        for module, fmt in missing:
            print(f"  - {module}.{fmt}", file=sys.stderr)
        print("\nAvailable module/format pairs:", file=sys.stderr)
        for module in sorted(index):
            for fmt in sorted(index[module]):
                print(f"  - {module}.{fmt}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source_page": DOWNLOAD_PAGE,
        "downloaded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "selected_format": args.format,
        "modules": modules,
        "files": [],
    }

    for module in modules:
        fmt = expected_format(module, args.format)
        url = index[module][fmt]
        remote_name = unquote(Path(urlsplit(url).path).name).strip()
        if not remote_name:
            remote_name = f"{module}.{fmt}"
        local_name = sanitize_filename(remote_name)
        destination = output_dir / local_name

        if args.dry_run:
            print(f"[DRY RUN] {module}.{fmt} -> {url}")
            continue

        if destination.exists() and not args.overwrite:
            print(f"[SKIP] {destination} (exists)")
            manifest["files"].append(
                {
                    "module": module,
                    "format": fmt,
                    "url": url,
                    "path": str(destination),
                    "status": "skipped_exists",
                }
            )
            continue

        print(f"[DOWNLOAD] {module}.{fmt} -> {destination}")
        try:
            size = download_file(url, destination)
        except Exception as exc:
            print(f"ERROR: failed downloading {url}: {exc}", file=sys.stderr)
            return 1

        manifest["files"].append(
            {
                "module": module,
                "format": fmt,
                "url": url,
                "path": str(destination),
                "bytes": size,
                "status": "downloaded",
            }
        )

    if not args.dry_run:
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        print(f"[DONE] Manifest written to {manifest_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
