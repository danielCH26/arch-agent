import asyncio
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class SSEStreamCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that collects LLM tokens and makes them
    available as an async iterator for FastAPI's StreamingResponse.

    Usage:
        handler = SSEStreamCallbackHandler()
        agent.invoke({"input": msg}, {"callbacks": [handler]})
        async for token in handler:
            yield token
    """

    def __init__(self):
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._done = False
        self._errors: list[str] = []

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """Called by LangChain each time a new token arrives."""
        if token:
            await self._queue.put(token)

    def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        self._done = True

    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        self._errors.append(str(error))
        self._done = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._errors:
            raise RuntimeError(self._errors[0])

        if self._done and self._queue.empty():
            raise StopAsyncIteration

        token = await self._queue.get()
        return token
