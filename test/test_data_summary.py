import json

from tools.data_summary import DataSummaryTool


def make_tool():
    return object.__new__(DataSummaryTool)


def test_rows_payload_is_truncated_on_complete_rows():
    tool = make_tool()
    rows = [{"id": index, "value": "x" * 1200} for index in range(100)]
    content = json.dumps(
        {"rows": rows, "pagination": {"mode": "detail"}},
        ensure_ascii=False,
    )

    result, was_truncated = tool._truncate_data_if_needed(content, 40000)
    parsed = json.loads(result)

    assert was_truncated is True
    assert len(result) <= 40000
    assert 0 < len(parsed["rows"]) < len(rows)
    assert parsed["pagination"]["source_rows_count"] == len(rows)
    assert parsed["pagination"]["summary_rows_count"] == len(parsed["rows"])
    assert parsed["pagination"]["summary_rows_truncated"] is True
    assert parsed["pagination"]["oversized_single_row"] is False


def test_json_prefix_is_preserved():
    tool = make_tool()
    rows = [{"id": index, "value": "x" * 1200} for index in range(100)]
    content = "JSON:\n" + json.dumps({"rows": rows}, ensure_ascii=False)

    result, was_truncated = tool._truncate_data_if_needed(content, 40000)

    assert was_truncated is True
    assert result.startswith("JSON:\n")
    assert len(result) <= 40000
    json.loads(result.split("\n", 1)[1])


def test_oversized_single_row_is_not_split():
    tool = make_tool()
    content = json.dumps(
        {"rows": [{"value": "x" * 50000}], "pagination": {}},
        ensure_ascii=False,
    )

    result, was_truncated = tool._truncate_data_if_needed(content, 40000)
    parsed = json.loads(result)

    assert was_truncated is True
    assert parsed["rows"] == []
    assert parsed["pagination"]["oversized_single_row"] is True


def test_json_list_is_truncated_as_valid_json():
    tool = make_tool()
    content = json.dumps(
        [{"id": index, "value": "x" * 1200} for index in range(100)],
        ensure_ascii=False,
    )

    result, was_truncated = tool._truncate_data_if_needed(content, 40000)
    parsed = json.loads(result)

    assert was_truncated is True
    assert len(result) <= 40000
    assert 0 < len(parsed) < 100


def test_truncated_result_passes_input_validation():
    tool = make_tool()
    content = json.dumps(
        {"rows": [{"value": "x" * 1200} for _ in range(100)]},
        ensure_ascii=False,
    )

    result, _ = tool._truncate_data_if_needed(content, tool.MAX_DATA_LENGTH)
    is_valid, error = tool._validate_input_data(result, "query")

    assert is_valid is True
    assert error == ""
