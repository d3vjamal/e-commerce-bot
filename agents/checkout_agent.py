"""CheckoutAgent — the multi-step, confirm-before-execute checkout flow.

Steps: review cart -> choose delivery address -> delivery charges ->
optional coupon -> payment method -> explicit total confirmation ->
place order -> (online payments only) Razorpay create / verify / capture.

Sets ``checkout_state.status = "COMPLETE"`` with the order id when done, or
``"FAILED"`` on an unrecoverable backend error.
"""

from agents.base import SpecialistAgent
from tools.ecommerce_tools import checkout_tools


class CheckoutAgent(SpecialistAgent):
    sop_path = "chat/checkout.sop.md"
    name = "CHECKOUT"

    def __init__(self, logger_config):
        super().__init__(
            logger_config,
            checkout_tools(logger_config),
            temperature=0.0,
            preserve_recent_messages=12,
        )
