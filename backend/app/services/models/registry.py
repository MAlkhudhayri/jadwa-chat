"""Model Registry — singleton that loads, tracks, and exposes all small ML models.

Every model is loaded lazily on first use or eagerly at startup via ``warm_all()``.
The registry provides a ``/status`` view consumed by the frontend Models tab.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelEntry:
    name: str
    description: str
    category: str  # "rag", "anomaly", "forecast", "attribution", "clustering"
    status: str = "not_loaded"  # not_loaded | loading | ready | error
    loaded_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_run_ms: Optional[int] = None
    error: Optional[str] = None
    size_mb: Optional[float] = None
    instance: Any = None
    meta: Dict[str, Any] = field(default_factory=dict)


class ModelRegistry:
    """Global registry of small ML models."""

    _instance: Optional["ModelRegistry"] = None

    def __init__(self) -> None:
        self._models: Dict[str, ModelEntry] = {}
        self._register_definitions()

    @classmethod
    def get(cls) -> "ModelRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Model definitions ─────────────────────────────────────────────

    def _register_definitions(self) -> None:
        defs = [
            ModelEntry(
                name="reranker",
                description="Cross-encoder reranker for RAG top-k reranking",
                category="rag",
                size_mb=22.0,
            ),
            ModelEntry(
                name="changepoint",
                description="PELT change-point detection via ruptures",
                category="anomaly",
                size_mb=0.1,
            ),
            ModelEntry(
                name="isolation_forest",
                description="Isolation Forest anomaly scorer on engineered features",
                category="anomaly",
                size_mb=2.0,
            ),
            ModelEntry(
                name="elastic_net",
                description="Elastic Net driver attribution for scorecard domains",
                category="attribution",
                size_mb=0.5,
            ),
            ModelEntry(
                name="topic_cluster",
                description="TF-IDF + KMeans topic clustering for document taxonomy",
                category="clustering",
                size_mb=5.0,
            ),
        ]
        for d in defs:
            self._models[d.name] = d

    # ── Load helpers ──────────────────────────────────────────────────

    def _load_model(self, name: str) -> None:
        entry = self._models.get(name)
        if not entry:
            return
        entry.status = "loading"
        t0 = time.time()
        try:
            if name == "reranker":
                from app.services.models.reranker import load_reranker
                entry.instance = load_reranker()
            elif name == "changepoint":
                from app.services.models.changepoint import load_changepoint
                entry.instance = load_changepoint()
            elif name == "isolation_forest":
                from app.services.models.isolation_forest import load_isolation_forest
                entry.instance = load_isolation_forest()
            elif name == "elastic_net":
                from app.services.models.drivers import load_elastic_net
                entry.instance = load_elastic_net()
            elif name == "topic_cluster":
                from app.services.models.topic_cluster import load_topic_cluster
                entry.instance = load_topic_cluster()
            else:
                entry.status = "error"
                entry.error = f"Unknown model: {name}"
                return

            elapsed = int((time.time() - t0) * 1000)
            entry.status = "ready"
            entry.loaded_at = datetime.now(timezone.utc)
            entry.last_run_ms = elapsed
            entry.error = None
            logger.info(f"Model '{name}' loaded in {elapsed}ms")

        except Exception as e:
            entry.status = "error"
            entry.error = str(e)[:300]
            logger.warning(f"Model '{name}' failed to load: {e}")

    def warm_all(self) -> Dict[str, str]:
        """Load every registered model eagerly. Returns {name: status}."""
        results = {}
        for name in self._models:
            self._load_model(name)
            results[name] = self._models[name].status
        return results

    def warm(self, name: str) -> str:
        """Load a single model by name. Returns status."""
        self._load_model(name)
        return self._models[name].status

    # ── Accessors ─────────────────────────────────────────────────────

    def get_model(self, name: str) -> Any:
        """Return the loaded model instance, loading lazily if needed."""
        entry = self._models.get(name)
        if not entry:
            raise KeyError(f"Unknown model: {name}")
        if entry.status != "ready":
            self._load_model(name)
        if entry.status != "ready":
            raise RuntimeError(f"Model '{name}' is not available: {entry.error}")
        return entry.instance

    def record_run(self, name: str, duration_ms: int) -> None:
        entry = self._models.get(name)
        if entry:
            entry.last_run_at = datetime.now(timezone.utc)
            entry.last_run_ms = duration_ms

    def status(self) -> Dict[str, Any]:
        """JSON-safe status dict for the frontend."""
        models = []
        for entry in self._models.values():
            models.append({
                "name": entry.name,
                "description": entry.description,
                "category": entry.category,
                "status": entry.status,
                "loaded_at": entry.loaded_at.isoformat() if entry.loaded_at else None,
                "last_run_at": entry.last_run_at.isoformat() if entry.last_run_at else None,
                "last_run_ms": entry.last_run_ms,
                "size_mb": entry.size_mb,
                "error": entry.error,
                "meta": entry.meta,
            })
        ready = sum(1 for m in models if m["status"] == "ready")
        total = len(models)
        return {
            "total": total,
            "ready": ready,
            "models": models,
        }


def get_registry() -> ModelRegistry:
    return ModelRegistry.get()
