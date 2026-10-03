"""Owner-scoped learning defaults stored alongside local encrypted settings."""
from __future__ import annotations

import copy
import json
import threading

from .credentials import CredentialStore
from .search_adapters import SearchError
from .search_service import SearchService


class PreferencesError(ValueError):
    pass


class PreferencesService:
    def __init__(self, credentials: CredentialStore, search: SearchService):
        self.credentials = credentials
        self.search = search
        self._lock = threading.RLock()

    def get(self, owner: str) -> dict:
        with self._lock:
            raw = self.credentials.get(f"learning-preferences:{owner}")
            if raw is None:
                return {"conflict_policy": "ask", "search": {"mode": "off"}, "teaching_mode": "stepwise"}
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                return self._validate(owner, value, verify_service=False)
            except (ValueError, TypeError, SearchError):
                raise PreferencesError("已保存的学习设置无法读取") from None

    def save(self, owner: str, payload: dict) -> dict:
        with self._lock:
            if isinstance(payload, dict) and 'teaching_mode' not in payload:
                payload = {**payload, 'teaching_mode': self.get(owner)['teaching_mode']}
            value = self._validate(owner, payload)
            self.credentials.set(f"learning-preferences:{owner}", json.dumps(value, ensure_ascii=False))
            return copy.deepcopy(value)

    def _validate(self, owner: str, payload: dict, *, verify_service: bool = True) -> dict:
        if (not isinstance(payload, dict) or not {'conflict_policy', 'search'} <= set(payload)
                or not set(payload) <= {'conflict_policy', 'search', 'teaching_mode'}):
            raise PreferencesError("学习设置格式不正确")
        teaching_mode = payload.get('teaching_mode', 'stepwise')
        if teaching_mode not in ('stepwise', 'socratic', 'feynman', 'practice_first'):
            raise PreferencesError("默认学习方式不支持")
        policy = payload["conflict_policy"]
        if policy not in ("ask", "balanced", "materials"):
            raise PreferencesError("资料冲突处理方式不支持")
        selection = payload["search"]
        if not isinstance(selection, dict) or not set(selection) <= {"mode", "service_id", "parameters"}:
            raise PreferencesError("联网默认设置格式不正确")
        mode = selection.get("mode")
        if mode not in ("off", "external", "native"):
            raise PreferencesError("联网模式不支持")
        if mode != "external" and set(selection) != {"mode"}:
            raise PreferencesError("当前联网模式不接受服务参数")
        saved = {"mode": mode}
        if mode == "external":
            service_id = selection.get("service_id")
            if not isinstance(service_id, str) or not service_id:
                raise PreferencesError("请选择外部搜索服务")
            settings = self.search.get(owner)
            service = next((row for row in settings["services"] if row["id"] == service_id), None)
            if service is None and verify_service:
                raise PreferencesError("所选搜索服务已不存在，请重新选择")
            parameters = selection.get("parameters", {})
            if len(json.dumps(selection, ensure_ascii=False)) > 20000:
                raise PreferencesError("联网参数过长")
            if service is not None:
                self.search._validate_parameters(self.search._catalog(service["kind"])["search_parameters"], parameters)
            elif not isinstance(parameters, dict):
                raise PreferencesError("联网参数格式不正确")
            saved["service_id"] = service_id
            if parameters:
                saved["parameters"] = copy.deepcopy(parameters)
        return {"conflict_policy": policy, "search": saved, "teaching_mode": teaching_mode}
