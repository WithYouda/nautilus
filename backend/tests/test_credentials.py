import json
import os
import stat

import pytest
from cryptography.fernet import Fernet

import app.credentials as credentials_module
from app.credentials import CredentialError, CredentialStore, mask_secret

# 测试用的假密钥，不是真实凭据。
FAKE_KEY = "sk-test-0123456789abcdef"


def test_save_read_overwrite_and_delete(tmp_path):
    store = CredentialStore(tmp_path / "credentials")

    assert store.get("provider:a") is None
    assert store.has("provider:a") is False

    store.set("provider:a", FAKE_KEY)
    assert store.get("provider:a") == FAKE_KEY
    assert store.has("provider:a") is True
    assert store.names() == ["provider:a"]

    store.set("provider:a", "sk-test-second-value")
    assert store.get("provider:a") == "sk-test-second-value"

    assert store.delete("provider:a") is True
    assert store.get("provider:a") is None
    assert store.delete("provider:a") is False


def test_secret_is_not_readable_from_the_store_file(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)

    blob = store.store_path.read_bytes()
    assert FAKE_KEY.encode("utf-8") not in blob
    assert b"provider:a" not in blob


def test_files_and_directory_use_strict_permissions(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)

    assert stat.S_IMODE(store.credentials_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.store_path.stat().st_mode) == 0o600
    # 原子写入的临时文件不允许残留。
    assert not list(store.credentials_dir.glob("*.tmp"))


def test_loose_permissions_are_tightened_on_next_read(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)

    os.chmod(store.credentials_dir, 0o755)
    os.chmod(store.key_path, 0o644)
    os.chmod(store.store_path, 0o666)

    reopened = CredentialStore(tmp_path / "credentials")
    assert reopened.get("provider:a") == FAKE_KEY
    assert stat.S_IMODE(reopened.credentials_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(reopened.key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(reopened.store_path.stat().st_mode) == 0o600


def test_wrong_master_key_reports_error_without_wiping_secrets(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)
    original = store.store_path.read_bytes()

    store.key_path.write_bytes(Fernet.generate_key())
    os.chmod(store.key_path, 0o600)

    broken = CredentialStore(tmp_path / "credentials")
    with pytest.raises(CredentialError) as error:
        broken.get("provider:a")
    assert "无法解密" in str(error.value)
    # 绝不静默清空用户凭据。
    assert store.store_path.read_bytes() == original


def test_corrupted_key_and_payload_raise_credential_error(tmp_path):
    bad_key_dir = tmp_path / "bad-key"
    bad_key_dir.mkdir(parents=True)
    os.chmod(bad_key_dir, 0o700)
    (bad_key_dir / "master.key").write_bytes(b"not-a-fernet-key")
    os.chmod(bad_key_dir / "master.key", 0o600)
    with pytest.raises(CredentialError) as key_error:
        CredentialStore(bad_key_dir).get("provider:a")
    assert "主密钥" in str(key_error.value)

    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)
    encrypted_non_json = store._load_fernet().encrypt(b"[1, 2, 3]")
    store.store_path.write_bytes(encrypted_non_json)
    os.chmod(store.store_path, 0o600)
    with pytest.raises(CredentialError) as payload_error:
        CredentialStore(tmp_path / "credentials").get("provider:a")
    assert "损坏" in str(payload_error.value)


def test_empty_names_and_values_are_rejected(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    with pytest.raises(CredentialError):
        store.set("   ", FAKE_KEY)
    with pytest.raises(CredentialError):
        store.set("provider:a", "   ")
    with pytest.raises(CredentialError):
        store.get("")


def test_existing_store_file_is_reused_not_regenerated(tmp_path):
    first = CredentialStore(tmp_path / "credentials")
    first.set("provider:a", FAKE_KEY)
    key_material = first.key_path.read_bytes()

    second = CredentialStore(tmp_path / "credentials")
    second.set("provider:b", "sk-test-other")

    assert second.key_path.read_bytes() == key_material
    assert second.names() == ["provider:a", "provider:b"]
    assert CredentialStore(tmp_path / "credentials").get("provider:a") == FAKE_KEY


def test_empty_store_file_is_reported_as_corruption(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)
    store.store_path.write_bytes(b"")
    os.chmod(store.store_path, 0o600)

    with pytest.raises(CredentialError, match="损坏"):
        CredentialStore(tmp_path / "credentials").names()


def test_failed_atomic_replace_does_not_mutate_in_memory_or_disk_state(tmp_path, monkeypatch):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)
    original_blob = store.store_path.read_bytes()

    def fail_replace(_source, _target):
        raise PermissionError("read-only test")

    monkeypatch.setattr(credentials_module.os, "replace", fail_replace)
    with pytest.raises(CredentialError, match="安全写入") as error:
        store.set("provider:a", "sk-test-new-value")
    assert "sk-test-new-value" not in str(error.value)
    assert store.get("provider:a") == FAKE_KEY
    assert store.store_path.read_bytes() == original_blob
    assert not list(store.credentials_dir.glob("*.tmp"))


def test_insecure_symlink_paths_are_rejected(tmp_path):
    real_dir = tmp_path / "real-credentials"
    real_store = CredentialStore(real_dir)
    real_store.set("provider:a", FAKE_KEY)

    linked_dir = tmp_path / "credentials-link"
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(CredentialError, match="类型不安全"):
        CredentialStore(linked_dir).get("provider:a")

    key_target = tmp_path / "key-target"
    key_target.write_bytes(real_store.key_path.read_bytes())
    os.chmod(key_target, 0o600)
    real_store.key_path.unlink()
    real_store.key_path.symlink_to(key_target)
    with pytest.raises(CredentialError, match="类型不安全"):
        CredentialStore(real_dir).get("provider:a")


def test_unable_to_tighten_permissions_is_an_error(tmp_path, monkeypatch):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)
    os.chmod(store.store_path, 0o644)
    original_chmod = credentials_module.os.chmod

    def deny_store_chmod(path, mode):
        if os.fspath(path) == os.fspath(store.store_path):
            raise PermissionError("permission test")
        return original_chmod(path, mode)

    monkeypatch.setattr(credentials_module.os, "chmod", deny_store_chmod)
    with pytest.raises(CredentialError, match="权限") as error:
        CredentialStore(tmp_path / "credentials").get("provider:a")
    assert FAKE_KEY not in str(error.value)


def test_mask_secret_never_reveals_the_full_value():
    assert mask_secret(FAKE_KEY) == "****cdef"
    assert mask_secret("short") == "****"
    assert mask_secret("") == ""
    assert FAKE_KEY not in mask_secret(FAKE_KEY)


def test_store_payload_is_valid_json_after_decrypt(tmp_path):
    store = CredentialStore(tmp_path / "credentials")
    store.set("provider:a", FAKE_KEY)
    decrypted = store._load_fernet().decrypt(store.store_path.read_bytes())
    assert json.loads(decrypted) == {"provider:a": FAKE_KEY}
