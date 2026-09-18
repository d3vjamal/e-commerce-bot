from typing import List

from strands.types.content import SystemContentBlock

from configs.settings import settings
from utils.logger import Logger


class CommonUtility:

    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.base_path = "sops"

    def _render(self, text: str) -> str:
        """Substitute simple ``{{TOKENS}}`` used across the SOPs."""
        return text.replace("{{BRAND_NAME}}", settings.brand_name)

    def load_sop(self, file_name: str) -> List[SystemContentBlock]:
        """
        Method to read SOP from file
        """
        try:
            self.logger.info(f"Reading SOP File: {file_name}")
            with open(f"{self.base_path}/{file_name}", "r", encoding="utf-8") as f:
                system_prompt = [
                    SystemContentBlock(text=self._render(f.read())),
                    SystemContentBlock(cachePoint={"type": "default"}),
                ]
                return system_prompt
        except Exception as e:
            self.logger.exception(e)
            raise e

    def load_faq(self, file_name: str) -> str:
        """Read a plain-text FAQ / knowledge file from ``sops/`` and return it."""
        try:
            self.logger.info(f"Reading FAQ file: {file_name}")
            with open(f"{self.base_path}/{file_name}", "r", encoding="utf-8") as f:
                return self._render(f.read())
        except FileNotFoundError:
            self.logger.warning(f"FAQ file not found: {file_name}")
            return ""
        except Exception as e:
            self.logger.exception(e)
            return ""

    def extract_text(self, result, messages: list = None) -> str:
        """
        Extract the last assistant text response from an AgentResult.

        Strands AgentResult.message holds the LAST message the agent produced.
        When the final turn ends on a tool call (e.g. IntentRouter), that message
        contains only a toolUse block — no text — so str(result) returns "".

        Fix: walk agent.messages in reverse to find the last assistant turn
        that actually contains a text block. Falls back to str(result).
        """
        try:
            self.logger.info("Extracting result as text...")

            # Primary: scan conversation history for last assistant text block
            if messages:
                for msg in reversed(messages):
                    if msg.get("role") != "assistant":
                        continue
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and "text" in block:
                            text = block["text"].strip()
                            if text:
                                self.logger.debug(
                                    f"extract_text: found in messages history (len={len(text)})"
                                )
                                return text

            # Fallback: str(result) works when final message IS a text turn
            text = str(result).strip()
            if text:
                return text

            self.logger.warning("extract_text: no text found in result or messages")
            return ""

        except Exception as e:
            self.logger.exception(f"extract_text failed: {e}")
            return str(result) if result else ""
