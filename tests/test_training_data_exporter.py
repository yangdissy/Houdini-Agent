from houdini_agent.utils.training_data_exporter import ChatTrainingExporter


def test_tool_message_strips_injected_guidance_and_keeps_long_result(tmp_path):
    exporter = ChatTrainingExporter(tmp_path)
    content = (
        "x" * 1500
        + "\n[注意：上述工具调用返回了错误，请分析后重试。]"
        + "\n[重要：你的下一条回复必须以 <think> 开始。]"
    )

    result = exporter._convert_tool_message({"role": "tool", "content": content})

    assert result is not None
    assert result["content"] == "x" * 1500


def test_finalize_sample_drops_context_before_first_user(tmp_path):
    exporter = ChatTrainingExporter(tmp_path)
    system = {"role": "system", "content": "system"}
    context = [
        {"role": "assistant", "content": "orphaned answer"},
        {"role": "tool", "tool_call_id": "orphaned", "content": "orphaned result"},
    ]
    current = [
        {"role": "user", "content": "build a box"},
        {"role": "assistant", "content": "done"},
    ]

    sample = exporter._finalize_sample(system, context, current)

    assert sample is not None
    assert [message["role"] for message in sample["messages"]] == [
        "system",
        "user",
        "assistant",
    ]


def test_unpaired_tool_uses_only_valid_ascii_function_name(tmp_path):
    exporter = ChatTrainingExporter(tmp_path)

    invalid = exporter._validate_tool_calls([
        {"role": "tool", "tool_call_id": "missing", "content": "已截取视口快照: ok"}
    ])
    valid = exporter._validate_tool_calls([
        {"role": "tool", "tool_call_id": "missing", "content": "capture_viewport: ok"}
    ])

    assert invalid[0]["tool_calls"][0]["function"]["name"] == "unknown_tool"
    assert valid[0]["tool_calls"][0]["function"]["name"] == "capture_viewport"


def test_tool_result_is_truncated_at_2000_characters(tmp_path):
    exporter = ChatTrainingExporter(tmp_path)

    result = exporter._convert_tool_message({"role": "tool", "content": "x" * 2500})

    assert result is not None
    assert len(result["content"]) == 2000