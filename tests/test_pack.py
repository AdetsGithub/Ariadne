"""Evidence pack — zip and encrypt without GPG keyring."""

from pathlib import Path

import pytest

from ariadne.reporting.pack import PackError, pack_artifacts, zip_artifacts


def test_zip_artifacts(tmp_path: Path):
    art = tmp_path / "ENG-001"
    art.mkdir()
    (art / "PageItem.ndjson").write_text('{"url":"x"}\n', encoding="utf-8")
    (art / "subdir").mkdir()
    (art / "subdir" / "note.txt").write_text("ok", encoding="utf-8")
    dest = tmp_path / "ENG-001.zip"
    zip_artifacts(art, dest)
    assert dest.is_file()
    assert dest.stat().st_size > 0


def test_pack_without_encrypt(tmp_path: Path):
    art = tmp_path / "ENG-002"
    art.mkdir()
    (art / "a.txt").write_text("hi", encoding="utf-8")
    out = pack_artifacts(art, encrypt=False)
    assert out.name == "ENG-002.zip"
    assert out.is_file()


def test_encrypt_requires_pubkey(tmp_path: Path):
    art = tmp_path / "ENG-003"
    art.mkdir()
    (art / "a.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(PackError, match="--pubkey"):
        pack_artifacts(art, encrypt=True, pubkey=None)


def test_encrypt_missing_pubkey_file(tmp_path: Path):
    art = tmp_path / "ENG-004"
    art.mkdir()
    (art / "a.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(PackError, match="not found"):
        pack_artifacts(art, encrypt=True, pubkey=tmp_path / "missing.age")


def test_age_encrypt_or_clear_error(tmp_path: Path):
    """If age is installed, encrypt succeeds; otherwise PackError mentions age — never keyring."""
    art = tmp_path / "ENG-005"
    art.mkdir()
    (art / "a.txt").write_text("secret", encoding="utf-8")
    # Fake age1 pubkey format (may fail age CLI validation — still must not touch ~/.gnupg)
    pub = tmp_path / "recipient.age"
    pub.write_text(
        "age1ql3z7hjy54pw3hyww5ayyfg7zqfdcjre22q23gmdz88yfqklc0msp0zqea\n",
        encoding="utf-8",
    )
    try:
        out = pack_artifacts(art, encrypt=True, pubkey=pub)
        assert out.suffix == ".age" or str(out).endswith(".zip.age")
        assert out.is_file()
    except PackError as exc:
        msg = str(exc).lower()
        assert "gnupg" not in msg or "refusing" in msg or "age" in msg
        assert "pinentry" not in msg
