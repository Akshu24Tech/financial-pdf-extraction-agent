"""CLI entrypoint for finagent.

Usage:
    finagent run test_pdfs/TCS_2024-2025.pdf
    finagent benchmark
    finagent golden [filter]
    finagent build-single [--check]
"""

import argparse
import sys
from pathlib import Path

from .pipeline import run as run_pipeline


def main():
    parser = argparse.ArgumentParser(
        prog="finagent",
        description="Financial PDF Extraction Agent — Accurate extraction through verification.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Run extraction on a single PDF file")
    run_parser.add_argument("pdf", help="Path to company annual report PDF")
    run_parser.add_argument("-o", "--output", help="Optional output Excel path")

    # Subcommand: benchmark
    subparsers.add_parser("benchmark", help="Run benchmark scorecard across all test PDFs")

    # Subcommand: golden
    golden_parser = subparsers.add_parser("golden", help="Run golden ground-truth check suite")
    golden_parser.add_argument(
        "filter", nargs="?", default="", help="Optional substring to filter PDFs"
    )

    # Subcommand: build-single
    build_parser = subparsers.add_parser(
        "build-single", help="Bundle package into finagent_single.py"
    )
    build_parser.add_argument(
        "--check", action="store_true", help="Check if finagent_single.py is up-to-date"
    )

    args = parser.parse_args()

    if not args.command or args.command == "run":
        if hasattr(args, "pdf") and args.pdf:
            run_pipeline(args.pdf, args.output)
        elif len(sys.argv) > 1 and Path(sys.argv[1]).exists():
            run_pipeline(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
        else:
            parser.print_help()
    elif args.command == "benchmark":
        import benchmark

        _ = benchmark

        # benchmark script automatically executes
    elif args.command == "golden":
        import golden_check

        if args.filter:
            sys.argv = [sys.argv[0], args.filter]
        golden_check.main()
    elif args.command == "build-single":
        from . import bundler

        sys.argv = [sys.argv[0]] + (["--check"] if args.check else [])
        bundler.main()


if __name__ == "__main__":
    main()
