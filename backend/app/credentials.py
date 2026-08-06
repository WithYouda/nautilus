from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("nautilus.credentials")

KEY_FILE_NAME = "master.key"
STORE_FILE_NAME = "secrets.enc"


class CredentialError(RuntimeError):
    """凭据存储的可预期错误，消息中不包含任何密钥内容。"""


def mask_secret(value: str | None) -> str:
    """把密钥压成可以安全出现在 API、日志和文档里的掩码。"""
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 8 else ""
    return f"****{tail}" if tail else "****"


class CredentialStore:
    """本地加密凭据存储。

    密钥永远不进入 SQLite、日志、Cookie、进度文档或对话内容，只落在
    ``NAUTILUS_DATA_DIR`` 下的受控目录里，目录 0700、文件 0600。
    加密使用 ``cryptography`` 的 Fernet（AES-128-CBC + HMAC-SHA256），
    不自制加密算法。

    威胁模型边界：本产品无账号无口令，主密钥只能与密文放在同一台机器上。
    因此本实现防的是"密钥明文散落进备份包、日志、grep 结果、误提交"，
    不防"已经能以同一个用户身份读文件的攻击者"。这是本地 MVP 的固有边界。
    """

    def __init__(self, credentials_dir: Path) -> None:
        self.credentials_dir = Path(credentials_dir)
        self.key_path = self.credentials_dir / KEY_FILE_NAME
        self.store_path = self.credentials_dir / STORE_FILE_NAME
        self._lock = threading.RLock()
        self._cache: dict[str, str] | None = None
        self._fernet: Fernet | None = None

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def set(self, name: str, secret: str) -> None:
        """保存或覆盖一条凭据。"""
        key = self._normalized(name)
        if not secret or not secret.strip():
            raise CredentialError("凭据内容不能为空")
        with self._lock:
            data = dict(self._load())
            data[key] = secret
            self._persist(data)

    def get(self, name: str) -> str | None:
        """读取明文凭据，仅供出站请求使用，调用方不得写日志。"""
        with self._lock:
            return self._load().get(self._normalized(name))

    def has(self, name: str) -> bool:
        with self._lock:
            return self._normalized(name) in self._load()

    def masked(self, name: str) -> str:
        """返回可安全外发的掩码，不泄露原始密钥。"""
        return mask_secret(self.get(name))

    def delete(self, name: str) -> bool:
        """删除一条凭据，返回是否真的删掉了。"""
        key = self._normalized(name)
        with self._lock:
            data = dict(self._load())
            if key not in data:
                return False
            data.pop(key)
            self._persist(data)
            return True

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._load())

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    @staticmethod
    def _normalized(name: str) -> str:
        key = (name or "").strip()
        if not key:
            raise CredentialError("凭据名称不能为空")
        return key

    def _ensure_dir(self) -> None:
        try:
            self.credentials_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise CredentialError("无法创建凭据目录") from error
        self._enforce_mode(self.credentials_dir, 0o700, directory=True)

    def _enforce_mode(self, path: Path, expected: int, *, directory: bool = False) -> None:
        """目录/文件权限过宽时收紧；收不紧就明确报错，不静默继续。"""
        try:
            metadata = path.lstat()
        except OSError as error:
            raise CredentialError(f"无法读取凭据路径：{path.name}") from error
        expected_kind = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode) or not expected_kind:
            raise CredentialError(f"凭据路径类型不安全：{path.name}")
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise CredentialError(f"凭据路径所有者不安全：{path.name}")
        current = stat.S_IMODE(metadata.st_mode)
        if current == expected:
            return
        try:
            os.chmod(path, expected)
        except OSError as error:
            raise CredentialError(
                f"凭据路径权限不安全且无法收紧：{path.name}"
            ) from error
        if stat.S_IMODE(path.lstat().st_mode) != expected:
            raise CredentialError(f"凭据路径权限不安全：{path.name}")
        logger.warning("已收紧凭据路径权限：%s（%o -> %o）", path.name, current, expected)

    def _load_fernet(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet
        self._ensure_dir()
        try:
            self.key_path.lstat()
        except FileNotFoundError:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                key_fd = os.open(self.key_path, flags, 0o600)
            except FileExistsError:
                # 另一个初始化者刚创建完成；后续按既有文件校验。
                pass
            except OSError as error:
                raise CredentialError("无法创建凭据主密钥文件") from error
            else:
                with os.fdopen(key_fd, "wb") as key_file:
                    key_file.write(Fernet.generate_key())
                    key_file.flush()
                    os.fsync(key_file.fileno())
                self._fsync_dir()
                logger.info("已生成本地凭据主密钥文件。")
        except OSError as error:
            raise CredentialError("无法检查凭据主密钥文件") from error
        self._enforce_mode(self.key_path, 0o600)
        try:
            raw = self.key_path.read_bytes().strip()
        except OSError as error:
            raise CredentialError("无法读取凭据主密钥文件") from error
        try:
            self._fernet = Fernet(raw)
        except (ValueError, TypeError) as error:
            raise CredentialError("凭据主密钥文件格式不正确") from error
        return self._fernet

    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        fernet = self._load_fernet()
        try:
            self.store_path.lstat()
        except FileNotFoundError:
            self._cache = {}
            return self._cache
        except OSError as error:
            raise CredentialError("无法检查凭据文件") from error
        self._enforce_mode(self.store_path, 0o600)
        try:
            blob = self.store_path.read_bytes()
        except OSError as error:
            raise CredentialError("无法读取凭据文件") from error
        if not blob.strip():
            raise CredentialError("凭据文件内容已损坏")
        try:
            plain = fernet.decrypt(blob)
        except InvalidToken as error:
            # 主密钥被替换或密文被篡改。绝不静默清空用户凭据。
            raise CredentialError("凭据文件无法解密，主密钥可能已更换或文件已损坏") from error
        try:
            parsed = json.loads(plain.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CredentialError("凭据文件内容已损坏") from error
        if not isinstance(parsed, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in parsed.items()
        ):
            raise CredentialError("凭据文件内容已损坏")
        self._cache = dict(parsed)
        return self._cache

    def _persist(self, data: dict[str, str]) -> None:
        fernet = self._load_fernet()
        blob = fernet.encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        self._ensure_dir()
        try:
            temp_fd, temp_name = tempfile.mkstemp(
                prefix=f".{STORE_FILE_NAME}.", suffix=".tmp", dir=self.credentials_dir
            )
        except OSError as error:
            raise CredentialError("无法创建凭据临时文件") from error
        temp_path = Path(temp_name)
        try:
            with os.fdopen(temp_fd, "wb") as temp_file:
                os.fchmod(temp_file.fileno(), 0o600)
                temp_file.write(blob)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.store_path)
            self._fsync_dir()
        except OSError as error:
            raise CredentialError("无法安全写入凭据文件") from error
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("无法清理凭据临时文件：%s", temp_path.name)
        self._enforce_mode(self.store_path, 0o600)
        self._cache = dict(data)

    def _fsync_dir(self) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            directory_fd = os.open(self.credentials_dir, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            raise CredentialError("无法同步凭据目录") from error
