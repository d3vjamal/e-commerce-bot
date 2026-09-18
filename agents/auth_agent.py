"""AuthAgent — brings the shopper to an authenticated state.

Two paths:

* **Silent adoption** — when the host app already put the user's JWT in
  ``sessionContext.authToken``, the orchestrator writes ``auth_state`` directly
  and never calls this agent.
* **Interactive login** — otherwise this agent collects credentials and calls
  ``ecom_login`` / ``ecom_login_social``, which store the token and set
  ``auth_state.verification_status = "PASS"``.
"""

from agents.base import SpecialistAgent
from configs.settings import settings
from tools.ecommerce_tools import auth_tools


class AuthAgent(SpecialistAgent):
    sop_path = "chat/auth.sop.md"
    name = "AUTH"

    def __init__(self, logger_config):
        super().__init__(
            logger_config,
            auth_tools(logger_config),
            model_id=settings.auth_model_id,
            temperature=0.1,
        )
