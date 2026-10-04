from __future__ import annotations

import logging
import os
from time import monotonic
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncBaseTransport

from .diagnostics import DiagnosticService, RuntimeDiagnosticHandler
from .routers import diagnostics
from . import __version__
from .agent_runtime import AgentRuntime
from .ai_runtime import AiRunManager
from .plan_organization import PlanOrganization
from .learning_paths import LearningPaths
from .commitments import Commitments
from .routers import commitments
from .routers import learning_paths
from .routers import plan_organization
from .outcome_graph import OutcomeGraph
from .routers import outcome_graph
from .auth import AuthService
from .config import Settings
from .conversations import ConversationService
from .credentials import CredentialStore
from .search_service import SearchService
from .outbound import OutboundApprovals
from .routers import outbound
from .preferences import PreferencesService
from .adaptive_preferences import AdaptivePreferencesService
from .routers import adaptive_preferences
from .routers import preferences
from .evidence import EvidenceService, ProviderSemanticAnalyzer
from .evidence_provider import EvidenceProviderService
from .evidence_events import EvidenceEventService
from .db import Database
from .layouts import LayoutService
from .learning_service import LearningService
from .completion import CompletionService
from .practice import PracticeService
from .routers import practice, delayed_follow_up
from .learning_setup import LearningSetupService
from .measurements import MeasurementService
from .review import ReviewService
from .state_derivation import StateDerivationService
from .learning_storage import open_learning_database
from .verification import VerificationService
from .question_discussion import QuestionDiscussionService
from .model_discovery import ModelDiscoveryService
from .materials import MaterialService
from .material_ocr import MaterialOCR
from .obsidian import ObsidianService
from .conversation_state import CurrentConversationState
from .model_control import ModelControlService
from .routers import model_control
from .routers import materials
from .routers import material_ocr
from .routers import obsidian
from .network import wsl_ip
from .plan_editor import PlanEditorService
from .plans import PlanService
from .routers import ai, auth, layouts, learning, plans, system, search, conversation_state

logger = logging.getLogger("nautilus")


