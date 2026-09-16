"""命令行运行财经经济时评采集节点。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.collectors import EastMoneyFinanceCollector, FinanceCollectionError  # noqa: E402


def _load_seen(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(item) for item in value} if isinstance(value, list) else set()


def _save_seen(path: Path, urls: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(sorted(urls), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取东方财富财经网友点击榜文章")
    parser.add_argument("--limit", type=int, default=10, help="文章数量，默认 10")
    parser.add_argument("--output", type=Path, help="可选 JSON 输出文件")
    parser.add_argument("--seen-file", type=Path, help="可选持久化去重 URL 文件")
    args = parser.parse_args()

    seen = _load_seen(args.seen_file)
    try:
        articles = EastMoneyFinanceCollector().collect(limit=args.limit, seen_urls=seen)
    except (FinanceCollectionError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    output = json.dumps(articles, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)
    if args.seen_file:
        seen.update(article["url"] for article in articles)
        _save_seen(args.seen_file, seen)
    if args.output:
        print(json.dumps({"success": True, "count": len(articles), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
