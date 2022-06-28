# SPDX-FileCopyrightText: 2019-2020 Magenta ApS
#
# SPDX-License-Identifier: MPL-2.0
"""Event handling."""
from fastapi import APIRouter
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.status import HTTP_204_NO_CONTENT

fastapi_router = APIRouter()


@fastapi_router.get("/")
async def index() -> dict[str, str]:
    """Endpoint to return name of integration."""
    return {"name": "adguidsync"}


@fastapi_router.get("/health/live", status_code=HTTP_204_NO_CONTENT)
async def liveness() -> None:
    """Endpoint to be used as a liveness probe for Kubernetes."""
    return None


@fastapi_router.get(
    "/health/ready",
    status_code=HTTP_204_NO_CONTENT,
    responses={
        "204": {"description": "Ready"},
        "503": {"description": "Not ready"},
    },
)
async def readiness() -> None:
    """Endpoint to be used as a readiness probe for Kubernetes."""
    return None


def create_app() -> FastAPI:
    """FastAPI application factory.

    Starts the metrics server, then listens to AMQP messages forever.

    Returns:
        None
    """
    context = {"greeting": "Hello, world!"}

    app = FastAPI()
    app.include_router(fastapi_router)
    app.state.context = context
    Instrumentator().instrument(app).expose(app)

    return app