def create_app(
    settings: Settings | None = None,
    provider_transport: AsyncBaseTransport | None = None,
) -> FastAPI:
    """provider_transport 仅供测试注入 httpx.MockTransport，生产路径保持为 None。"""
    app_settings = settings or Settings.from_env()
    # Tolerant PDF parsers may quote file bytes in warnings. API callers receive
    # fixed extraction error codes; document content must not enter runtime logs.
    pdf_logger = logging.getLogger('pypdf')
    pdf_logger.addHandler(logging.NullHandler())
    pdf_logger.propagate = False

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
        search_service = SearchService(credential_store, transport=provider_transport)
        outbound_approvals = OutboundApprovals()
        conversation_service.outbound = outbound_approvals
        conversation_service.search_service = search_service
        preferences_service = PreferencesService(credential_store, search_service)
        conversation_service.preferences = preferences_service
        adaptive_service = AdaptivePreferencesService(conversation_service, learning_database, credential_store)
        conversation_service.adaptive_preferences = adaptive_service
        material_service = MaterialService(learning_service, conversation_service, preferences_service)
        conversation_service.materials = material_service
        ocr_service = MaterialOCR(material_service, credential_store, transport=provider_transport)
        ocr_service.recover()
        obsidian_service = ObsidianService(credential_store, material_service)
        material_service.obsidian = obsidian_service
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
        model_control_service = ModelControlService(learning_service, conversation_service)
        conversation_service.model_control = model_control_service
        discussion_service.model_control = model_control_service
        current_state = CurrentConversationState(material_service, conversation_service, discussion_service, search_service)
        conversation_service.current_state = current_state
        discussion_service.current_state = current_state
        discussion_service.recover()
        CompletionService(verification_service).recover()
        PracticeService(verification_service).recover()
        interrupted_title_runs = conversation_service.recover_interrupted_title_runs()
        if interrupted_title_runs:
            logger.warning("Recovered %s interrupted conversation title runs.", interrupted_title_runs)
        ai_run_manager = AiRunManager(conversation_service, transport=provider_transport)
        graph_service = OutcomeGraph(learning_service, evidence_provider_service, provider_transport, ai_run_manager._provider_slots)
        graph_service.recover()
        learning_paths_service=LearningPaths(learning_service,conversation_service)
        commitments_service=Commitments(learning_service,conversation_service,learning_paths_service,
            transport=provider_transport,provider_slots=ai_run_manager._provider_slots)
        commitments_service.recover()
        app.state.commitments=commitments_service
        app.state.outcome_graph = graph_service
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
        app.state.plan_organization = PlanOrganization(learning_service)
        app.state.learning_paths = learning_paths_service
        app.state.learning = learning_service
        app.state.learning_setup = learning_setup_service
        app.state.verification = verification_service
        app.state.discussions = discussion_service
        app.state.conversation_state = current_state
        app.state.model_control = model_control_service
        app.state.agent_runtime = agent_runtime
        app.state.state_derivation = state_derivation_service
        app.state.review = review_service
        app.state.measurements = measurement_service
        app.state.evidence = evidence_service
        app.state.evidence_provider = evidence_provider_service
        app.state.evidence_events = evidence_events
        app.state.credentials = credential_store
        app.state.search = search_service
        app.state.outbound = outbound_approvals
        app.state.preferences = preferences_service
        app.state.adaptive_preferences = adaptive_service
        app.state.materials = material_service
        app.state.material_ocr = ocr_service
        app.state.obsidian = obsidian_service
        diagnostic_service = DiagnosticService(app_settings.data_dir / 'runtime' / 'diagnostics')
        app.state.diagnostics = diagnostic_service
        conversation_service.diagnostics = diagnostic_service
        runtime_handler = RuntimeDiagnosticHandler(diagnostic_service, identity['id'])
        logging.getLogger('nautilus').addHandler(runtime_handler)
        diagnostic_service.record(identity['id'], module='system', event='service.started')
        app.state.conversations = conversation_service
        app.state.ai_runs = ai_run_manager
        app.state.model_discovery = model_discovery
        logger.info("Nautilus identity ready: %s", identity["device_id"])
        logger.info("Nautilus access token generated for this process.")
        logger.info("API access: http://%s:%s", wsl_ip(), app_settings.port)
        try:
            yield
        finally:
            outbound_approvals.close()
            await commitments_service.shutdown()
            await graph_service.shutdown()
            await discussion_service.shutdown()
            await ai_run_manager.shutdown()
            await ocr_service.shutdown()
            diagnostic_service.record(identity['id'], module='system', event='service.stopped')
            logging.getLogger('nautilus').removeHandler(runtime_handler)
            diagnostic_service.close()
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
    @app.middleware('http')
    async def diagnostic_requests(request, call_next):
        request.state.diagnostic_id = str(uuid4())
        started = monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers['X-Nautilus-Request-ID'] = request.state.diagnostic_id
            if request.url.path.startswith('/api/diagnostics'):
                response.headers['Cache-Control'] = 'no-store'
            return response
        finally:
            owner = getattr(request.state, 'diagnostic_owner', None)
            service = getattr(request.app.state, 'diagnostics', None)
            route = getattr(request.scope.get('route'), 'path', None)
            if owner and service and route and not route.startswith('/api/diagnostics'):
                group = route.split('/')[2]
                module = {'ai': 'ai', 'learning': 'learning', 'materials': 'materials',
                          'search': 'search', 'preferences': 'settings'}.get(group, 'system')
                service.record(owner, module=module, event='request.finished',
                    level='error' if status >= 500 else 'warning' if status >= 400 else 'info',
                    request_id=request.state.diagnostic_id, method=request.method, route=route,
                    status=status, code=f'HTTP_{status}', duration_ms=round((monotonic() - started) * 1000))

    app.include_router(diagnostics.router)
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(plans.router)
    app.include_router(layouts.router)
    app.include_router(learning.router)
    app.include_router(outcome_graph.router)
    app.include_router(plan_organization.router)
    app.include_router(learning_paths.router)
    app.include_router(commitments.router)
    app.include_router(commitments.feedback_router)
    app.include_router(practice.router)
    app.include_router(delayed_follow_up.router)
    app.include_router(ai.router)
    app.include_router(conversation_state.router)
    app.include_router(model_control.router)
    app.include_router(search.router)
    app.include_router(outbound.router)
    app.include_router(materials.router)
    app.include_router(material_ocr.router)
    app.include_router(obsidian.router)
    app.include_router(preferences.router)
    app.include_router(adaptive_preferences.router)
    return app


app = create_app()
