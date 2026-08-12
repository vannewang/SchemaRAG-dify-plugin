"""轻量图表类型推断测试。"""

from tools.llm_plot_lite import LlmPlotLiteTool


def build_tool() -> LlmPlotLiteTool:
    """绕过 Dify 运行时初始化，仅测试无状态推断方法。"""
    return object.__new__(LlmPlotLiteTool)


def test_category_comparison_ignores_time_filter_keywords():
    """时间范围不能把算法类别对比误判为折线图。"""
    tool = build_tool()
    rows = [
        {"category": "未带安全帽", "value": 9.0},
        {"category": "人员进出统计", "value": 0.86},
    ]

    chart_type = tool._choose_chart_type(
        "计算近一周各算法平均每天的告警数量",
        "SELECT algorithm_name, avg_daily_alarm_count FROM result",
        rows,
        "category",
        "value",
        "algorithm_name",
    )

    assert chart_type == "bar"


def test_time_dimension_uses_line_chart():
    """原始维度为日期时使用折线图。"""
    tool = build_tool()
    rows = [
        {"category": "2026-08-08", "value": 60},
        {"category": "2026-08-11", "value": 6},
    ]

    chart_type = tool._choose_chart_type(
        "查询近一周每天的告警数量趋势",
        "SELECT day_period, alarm_count FROM result",
        rows,
        "category",
        "value",
        "day_period",
    )

    assert chart_type == "line"


def test_legacy_call_detects_time_axis_from_values():
    """旧工作流未传原始字段时，根据横轴值识别时间序列。"""
    tool = build_tool()
    rows = [
        {"category": "2026-08", "value": 10},
        {"category": "2026-09", "value": 12},
    ]

    chart_type = tool._choose_chart_type(
        "每月告警数量",
        "SELECT category, value FROM result",
        rows,
        "category",
        "value",
    )

    assert chart_type == "line"


def test_proportion_semantics_use_pie_chart():
    """少量类别的占比查询优先使用饼图。"""
    tool = build_tool()
    rows = [
        {"category": "危急", "value": 30},
        {"category": "紧急", "value": 20},
    ]

    chart_type = tool._choose_chart_type(
        "统计近一周告警等级占比",
        "SELECT alarm_level, percentage FROM result",
        rows,
        "category",
        "value",
        "alarm_level",
    )

    assert chart_type == "pie"


def test_distribution_semantics_remain_pie_chart():
    """保留既有的少量类别分布饼图行为。"""
    tool = build_tool()
    rows = [
        {"category": "危急", "value": 30},
        {"category": "紧急", "value": 20},
    ]

    chart_type = tool._choose_chart_type(
        "统计告警等级分布",
        "SELECT alarm_level, alarm_count FROM result",
        rows,
        "category",
        "value",
        "alarm_level",
    )

    assert chart_type == "pie"


def test_category_values_remain_bar_without_source_field():
    """旧工作流中的类别数据不因“近一周”而变成折线图。"""
    tool = build_tool()
    rows = [
        {"category": "摄像机211", "value": 3.1},
        {"category": "摄像机105", "value": 0.9},
    ]

    chart_type = tool._choose_chart_type(
        "近一周各摄像机平均每天告警数量",
        "SELECT category, value FROM result",
        rows,
        "category",
        "value",
    )

    assert chart_type == "bar"
