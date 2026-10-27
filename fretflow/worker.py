"""Command-line worker entrypoint for local jobs and future AWS Batch jobs."""

from __future__ import annotations

import argparse
import sys

from fretflow.config import Settings
from fretflow.runtime import create_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one FretFlow job")
    parser.add_argument("job_type", choices=("separation", "tab"))
    parser.add_argument("job_id")
    parser.add_argument("--owner-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        owner_id = args.owner_id or settings.owner_id
        pipeline = create_pipeline(settings)
        if args.job_type == "separation":
            pipeline.run_separation(owner_id, args.job_id)
        else:
            pipeline.run_tab(owner_id, args.job_id)
        return 0
    except Exception as error:
        print(f"FretFlow worker failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
