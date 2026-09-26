"""Owner-scoped search configuration and explicit, bounded outbound searches."""
from __future__ import annotations

import copy
import json
import re
import threading
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .credentials import CredentialStore, mask_secret
from .search_adapters import SearchError, search, scrape
from .search_catalog import SEARCH_CATALOG


NATIVE_KINDS = {"openai_responses", "google", "anthropic"}


class SearchConflict(SearchError):
    pass


@dataclass
class SearchRun:
    selection: dict
    common: dict
    service: dict | None = None

    def initial_trace(self):
        mode = self.selection["mode"]
        return {"mode": mode, "status": "off" if mode == "off" else "queued",
                "service_name": self.service["name"] if self.service else None,
                "items": []}


def _integer(value, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SearchError("搜索设置中的数值超出允许范围", "invalid_settings")
    return value


class SearchService:
    """Settings use the existing atomic encrypted store; no new database or migration.

    All secrets and script configuration stay in the encrypted store. Public
    representations omit credentials. A run owns a deep copy so later edits or
    key rotation cannot silently change its service.
    """
    def __init__(self, credentials: CredentialStore, transport=None):
        self.credentials = credentials
        self.transport = transport
        self._lock = threading.RLock()
        self._key_positions = {}

    @staticmethod
    def catalog():
        return copy.deepcopy(SEARCH_CATALOG)

    @staticmethod
    def _catalog(kind):
        item = next((item for item in SEARCH_CATALOG if item["kind"] == kind), None)
        if item is None:
            raise SearchError("搜索服务类型不支持", "unsupported_service")
        return item

    def _read(self, owner):
        raw = self.credentials.get(f"search-settings:{owner}")
        if raw:
            try:
                value = json.loads(raw)
                if not isinstance(value, dict) or not isinstance(value.get("services"), list):
                    raise ValueError()
                return value
            except (ValueError, TypeError):
                raise SearchError("已保存的搜索设置无法读取", "settings_corrupt") from None
        service_id = str(uuid5(NAMESPACE_URL, f"nautilus-search:{owner}:bing"))
        return {"revision": 0, "services": [{"id": service_id, "kind": "bing", "name": "Bing",
                 "options": {}, "secrets": {}}], "selected_service_id": service_id,
                "result_size": 10, "timeout_seconds": 30, "max_requests": 3}

    def _public(self, settings):
        value = copy.deepcopy(settings)
        for service in value["services"]:
            secrets = service.pop("secrets", {})
            service["has_secrets"] = {key: bool(secret) for key, secret in secrets.items()}
            service["masked_secrets"] = {key: mask_secret(secret) for key, secret in secrets.items()}
        return value

    def get(self, owner):
        with self._lock:
            return self._public(self._read(owner))

    def _service(self, incoming, existing=None):
        if not isinstance(incoming, dict):
            raise SearchError("搜索服务配置格式不正确", "invalid_settings")
        service_id = incoming.get("id")
        if not isinstance(service_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", service_id):
            raise SearchError("搜索服务标识不正确", "invalid_settings")
        catalog = self._catalog(incoming.get("kind"))
        if existing and existing["kind"] != catalog["kind"]:
            raise SearchError("已有搜索服务不能更换类型，请添加新实例", "invalid_settings")
        name = incoming.get("name") or catalog["label"]
        if not isinstance(name, str) or len(name) > 80:
            raise SearchError("搜索服务名称过长", "invalid_settings")
        raw_options = incoming.get("options", {})
        updates = incoming.get("secret_updates", {})
        if not isinstance(raw_options, dict) or not isinstance(updates, dict):
            raise SearchError("搜索参数格式不正确", "invalid_settings")
        fields = {field["key"]: field for field in catalog["fields"]}
        secret_keys = {key for key, field in fields.items() if field["type"] == "secret"}
        if set(raw_options) - (set(fields) - secret_keys) or set(updates) - secret_keys:
            raise SearchError("搜索参数包含未知字段或未分离的密钥", "invalid_settings")
        options = {}
        for key, field in fields.items():
            if key in secret_keys:
                continue
            value = raw_options.get(key, field.get("default"))
            if field["type"] == "number":
                if value is not None and value != "":
                    value = _integer(value, field.get("min", 1), field.get("max", 1_000_000))
                else:
                    value = None
            elif field["type"] == "boolean":
                if not isinstance(value, bool):
                    raise SearchError("开关参数格式不正确", "invalid_settings")
            else:
                if not isinstance(value, str) or len(value) > (65536 if field["type"] == "textarea" else 2000):
                    raise SearchError("搜索参数格式或长度不正确", "invalid_settings")
                if field.get("options") and value not in {option["value"] for option in field["options"]}:
                    raise SearchError("搜索选项不支持", "invalid_settings")
            options[key] = value
        secrets = copy.deepcopy(existing.get("secrets", {})) if existing else {}
        for key, value in updates.items():
            if value is None:
                secrets.pop(key, None)
            elif not isinstance(value, str) or len(value) > 16000:
                raise SearchError("搜索凭据格式或长度不正确", "invalid_settings")
            elif value.strip():
                secrets[key] = value.strip()
        return {"id": service_id, "kind": catalog["kind"], "name": name.strip() or catalog["label"],
                "options": options, "secrets": secrets}

    def save(self, owner, payload):
        with self._lock:
            current = self._read(owner)
            if payload.get("revision") != current["revision"]:
                raise SearchConflict("搜索设置已被其他页面修改，请重新载入后再保存", "settings_conflict")
            incoming = payload.get("services")
            if not isinstance(incoming, list) or len(incoming) > 50:
                raise SearchError("最多配置50个搜索服务实例", "invalid_settings")
            old = {item["id"]: item for item in current["services"]}
            services = [self._service(item, old.get(item.get("id"))) if isinstance(item, dict)
                        else self._service(item) for item in incoming]
            ids = [item["id"] for item in services]
            if len(ids) != len(set(ids)):
                raise SearchError("搜索服务标识重复", "invalid_settings")
            selected = payload.get("selected_service_id")
            if selected is not None and selected not in ids:
                raise SearchError("所选搜索服务已不存在，请明确重新选择", "service_unavailable")
            saved = {"revision": current["revision"] + 1, "services": services,
                     "selected_service_id": selected,
                     "result_size": _integer(payload.get("result_size", 10), 1, 50),
                     "timeout_seconds": _integer(payload.get("timeout_seconds", 30), 5, 120),
                     "max_requests": _integer(payload.get("max_requests", 3), 1, 5)}
            self.credentials.set(f"search-settings:{owner}", json.dumps(saved, ensure_ascii=False))
            return self._public(saved)

    def _runtime_options(self, service):
        options = {**service["options"], **service.get("secrets", {})}
        # Multiple API keys are rotated once at the run boundary, never retried
        # against another key or vendor after an ambiguous upstream response.
        key = options.get("api_key")
        if key:
            keys = [part.strip() for part in re.split(r"[,\n]", key) if part.strip()]
            if keys:
                with self._lock:
                    position = self._key_positions.get(service["id"], 0)
                    options["api_key"] = keys[position % len(keys)]
                    self._key_positions[service["id"]] = position + 1
        return options

    def prepare(self, owner, selection, provider_kind="openai_compatible"):
        selected = copy.deepcopy(selection or {"mode": "off"})
        if not isinstance(selected, dict) or set(selected) - {"mode", "service_id", "query", "parameters"}:
            raise SearchError("搜索选择包含未知字段", "invalid_settings")
        mode = selected.get("mode", "off")
        if mode not in {"off", "external", "native"}:
            raise SearchError("搜索模式不支持", "invalid_settings")
        selected["mode"] = mode
        query = selected.get("query")
        if query is not None and (not isinstance(query, str) or len(query) > 2000):
            raise SearchError("搜索词过长", "invalid_query")
        if not isinstance(selected.get("parameters", {}), dict):
            raise SearchError("检索参数格式不正确", "invalid_settings")
        if len(json.dumps(selected, ensure_ascii=False)) > 20000:
            raise SearchError("检索参数过长", "invalid_settings")
        if mode == "native" and provider_kind not in NATIVE_KINDS:
            raise SearchError("当前提供方协议没有接入模型内置搜索，请选择外部搜索服务", "native_unsupported")
        with self._lock:
            settings = self._read(owner)
            common = {key: settings[key] for key in ("result_size", "timeout_seconds", "max_requests")}
            service = None
            if mode == "external":
                service_id = selected.get("service_id") or settings.get("selected_service_id")
                service = next((copy.deepcopy(item) for item in settings["services"] if item["id"] == service_id), None)
                if service is None:
                    raise SearchError("所选搜索服务不存在，请重新选择；不会自动更换服务", "service_unavailable")
                self._validate_parameters(self._catalog(service["kind"])["search_parameters"], selected.get("parameters", {}))
                selected["service_id"] = service_id
                service["options"] = self._runtime_options(service)
                service.pop("secrets", None)
            return SearchRun(selected, common, service)

    @staticmethod
    def _validate_parameters(schema, values):
        properties = (schema or {}).get("properties", {})
        if not isinstance(values, dict) or set(values) - set(properties):
            raise SearchError("检索参数包含未知字段", "invalid_settings")

        def check(rule, value):
            kind = rule.get("type")
            valid = ((kind == "string" and isinstance(value, str) and len(value) <= 2000)
                     or (kind == "integer" and type(value) is int)
                     or (kind == "boolean" and type(value) is bool)
                     or (kind == "array" and isinstance(value, list) and len(value) <= 50))
            if not valid or ("enum" in rule and value not in rule["enum"]):
                raise SearchError("检索参数类型或选项不正确", "invalid_settings")
            if kind == "integer" and not rule.get("minimum", -1_000_000) <= value <= rule.get("maximum", 1_000_000):
                raise SearchError("检索参数超出允许范围", "invalid_settings")
            if kind == "array":
                for item in value:
                    check(rule["items"], item)

        for key, value in values.items():
            check(properties[key], value)

    async def invoke(self, run: SearchRun, params: dict, *, fetch=False):
        if run.service is None or run.selection["mode"] != "external":
            raise SearchError("尚未选择外部搜索服务", "service_unavailable")
        if run.service["kind"] == "custom_js":
            from .search_scripts import execute_script
            return await execute_script(run.service["options"], params, run.common, fetch=fetch)
        method = scrape if fetch else search
        return await method(run.service["kind"], params, run.common, run.service["options"], transport=self.transport)

    async def test(self, owner, payload, *, fetch=False):
        with self._lock:
            current = self._read(owner)
            incoming = payload.get("service")
            if not isinstance(incoming, dict):
                raise SearchError("请选择要测试的服务", "invalid_settings")
            existing = next((item for item in current["services"] if item["id"] == incoming.get("id")), None)
            service = self._service(incoming, existing)
            service["options"] = self._runtime_options(service)
            service.pop("secrets", None)
            run = SearchRun({"mode": "external"}, {key: current[key] for key in ("result_size", "timeout_seconds", "max_requests")}, service)
        params = copy.deepcopy(payload.get("parameters") or {})
        if not isinstance(params, dict):
            raise SearchError("检索参数格式不正确", "invalid_settings")
        catalog = self._catalog(service["kind"])
        self._validate_parameters(catalog["scrape_parameters" if fetch else "search_parameters"], params)
        if fetch:
            urls = payload.get("urls")
            if not isinstance(urls, list) or not urls or not isinstance(urls[0], str):
                raise SearchError("请填写网页地址", "invalid_query")
            params.update(url=urls[0], urls=urls[:5])
        else:
            query = payload.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 2000:
                raise SearchError("请填写不超过2000字的搜索词", "invalid_query")
            params["query"] = query.strip()
        return await self.invoke(run, params, fetch=fetch)
