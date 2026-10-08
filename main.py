import copy
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request

from agents.orchestrator_agent import OrchestratorAgent
from models.agent_invocation_model import InvocationRequest, InvocationResponse
from utils.logger import Logger
from utils.logger_config import LoggerConfig

app = FastAPI(title="commerce-bot", version="0.1.0")

logger_config = LoggerConfig()
logger = Logger(__name__, logger_config)

# One OrchestratorAgent per runtime session, keyed by the
# x-amzn-bedrock-agentcore-runtime-session-id header (see docs/02-api-server.md).
# A caller that omits the header gets a fresh, unstored orchestrator each turn —
# no cross-conversation state leakage, but no continuity either.
_orchestrators: dict[str, OrchestratorAgent] = {}


def _get_orchestrator(session_id: str | None) -> OrchestratorAgent:
    if not session_id:
        return OrchestratorAgent(logger_config, None)
    if session_id not in _orchestrators:
        _orchestrators[session_id] = OrchestratorAgent(
            logger_config, session_id)
    return _orchestrators[session_id]


def _redacted_session_data(data: dict) -> dict:
    """Copy of agent.state['data'] safe to put on the wire — never echo the raw
    backend JWT back to the caller (they already have it; it's dead weight in
    the response and gets duplicated into every logger/tracer downstream)."""
    redacted = copy.deepcopy(data)
    auth_state = redacted.get("auth_state")
    if isinstance(auth_state, dict) and auth_state.get("token"):
        token = auth_state["token"]
        auth_state["token"] = f"{token[:10]}…(redacted)"
    return redacted


@app.post("/invocations", response_model=InvocationResponse)
def invoke_agent_sync(request: Request, body: InvocationRequest):
    """Synchronous turn: prompt in, assistant reply + session data out."""
    try:
        start_time = time.perf_counter()
        session_id = request.headers.get(
            "x-amzn-bedrock-agentcore-runtime-session-id", None
        )
        logger.info(f"Invoking commerce agent | session={session_id}")

        details = body.input.get("details", {}) or {}
        user_message = body.input.get("prompt", "")
        if not user_message:
            raise HTTPException(
                status_code=400,
                detail="No prompt found in input. Provide input.prompt.",
            )

        agent = _get_orchestrator(session_id)
        reply, data = agent.run(user_message, details)
        elapsed = time.perf_counter() - start_time
        logger.info(f"Agent responded in {elapsed:.3f}s")

        response = {
            "message": reply,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sessionId": session_id,
            "sessionData": _redacted_session_data(data),
            "timeTaken": f"{elapsed:.3f} Secs",
        }
        return InvocationResponse(output=response)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ping")
async def ping():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
