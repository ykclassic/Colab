"""Durable persistence for Phase 21E validation and vertical-slice results."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from .quant_vertical_slice import QuantVerticalSlice


class PostgresQuantVerticalSliceStore:
    def __init__(self, connection_factory: Callable[[], Connection[Any]]) -> None:
        self._connection_factory = connection_factory

    def save(self, result: dict[str, Any]) -> str:
        validation = result["scientific_validation"]
        experiment = result["experiment"]
        digest = result["reproducibility_hash"]
        with self._connection_factory() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.quant_research_runs
                (run_id,workspace_id,dataset_id,strategy_id,experiment_id,experiment_hash,validation_hash,reproducibility_hash,backtest,walk_forward_oos,risk,stress,monte_carlo,robustness,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                (UUID(str(result["experiment"].experiment_id)), experiment.workspace_id, result["dataset"].dataset_id,
                 experiment.strategy_id, experiment.experiment_id, result["experiment_hash"], validation.validation_hash,
                 digest, Jsonb(result["backtest"].model_dump(mode="json")), Jsonb(result["walk_forward_oos"].model_dump(mode="json")),
                 Jsonb(result["risk"].model_dump(mode="json")), Jsonb([x.model_dump(mode="json") for x in result["stress"]]),
                 Jsonb(result["monte_carlo"].model_dump(mode="json")), Jsonb(result["robustness"].model_dump(mode="json"))),
            )
        return digest

    def list(self, workspace_id: UUID) -> list[dict[str, Any]]:
        with self._connection_factory() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT run_id,workspace_id,dataset_id,strategy_id,experiment_id,experiment_hash,validation_hash,reproducibility_hash,created_at FROM public.quant_research_runs WHERE workspace_id=%s ORDER BY created_at DESC",
                (workspace_id,),
            )
            columns = [desc.name for desc in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
