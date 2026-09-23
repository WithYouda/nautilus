from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncBaseTransport

from . import __version__
from .agent_runtime import AgentRuntime
from .ai_runtime import AiRunManager
from .auth import AuthService
from .config import Settings
from .conversations import ConversationService
from .credentials import CredentialStore
from .evidence import EvidenceService, ProviderSemanticAnalyzer
from .evidence_provider import EvidenceProviderService
from .evidence_events import EvidenceEventService
from .db import Database
from .layouts import LayoutService
from .learning_service import LearningService
from .learning_setup import LearningSetupService
from .measurements import MeasurementService
from .review import ReviewService
from .state_derivation import StateDerivationService
from .learning_storage import open_learning_database
from .verification import VerificationService
from .question_discussion import QuestionDiscussionService
from .model_discovery import ModelDiscoveryService
from .network import wsl_ip
from .plan_editor import PlanEditorService
from .plans import PlanService
from .routers import ai, auth, layouts, learning, plans, system

logger = logging.getLogger("nautilus")


def create_app(
    settings: Settings | None = None,
    provider_transport: AsyncBaseTransport | None = None,
) -> FastAPI:
    """provider_transport 仅供测试注入 httpx.MockTransport，生产路径保持为 None。"""
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(app_settings.database_path, app_settings.migrations_dir, migrate=False)
        learning_path = app_settings.learning_database_path or app_settings.data_dir / "learning.sqlite3"
        try:
            learning_database = open_learning_database(learning_path, migrate=False)
        except BaseException:
            database.close()
            raise
        auth_service = AuthService(database, app_settings.session_ttl_seconds)
        plan_service = PlanService(database)
        plan_editor_service = PlanEditorService(database, plan_service)
        layout_service = LayoutService(database)
        learning_service = LearningService(learning_database)
        agent_runtime = AgentRuntime(learning_service)
        evidence_events = EvidenceEventService(learning_database)
        state_derivation_service = StateDerivationService(learning_service, evidence_events)
        review_service = ReviewService(learning_service, state_derivation_service, evidence_events)
        measurement_service = MeasurementService(learning_service)
        credential_store = CredentialStore(app_settings.credentials_dir)
        conversation_service = ConversationService(database, plan_service, credential_store)
        learning_setup_service = LearningSetupService(
            learning_service,
            conversation_service,
            transport=provider_transport,
        )
        verification_service = VerificationService(
            learning_service,
            conversation_service,
            transport=provider_transport,
        )
        evidence_provider_service = EvidenceProviderService(learning_service, conversation_service)
        evidence_service = EvidenceService(
            learning_service,
            evidence_events=evidence_events,
            semantic_analyzer=ProviderSemanticAnalyzer(
                conversation_service,
                transport=provider_transport,
                provider_service=evidence_provider_service,
            ),
        )
        verification_service.evidence = evidence_service
        discussion_service = QuestionDiscussionService(verification_service)
        discussion_service.recover()
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
        app.state.learning = learning_service
        app.state.learning_setup = learning_setup_service
        app.state.verification = verification_service
        app.state.discussions = discussion_service
        app.state.agent_runtime = agent_runtime
        app.state.state_derivation = state_derivation_service
        app.state.review = review_service
        app.state.measurements = measurement_service
        app.state.evidence = evidence_service
        app.state.evidence_provider = evidence_provider_service
        app.state.evidence_events = evidence_events
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
            await discussion_service.shutdown()
            await ai_run_manager.shutdown()
            learning_service.close()
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
    app.include_router(learning.router)
    app.include_router(ai.router)
    return app


app = create_app()
