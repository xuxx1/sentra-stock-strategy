"""命令行运行股吧热门话题采集节点。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.collectors import EastMoneyGubaCollector, GubaCollectionError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取东方财富股吧热门话题")
    parser.add_argument("--pages", type=int, default=1, help="页数，默认 1，最多 20")
    parser.add_argument("--page-size", type=int, default=50, help="每页数量，默认 50")
    parser.add_argument("--output", type=Path, help="可选 JSON 输出文件；不传则输出到终端")
    args = parser.parse_args()

    collector = EastMoneyGubaCollector()
    try:
        topics = collector.collect(pages=args.pages, page_size=args.page_size)
    except (GubaCollectionError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    output = json.dumps(topics, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(json.dumps({"success": True, "count": len(topics), "output": str(args.output)}, ensure_ascii=False))
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
