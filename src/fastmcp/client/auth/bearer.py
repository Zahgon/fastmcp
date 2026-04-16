import httpx
from pydantic import SecretStr

from fastmcp.utilities.logging import get_logger

__all__ = ["BearerAuth"]

logger = get_logger(__name__)


class BearerAuth(httpx.Auth):
    def __init__(self, token: str):
        self.token = SecretStr(token)

    def auth_flow(self, request):
        pass
