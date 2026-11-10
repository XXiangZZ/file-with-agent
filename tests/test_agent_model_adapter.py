import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from assistant.agent.model_adapter import ArchiveChatModel
from assistant.agent.tools import build_tools


class FakeService:
    chat_model = "fake-model"
    config = {"chat_model": "fake-model"}

    def __init__(self, responses):
        self.responses = iter(responses)
        self.payloads = []

    def post(self, route, payload):
        self.payloads.append((route, payload))
        return next(self.responses)


def test_custom_model_binds_standard_tools_and_parses_calls():
    service = FakeService([{"choices": [{"message": {"role": "assistant", "content": None,
        "tool_calls": [{"id": "call-1", "type": "function", "function": {
            "name": "kb_sources", "arguments": "{}"}}]}}]}])
    tools, _ = build_tools(index=None, allow_model_calls=False)
    model = ArchiveChatModel(service=service).bind_tools(tools)
    message = model.invoke([HumanMessage(content="查看知识库")])
    assert message.tool_calls == [{"id": "call-1", "name": "kb_sources", "args": {},
                                  "type": "tool_call"}]
    sent = service.payloads[0][1]
    assert sent["tool_choice"] == "auto"
    assert {item["function"]["name"] for item in sent["tools"]} >= {"ask_policy", "kb_sources"}


def test_tool_message_round_trip_and_invalid_arguments_rejected():
    service = FakeService([{"choices": [{"message": {"role": "assistant", "content": "done"}}]}])
    model = ArchiveChatModel(service=service)
    model.invoke([ToolMessage(content="safe result", tool_call_id="call-1")])
    assert service.payloads[0][1]["messages"][0] == {
        "role": "tool", "tool_call_id": "call-1", "content": "safe result"}

    bad = FakeService([{"choices": [{"message": {"role": "assistant", "tool_calls": [{
        "id": "call-2", "function": {"name": "kb_sources", "arguments": "[]"}}]}}]}])
    with pytest.raises(ValueError, match="无效的工具调用"):
        ArchiveChatModel(service=bad).bind_tools([]).invoke([HumanMessage(content="查看")])


def test_tools_exclude_deletes_and_write_tools_only_propose():
    tools, _ = build_tools(index=None, allow_model_calls=False)
    names = {item.name for item in tools}
    assert not any("delete" in name for name in names)
    proposal = next(item for item in tools if item.name == "propose_create_record")
    with pytest.raises(ValueError):
        proposal.invoke({"name": "只提计划"})
    schema = proposal.args_schema.model_json_schema()
    assert "fields" in schema["properties"]
    assert "data" in schema["properties"]
