"""Runtime configuration read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value != "" else default


@dataclass(frozen=True)
class Settings:
    environment: str
    aws_region: str
    sec_user_agent: str | None
    sec_max_rps: float
    data_lake_bucket: str | None
    glue_database: str
    athena_workgroup: str
    athena_ai_workgroup: str
    bedrock_model_id: str | None
    ai_daily_quota_per_user: int
    ai_global_daily_cap: int
    ai_max_result_rows: int
    ai_kill_switch_param: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        environment=_env("ENVIRONMENT", "dev"),
        aws_region=_env("AWS_REGION", "us-east-1"),
        sec_user_agent=_env("SEC_USER_AGENT"),
        sec_max_rps=float(_env("SEC_MAX_REQUESTS_PER_SECOND", "5")),
        data_lake_bucket=_env("DATA_LAKE_BUCKET"),
        glue_database=_env("GLUE_DATABASE", "finxplore"),
        athena_workgroup=_env("ATHENA_WORKGROUP", "finxplore-app"),
        athena_ai_workgroup=_env("ATHENA_AI_WORKGROUP", "ai-readonly"),
        bedrock_model_id=_env("BEDROCK_MODEL_ID"),
        ai_daily_quota_per_user=int(_env("AI_DAILY_QUOTA_PER_USER", "20")),
        ai_global_daily_cap=int(_env("AI_GLOBAL_DAILY_CAP", "300")),
        ai_max_result_rows=int(_env("AI_MAX_RESULT_ROWS", "100")),
        ai_kill_switch_param=_env("AI_KILL_SWITCH_PARAM", "/finxplore/dev/ai_enabled"),
    )
