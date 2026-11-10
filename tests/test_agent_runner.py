from assistant.agent.runner import run_agent
from assistant.index import KnowledgeIndex


class FakeChatService:
    config = {"chat_model": "fake"}
    chat_model = "fake"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def post(self, route, payload):
        self.calls += 1
        assert route == "/chat/completions"
        assert payload.get("tools")
        return next(self.responses)


def _tool_response(call_id="one", name="kb_sources"):
    return {"choices": [{"message": {"role": "assistant", "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": name, "arguments": "{}"}}]}}]}


def _final_response(content="终结"):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_runner_selects_tool_then_returns_final_turn(tmp_path):
    service = FakeChatService([_tool_response(), _final_response()])
    result = run_agent("查看知识库", KnowledgeIndex(tmp_path / "kb.sqlite3"), service,
                       allow_model_calls=True, max_turns=4)
    assert service.calls == 2
    assert result["tool_calls"] == 1
    assert result["mode"] == "受控 ReAct 工具模式"
    assert result["verified_claims"] == []
    assert "已隐藏未核验结论" in result["verified_answer"]


def test_runner_enforces_turn_limit_and_unapproved_is_local_only(tmp_path):
    service = FakeChatService([_tool_response(str(i)) for i in range(4)])
    result = run_agent("查看知识库", KnowledgeIndex(tmp_path / "kb.sqlite3"), service,
                       allow_model_calls=True, max_turns=4)
    assert service.calls == 4
    assert result["tool_calls"] == 4

    class NeverCalled:
        config = {"chat_model": "fake"}
        def post(self, *args):
            raise AssertionError("unauthorized model request")

    local = run_agent("查看知识库", KnowledgeIndex(tmp_path / "kb.sqlite3"), NeverCalled(),
                      allow_model_calls=False, local_tool="kb_sources")
    assert local["mode"] == "本地只读工具模式"
    assert local["model_used"] is False
    assert local["tool_calls"] == 1


def test_runner_can_choose_a_second_tool_after_reading_first_result(tmp_path):
    service = FakeChatService([_tool_response("manual", "ask_manual"),
                               _tool_response("sources", "kb_sources"), _final_response()])
    result = run_agent("如何使用并查看资料", KnowledgeIndex(tmp_path / "kb.sqlite3"), service,
                       allow_model_calls=True, max_turns=4)
    assert result["tool_calls"] == 2
    assert service.calls == 3


def test_model_transport_failure_falls_back_to_local_read_tool(tmp_path):
    class OfflineService:
        config = {"chat_model": "fake"}
        chat_model = "fake"

        def post(self, route, payload):
            raise RuntimeError("sanitized transport failure")

    result = run_agent("查看知识库", KnowledgeIndex(tmp_path / "kb.sqlite3"),
        OfflineService(), allow_model_calls=True, local_tool="kb_sources")
    assert result["model_used"] is False
    assert result["mode"] == "本地只读工具模式"
    assert result["fallback_reason"] == "RuntimeError"
    assert "退回" in result["notice"]
