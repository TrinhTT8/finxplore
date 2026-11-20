"""API Lambda behind API Gateway HTTP API.

Public routes are throttled at API Gateway. Routes under /ai/* and /me/* are protected
by the Cognito JWT authorizer configured in Terraform; the user id comes from the claims.
"""

from __future__ import annotations

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response, content_types
from aws_lambda_powertools.logging import correlation_paths

from finxplore import __version__
from finxplore.ai.prompts import DISCLAIMER

logger = Logger()
tracer = Tracer()
app = APIGatewayHttpResolver()


def _not_implemented(feature: str, phase: int) -> Response:
    return Response(
        status_code=501,
        content_type=content_types.APPLICATION_JSON,
        body={"error": f"{feature} is not implemented yet (Phase {phase})"},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/companies/search")
def search_companies():  # FR-5
    return _not_implemented("Company search", 3)


@app.get("/companies/<ticker>")
def get_company(ticker: str):  # FR-6, FR-7, FR-8, FR-10
    return _not_implemented(f"Company page for {ticker.upper()}", 3)


@app.get("/compare")
def compare():  # FR-9
    return _not_implemented("Compare", 3)


@app.post("/ai/ask")
def ask():  # FR-14, FR-15 (protected)
    return _not_implemented("AI analyst", 4)


@app.post("/ai/explain")
def explain():  # FR-13 (protected)
    return _not_implemented("Explain this", 4)


@app.post("/ai/feedback")
def feedback():  # FR-16 (protected)
    return _not_implemented("Feedback", 4)


@app.get("/meta/disclaimer")
def disclaimer() -> dict:
    return {"disclaimer": DISCLAIMER}


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_HTTP)
@tracer.capture_lambda_handler
def handler(event: dict, context) -> dict:
    return app.resolve(event, context)
