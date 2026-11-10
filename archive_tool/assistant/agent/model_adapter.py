"""OpenAI-compatible chat adapter implementing the LangChain Core contract."""
import json
from typing import Any

from pydantic import ConfigDict, PrivateAttr
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool


class ArchiveChatModel(BaseChatModel):
    """Custom chat model reusing ModelService for transport and credentials."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    service: Any
    _bound_tools: list[dict] = PrivateAttr(default_factory=list)
    _tool_choice: str | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "archive-openai-compatible"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.service.chat_model}

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        bound = self.model_copy(deep=False)
        bound._bound_tools = [convert_to_openai_tool(item) for item in tools]
        bound._tool_choice = tool_choice
        return bound

    @staticmethod
    def _to_openai_message(message: BaseMessage) -> dict:
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, ToolMessage):
            return {"role": "tool", "tool_call_id": message.tool_call_id,
                    "content": str(message.content)}
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            raise ValueError("不支持的消息类型")
        if not isinstance(message.content, str):
            raise ValueError("工具模式只接受文本消息")
        return {"role": role, "content": message.content}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        payload = {"model": self.service.chat_model, "temperature": 0,
                   "messages": [self._to_openai_message(item) for item in messages]}
        tools = kwargs.get("tools", self._bound_tools)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = kwargs.get("tool_choice", self._tool_choice or "auto")
        if stop:
            payload["stop"] = stop
        response = self.service.post("/chat/completions", payload)
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("模型服务未返回有效的对话结果")
        message = choices[0].get("message")
        if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
            raise ValueError("模型服务返回了无效的 assistant 消息")
        calls = []
        for call in message.get("tool_calls") or []:
            try:
                function = call["function"]
                args = function["arguments"]
                parsed = json.loads(args) if isinstance(args, str) else args
                if not isinstance(parsed, dict):
                    raise ValueError
                identity, name = call["id"], function["name"]
                if not isinstance(identity, str) or not identity or not isinstance(name, str):
                    raise ValueError
                calls.append({"id": identity, "name": name, "args": parsed, "type": "tool_call"})
            except (KeyError, TypeError, json.JSONDecodeError, ValueError):
                raise ValueError("模型服务返回了无效的工具调用") from None
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ValueError("模型服务返回了无效的文本内容")
        ai_message = AIMessage(content=content, tool_calls=calls)
        return ChatResult(generations=[ChatGeneration(message=ai_message)],
                          llm_output={"model": self.service.chat_model})
