#!/usr/bin/env python3
"""Single source of truth for the version number.

The default version lives in the VERSION file. For a build, this script decides the final version,
writes it to

  deskpresence/_build_version.py   read by the app      -> tray menu / About window
  version_info.txt                 PyInstaller version  -> Windows file properties of DeskPresence.exe

and prints it, so the GitHub release uses the very same string.

  python tools/set_version.py                          the default version (VERSION file)
  python tools/set_version.py 1.2.0                    an explicit version
  python tools/set_version.py --ci REF REF_NAME RUN    version of a GitHub Actions build:
                                                         tag vX.Y.Z   -> X.Y.Z
                                                         main branch  -> MAJOR.MINOR.RUN
                                                         other        -> MAJOR.MINOR.0-dev.RUN
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def default_version(root=ROOT):
    return (Path(root) / "VERSION").read_text(encoding="utf-8").strip()


def compute_version(ref, ref_name, run_number, default):
    major_minor = ".".join(default.split(".")[:2])
    if ref.startswith("refs/tags/v"):
        return ref_name[1:]
    if ref in ("refs/heads/main", "refs/heads/master"):
        return f"{major_minor}.{run_number}"
    return f"{major_minor}.0-dev.{run_number}"


def numeric_version(version):
    """'1.4.37' -> (1, 4, 37, 0);  '1.4.0-dev.12' -> (1, 4, 0, 12)  (Windows wants four numbers)."""
    nums = [int(n) for n in re.findall(r"\d+", version.split("-")[0])][:3]
    nums += [0] * (3 - len(nums))
    build = re.search(r"-[A-Za-z]+\.(\d+)", version)
    return (*nums, int(build.group(1)) if build else 0)


def version_info_text(version):
    nums = numeric_version(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Usef Farahmand'),
      StringStruct('FileDescription', 'DeskPresence'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'DeskPresence'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 Usef Farahmand'),
      StringStruct('OriginalFilename', 'DeskPresence.exe'),
      StringStruct('ProductName', 'DeskPresence'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write_files(version, root=ROOT):
    root = Path(root)
    (root / "deskpresence" / "_build_version.py").write_text(
        f'"""Written by tools/set_version.py at build time."""\nAPP_VERSION = "{version}"\n', encoding="utf-8")
    (root / "version_info.txt").write_text(version_info_text(version), encoding="utf-8")


def main(argv):
    if argv[:1] == ["--ci"]:
        ref, ref_name, run = argv[1:4]
        version = compute_version(ref, ref_name, run, default_version())
    elif argv:
        version = argv[0]
    else:
        version = default_version()
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[A-Za-z]+\.\d+)?", version):
        raise SystemExit(f"Invalid version: {version}")
    write_files(version)
    print(version)


if __name__ == "__main__":
    main(sys.argv[1:])
