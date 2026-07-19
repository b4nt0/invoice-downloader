"""Command-line interface for AID."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from aid.orchestrator import run_from_path
from aid.setup.init_config import InitConfigError, init_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aid",
        description="Automated Invoice Downloader",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Create config.yml from the example template"
    )
    init_parser.add_argument(
        "-o",
        "--output",
        default="config.yml",
        help="Destination config path (default: config.yml)",
    )
    init_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite an existing config file",
    )

    run_parser = subparsers.add_parser(
        "run", help="Authenticate and download invoices for enabled services"
    )
    run_parser.add_argument(
        "-c",
        "--config",
        default="config.yml",
        help="Path to YAML config (default: config.yml)",
    )
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    try:
        path = init_config(args.output, force=args.force)
    except InitConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Wrote {path}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    result = asyncio.run(run_from_path(Path(args.config)))
    exit_code = 0
    for service_result in result.results:
        if service_result.ok:
            paths = ", ".join(str(path) for path in service_result.paths)
            print(f"{service_result.service}: ok ({paths})")
        else:
            exit_code = 1
            print(
                f"{service_result.service}: failed — {service_result.error}",
                file=sys.stderr,
            )
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "run":
        return _cmd_run(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
