#!/usr/bin/env python
"""Stage the bundled RawFileReader Python adapter into a target directory."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def copytree_replace(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy the vendored RawFileReader adapter into a target directory."
    )
    parser.add_argument(
        "--target",
        default=".",
        help="Directory that should receive the rawfilereader package and packaging files.",
    )
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    source_dir = skill_dir / "assets" / "rawfilereader-python"
    libs_dir = skill_dir / "assets" / "libs" / "Net8" / "Assemblies"
    target_dir = Path(args.target).resolve()

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Missing adapter asset directory: {source_dir}")
    if not libs_dir.is_dir():
        raise FileNotFoundError(f"Missing DLL asset directory: {libs_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    copytree_replace(source_dir / "rawfilereader", target_dir / "rawfilereader")

    for name in ("setup.py", "requirements.txt", "README.md"):
        src = source_dir / name
        if src.exists():
            shutil.copy2(src, target_dir / name)

    print(f"staged_package={target_dir / 'rawfilereader'}")
    print(f"RAWFILEREADER_LIBS={libs_dir}")
    print(f"pythonpath_hint={target_dir}")
    print(
        "powershell_env="
        f"$env:RAWFILEREADER_LIBS='{libs_dir}'; "
        f"$env:PYTHONPATH='{target_dir}'"
    )
    print(
        "posix_env="
        f"export RAWFILEREADER_LIBS='{libs_dir}'; "
        f"export PYTHONPATH='{target_dir}${{PYTHONPATH:+:$PYTHONPATH}}'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
