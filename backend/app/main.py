from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncBaseTransport

from . import __version__
from .ai_runtime import AiRunManager
from .auth import AuthService
from .config import Settings
from .conversations import ConversationService
from .credentials import CredentialStore
from .db import Database
from .layouts import LayoutService
from .model_discovery import ModelDiscoveryService
from .network import wsl_ip
from .plan_editor import PlanEditorService
from .plans import PlanService
from .routers import ai, auth, layouts, plans, system

logger = logging.getLogger("nautilus")


def create_app(
    settings: Settings | None = None,
    provider_transport: AsyncBaseTransport | None = None,
) -> FastAPI:
    """provider_transport 仅供测试注入 httpx.MockTransport，生产路径保持为 None。"""
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(app_settings.database_path, app_settings.migrations_dir)
        auth_service = AuthService(database, app_settings.session_ttl_seconds)
        plan_service = PlanService(database)
        plan_editor_service = PlanEditorService(database, plan_service)
        layout_service = LayoutService(database)
        credential_store = CredentialStore(app_settings.credentials_dir)
        conversation_service = ConversationService(database, plan_service, credential_store)
        interrupted_title_runs = conversation_service.recover_interrupted_title_runs()
        if interrupted_title_runs:
            logger.warning("Recovered %s interrupted conversation title runs.", interrupted_title_runs)
        ai_run_manager = AiRunManager(conversation_service, transport=provider_transport)
        model_discovery = ModelDiscoveryService(transport=provider_transport)
        identity = auth_service.ensure_local_identity()
        app_settings.runtime_token_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(app_settings.runtime_token_path.parent, 0o700)
        token_fd = os.open(
            app_settings.runtime_token_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(token_fd, "w", encoding="utf-8") as token_file:
            token_file.write(auth_service.runtime_access_token)
        os.chmod(app_settings.runtime_token_path, 0o600)
        app.state.settings = app_settings
        app.state.database = database
        app.state.auth = auth_service
        app.state.plans = plan_service
        app.state.plan_editor = plan_editor_service
        app.state.layouts = layout_service
        app.state.credentials = credential_store
        app.state.conversations = conversation_service
        app.state.ai_runs = ai_run_manager
        app.state.model_discovery = model_discovery
        logger.info("Nautilus identity ready: %s", identity["device_id"])
        logger.info("Nautilus access token generated for this process.")
        logger.info("API access: http://%s:%s", wsl_ip(), app_settings.port)
        try:
            yield
        finally:
            await ai_run_manager.shutdown()
            try:
                app_settings.runtime_token_path.unlink()
            except FileNotFoundError:
                pass
            database.close()

    app = FastAPI(
        title="Nautilus Local Service",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://[^/]+:5173$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(plans.router)
    app.include_router(layouts.router)
    app.include_router(ai.router)
    return app


app = create_app()
