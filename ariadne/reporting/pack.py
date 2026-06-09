"""Evidence pack — zip artifacts and encrypt with explicit pubkey (age-preferred).

Never uses host ~/.gnupg or ambient GPG default keys. Operator must pass --pubkey.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


class PackError(RuntimeError):
    pass


def zip_artifacts(artifacts_dir: Path, dest_zip: Path) -> Path:
    artifacts_dir = artifacts_dir.resolve()
    if not artifacts_dir.is_dir():
        raise PackError(f"Not a directory: {artifacts_dir}")
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(artifacts_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(artifacts_dir).as_posix())
    return dest_zip


def encrypt_with_age(plaintext: Path, pubkey_file: Path, output: Path) -> Path:
    """Encrypt using age CLI. No host keyring — recipient file only."""
    pubkey = pubkey_file.read_text(encoding="utf-8").strip()
    if not pubkey:
        raise PackError(f"Empty pubkey file: {pubkey_file}")

    with tempfile.NamedTemporaryFile("w", suffix=".age.pub", delete=False) as tmp:
        tmp.write(pubkey + "\n")
        recip = Path(tmp.name)
    try:
        age_bin = shutil.which("age")
        if not age_bin:
            raise PackError(
                "age CLI not found on PATH. Install age (https://age-encryption.org) "
                "or use a GPG public key file (.asc) with --pubkey. "
                "Refusing ambient GPG keyring fallback."
            )
        proc = subprocess.run(
            [age_bin, "-e", "-R", str(recip), "-o", str(output), str(plaintext)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise PackError(f"age encrypt failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return output
    finally:
        recip.unlink(missing_ok=True)


def encrypt_with_gpg_pubkey_file(plaintext: Path, pubkey_file: Path, output: Path) -> Path:
    """
    Optional GPG path using ONLY an explicit public key file — never ~/.gnupg default key.
    Imports into a temporary GNUPGHOME and encrypts with --batch --trust-model always.
    """
    gpg = shutil.which("gpg")
    if not gpg:
        raise PackError("gpg not found; prefer age with --pubkey recipient.age")

    with tempfile.TemporaryDirectory(prefix="ariadne-gnupg-") as td:
        env = {**os.environ, "GNUPGHOME": td, "HOME": td}
        subprocess.run(
            [gpg, "--batch", "--import", str(pubkey_file)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        listing = subprocess.run(
            [gpg, "--batch", "--list-keys", "--with-colons"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        fpr = None
        for line in listing.stdout.splitlines():
            if line.startswith("fpr:"):
                fpr = line.split(":")[9]
                break
        if not fpr:
            raise PackError("Could not read fingerprint from imported pubkey")
        subprocess.run(
            [
                gpg,
                "--batch",
                "--yes",
                "--trust-model",
                "always",
                "--encrypt",
                "--recipient",
                fpr,
                "--output",
                str(output),
                str(plaintext),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    return output


def _looks_like_age_pubkey(text: str, pubkey: Path) -> bool:
    stripped = text.strip()
    return (
        stripped.startswith("age1")
        or "age1" in stripped.split()[0]
        or pubkey.suffix in {".age", ".pub"}
    ) and "BEGIN PGP" not in text


def pack_artifacts(
    artifacts_dir: Path,
    *,
    encrypt: bool = False,
    pubkey: Path | None = None,
    output: Path | None = None,
    prefer_age: bool = True,
) -> Path:
    artifacts_dir = Path(artifacts_dir)
    out_dir = artifacts_dir.parent
    zip_path = out_dir / f"{artifacts_dir.name}.zip"
    zip_artifacts(artifacts_dir, zip_path)
    if not encrypt:
        return zip_path
    if pubkey is None:
        raise PackError("--encrypt requires --pubkey <recipient key file>")
    pubkey = Path(pubkey)
    if not pubkey.is_file():
        raise PackError(f"Pubkey not found: {pubkey}")

    text = pubkey.read_text(encoding="utf-8", errors="ignore")
    if output is None:
        if "BEGIN PGP PUBLIC KEY" in text:
            output = out_dir / f"{artifacts_dir.name}.zip.gpg"
        else:
            output = out_dir / f"{artifacts_dir.name}.zip.age"

    if prefer_age and _looks_like_age_pubkey(text, pubkey):
        return encrypt_with_age(zip_path, pubkey, output)

    if "BEGIN PGP PUBLIC KEY" in text or pubkey.suffix in {".asc", ".gpg", ".pgp"}:
        gpg_out = output if str(output).endswith(".gpg") else Path(str(output) + ".gpg")
        return encrypt_with_gpg_pubkey_file(zip_path, pubkey, gpg_out)

    return encrypt_with_age(zip_path, pubkey, output)
