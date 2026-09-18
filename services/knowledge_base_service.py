"""Amazon Bedrock Knowledge Base retrieval (FAQ, terms & conditions, policies)."""

from typing import Any

import boto3

from configs.settings import settings
from utils.logger import Logger


class KnowledgeBaseService:
    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.kb_id = settings.knowledge_base_id
        self.top_k = settings.knowledge_base_top_k
        self._client = (
            boto3.client("bedrock-agent-runtime", region_name=settings.region)
            if self.kb_id
            else None
        )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        """Return the top matching passages as ``[{"text", "source", "score"}]``.
        Raises on API failure so the caller can fall back."""
        response = self._client.retrieve(
            knowledgeBaseId=self.kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": self.top_k}
            },
        )
        passages = []
        for item in response.get("retrievalResults", []):
            location = item.get("location", {})
            source = (
                location.get("s3Location", {}).get("uri")
                or location.get("webLocation", {}).get("url")
            )
            passages.append(
                {
                    "text": item.get("content", {}).get("text", ""),
                    "source": source,
                    "score": item.get("score"),
                }
            )
        return passages
