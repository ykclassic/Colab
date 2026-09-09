"""Durable PostgreSQL persistence for Phase 18 quant research."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .quant_platform import ExperimentRecord, StrategyRecord


class PostgresQuantStore:
    def __init__(self, connection_factory: Callable[[], Connection[Any]]) -> None:
        self._connection_factory = connection_factory

    def register_strategy(self, strategy: StrategyRecord) -> StrategyRecord:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO public.quant_strategies (strategy_id,workspace_id,name,version,code_revision,parameters,dataset_ids,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (strategy.strategy_id, strategy.workspace_id, strategy.name, strategy.version, strategy.code_revision,
                 Jsonb(strategy.parameters), Jsonb([str(x) for x in strategy.dataset_ids]), strategy.created_at),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("strategy registration returned no row")
        row["dataset_ids"] = [UUID(x) for x in row["dataset_ids"]]
        return StrategyRecord.model_validate(row)

    def list_strategies(self, workspace_id: UUID) -> list[StrategyRecord]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.quant_strategies WHERE workspace_id=%s ORDER BY name,version", (workspace_id,))
            rows = cur.fetchall()
        for row in rows:
            row["dataset_ids"] = [UUID(x) for x in row["dataset_ids"]]
        return [StrategyRecord.model_validate(row) for row in rows]

    def save_experiment(self, record: ExperimentRecord, result: dict[str, Any], digest: str) -> ExperimentRecord:
        with self._connection_factory() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO public.quant_experiments (experiment_id,workspace_id,strategy_id,strategy_version,dataset_ids,seed,configuration,metrics,result,experiment_hash,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (record.experiment_id, record.workspace_id, record.strategy_id, record.strategy_version,
                 Jsonb([str(x) for x in record.dataset_ids]), record.seed, Jsonb(record.configuration),
                 Jsonb(record.metrics), Jsonb(result), digest, record.created_at),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("experiment persistence returned no row")
        data = {key: row[key] for key in ("experiment_id", "workspace_id", "strategy_id", "strategy_version", "dataset_ids", "seed", "configuration", "metrics", "created_at")}
        data["dataset_ids"] = [UUID(x) for x in data["dataset_ids"]]
        return ExperimentRecord.model_validate(data)

    def list_experiments(self, workspace_id: UUID) -> list[dict[str, Any]]:
        with self._connection_factory() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM public.quant_experiments WHERE workspace_id=%s ORDER BY created_at DESC", (workspace_id,))
            return list(cur.fetchall())
