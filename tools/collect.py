#!/usr/bin/env python3
"""Assemble an F-Droid working tree from the apps listed in apps.yml.

This is the step that takes binaries built somewhere else and decides they
belong in the index, so it is where the signing certificate is checked. An APK
whose signer does not match the pin in apps.yml never reaches the repo, and the
pin is also written into the metadata as AllowedAPKSigningKeys so that fdroid
enforces it independently of this script.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)


def signer_digest(apksigner: str, apk: Path) -> str:
    """The SHA-256 of the certificate an APK is signed with."""
    out = run([apksigner, "verify", "--print-certs", str(apk)]).stdout
    for line in out.splitlines():
        prefix = "Signer #1 certificate SHA-256 digest: "
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    raise SystemExit(f"could not read a signer certificate from {apk.name}")


def download(app: dict, into: Path) -> list[Path]:
    """Fetch an app's APKs from its GitHub release."""
    before = set(into.glob("*.apk"))
    cmd = ["gh", "release", "download"]
    if app["release"] != "latest":
        cmd.append(app["release"])
    cmd += ["--repo", app["repo"], "--pattern", "*.apk",
            "--dir", str(into), "--clobber"]
    try:
        run(cmd)
    except subprocess.CalledProcessError as e:
        # A missing nightly release is normal before the first nightly build;
        # anything already published stays in the index regardless.
        sys.stderr.write(f"warning: no release for {app['id']}: {e.stderr.strip()}\n")
        return []
    return sorted(set(into.glob("*.apk")) - before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path,
                    help="the F-Droid working tree to assemble into")
    ap.add_argument("--apksigner", default="apksigner")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args()

    apps = yaml.safe_load((args.root / "apps.yml").read_text())["apps"]
    repo_dir = args.work / "repo"
    meta_dir = args.work / "metadata"
    repo_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    failures = []
    for app in apps:
        app_id, pin = app["id"], (app.get("signer") or "").strip().lower()

        for apk in download(app, repo_dir):
            got = signer_digest(args.apksigner, apk).lower()
            if not pin:
                print(f"warning: {app_id} is not pinned; accepting signer {got}")
            elif got != pin:
                # Do not leave it lying in repo/ where the next run might
                # sweep it into the index.
                apk.unlink()
                failures.append(
                    f"{app_id}: {apk.name} is signed by {got}, not the pinned {pin}")
                continue
            print(f"accepted {apk.name} ({app_id})")

        src = args.root / "metadata" / f"{app_id}.yml"
        if not src.exists():
            failures.append(f"{app_id}: no metadata/{app_id}.yml")
            continue
        meta = yaml.safe_load(src.read_text()) or {}
        if pin:
            # fdroid rejects a wrongly-signed APK on its own account too.
            meta["AllowedAPKSigningKeys"] = pin
        (meta_dir / f"{app_id}.yml").write_text(
            yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))

    if failures:
        sys.stderr.write("\n".join(f"error: {f}" for f in failures) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
