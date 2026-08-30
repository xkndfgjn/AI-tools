"""FastAPI application entry point.

Starts the HTTP service, initializes RPA engine, wires routes.

Usage:
    python src/main.py
    # or
    uvicorn src.main:app --host 127.0.0.1 --port 9420
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import yaml
from fastapi import FastAPI
from loguru import logger
import uvicorn

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# Auto-load all operation modules to trigger @register_operation
import src.operations  # noqa: F401
from src.api.routes import router, init_routes
from src.mcp import build_default_facade
from src.operations.registry import OperationRegistry


def load_config(config_path: str = "config/config.yaml") -> dict:
    """Load YAML configuration."""
    # Search relative to project root
    candidates = [
        config_path,
        os.path.join(os.path.dirname(__file__), "..", config_path),
        os.path.join(os.path.dirname(__file__), "..", "..", config_path),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    logger.warning(f"Config file not found, using defaults")
    return {}


def setup_logger(config: dict):
    """Configure loguru logger from config."""
    log_config = config.get("logging", {})
    level = log_config.get("level", "INFO")
    log_file = log_config.get("file", "./data/logs/wechat_rpa.log")
    rotation = log_config.get("rotation", "10 MB")

    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger.remove()  # remove default handler
    logger.add(sys.stderr, level=level)
    logger.add(log_file, level=level, rotation=rotation, encoding="utf-8")
    return logger


class OperationEngine:
    """Wires RPA engine + operation executor together.

    Holds singletons: controller, finder, watcher, execution lock.
    """

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.controller = None       # RpaController - initialized lazily
        self.finder = None           # ElementFinder
        self.watcher = None          # WindowWatcher
        self._lock = asyncio.Lock()  # serial execution (WeChat has 1 window)

    async def initialize(self):
        """Initialize RPA engine components. Called at app startup."""
        from src.rpa.controller import RpaController
        from src.rpa.finder import ElementFinder
        from src.rpa.watcher import WindowWatcher

        self.controller = RpaController(self.config)
        self.finder = ElementFinder.from_config(self.config, controller=self.controller)
        self.watcher = WindowWatcher(self.controller, self.config, self.logger)
        asyncio.create_task(self.watcher.start())

        # Try to locate WeChat once at startup so /health can report status.
        # Wrapped with a timeout: a slow/hung UIAutomation call must never
        # block the service from starting. Operations do their own window
        # lookup, so a failed startup probe is non-fatal.
        try:
            found = await asyncio.wait_for(
                asyncio.to_thread(self.controller.find_wechat_window),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            found = None
            self.logger.warning("WeChat window lookup timed out at startup; continuing")
        except Exception as e:
            found = None
            self.logger.warning(f"WeChat window lookup failed at startup: {e}; continuing")
        if not found:
            self.logger.warning(
                "WeChat window not found at startup. Service is running but "
                "operations will fail until WeChat is opened."
            )
        else:
            self.logger.info(f"WeChat window found: HWND {found}")

    async def execute(self, op_class, params: dict):
        """Execute an operation with the serial lock.

        1. Instantiate op_class
        2. Build OperationContext
        3. Acquire lock, run operation lifecycle
        4. Return OperationResult
        """
        from src.operations.base import OperationContext, OperationResult, OperationStatus

        if self.controller is None or self.finder is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="RPA engine not initialized yet",
            )

        op = op_class()
        ctx = OperationContext(
            controller=self.controller,
            finder=self.finder,
            config=self.config,
            logger=self.logger,
        )
        async with self._lock:
            return await op.run(ctx, params)


def create_app() -> FastAPI:
    """Application factory."""
    config = load_config()
    lg = setup_logger(config)

    app = FastAPI(title="WeChat RPA Skill", version="0.1.0")

    # Initialize engine
    engine = OperationEngine(config, lg)

    # Build MCP facade bridged to the real engine and register the 6 RPA
    # operations as tools. The facade only stores the engine reference; it
    # dispatches to engine.execute() at call time (after startup initializes
    # the controller), so building it here is safe.
    facade = build_default_facade(engine)

    # Wire routes (facade exposes /api/mcp/call and /api/mcp/tools)
    init_routes(engine, config, lg, facade)
    app.include_router(router)

    @app.on_event("startup")
    async def startup():
        await engine.initialize()
        lg.info(f"WeChat RPA service started on {config.get('server', {}).get('host')}:{config.get('server', {}).get('port')}")
        lg.info(f"Registered operations: {[op['name'] for op in OperationRegistry.list_all()]}")
        lg.info(f"MCP facade tools: {facade.list_tools()}")

    @app.on_event("shutdown")
    async def shutdown():
        if engine.watcher:
            await engine.watcher.stop()
        lg.info("WeChat RPA service stopped")

    return app


app = create_app()


if __name__ == "__main__":
    config = load_config()
    host = config.get("server", {}).get("host", "127.0.0.1")
    port = config.get("server", {}).get("port", 9420)
    # Pass the app object directly (instead of "src.main:app") to avoid
    # re-importing this module and creating a second app instance.
    uvicorn.run(app, host=host, port=port, reload=False)
