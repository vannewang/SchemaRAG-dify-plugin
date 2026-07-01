from collections.abc import Generator
from typing import Any
import json
import logging
import re

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

logger = logging.getLogger(__name__)


class LlmPlotLiteTool(Tool):
    """Generate frontend-renderable chart JSON without LLM or external chart APIs."""

    MAX_ROWS = 200

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        try:
            user_question = str(tool_parameters.get("user_question") or "").strip()
            sql_query = str(tool_parameters.get("sql_query") or "").strip()
            title = str(tool_parameters.get("title") or "").strip() or user_question or "数据图表"
            rows = self._parse_rows(tool_parameters.get("data"))

            if not rows:
                yield self.create_text_message(json.dumps({
                    "render_type": "empty",
                    "can_render": False,
                    "chart_type": "",
                    "title": title,
                    "message": "没有可用于渲染图表的数据",
                    "data": [],
                    "table_rows": [],
                    "option": None,
                }, ensure_ascii=False))
                return

            rows = [self._normalize_row(row) for row in rows if isinstance(row, dict)]
            rows = [row for row in rows if row]
            rows = rows[: self.MAX_ROWS]
            if not rows:
                yield self.create_text_message(json.dumps({
                    "render_type": "empty",
                    "can_render": False,
                    "chart_type": "",
                    "title": title,
                    "message": "没有可用于渲染图表的数据",
                    "data": [],
                    "table_rows": [],
                    "option": None,
                }, ensure_ascii=False))
                return

            fields = list(rows[0].keys())
            numeric_fields = [field for field in fields if self._is_numeric_field(rows, field)]
            dimension_fields = [field for field in fields if field not in numeric_fields]

            x_field = self._choose_x_field(fields, dimension_fields, user_question, sql_query)
            y_field = self._choose_y_field(fields, numeric_fields)
            chart_type = self._choose_chart_type(user_question, sql_query, rows, x_field, y_field)
            field_labels = {field: self._field_label(field) for field in fields}

            if not x_field or not y_field:
                result = {
                    "render_type": "table",
                    "can_render": True,
                    "chart_type": "table",
                    "title": title,
                    "x_field": x_field or "",
                    "y_field": y_field or "",
                    "series_field": "",
                    "x_label": self._field_label(x_field) if x_field else "",
                    "y_label": self._field_label(y_field) if y_field else "",
                    "series_label": "",
                    "field_labels": field_labels,
                    "data": rows,
                    "table_rows": rows,
                    "option": None,
                    "message": "数据缺少可用于图表的维度或数值字段，建议渲染表格",
                }
                yield self.create_text_message(json.dumps(result, ensure_ascii=False))
                return

            series_field = self._choose_series_field(fields, dimension_fields, x_field, user_question, sql_query)
            option = self._build_echarts_option(title, rows, chart_type, x_field, y_field, series_field)

            result = {
                "render_type": "chart",
                "can_render": True,
                "renderer": "echarts",
                "schema_version": "1.0",
                "chart_type": chart_type,
                "title": title,
                "x_field": x_field,
                "y_field": y_field,
                "series_field": series_field or "",
                "x_label": self._field_label(x_field),
                "y_label": self._field_label(y_field),
                "series_label": self._field_label(series_field) if series_field else "",
                "field_labels": field_labels,
                "data": rows,
                "table_rows": rows,
                "option": option,
                "echarts_option": option,
                "message": "",
            }
            yield self.create_text_message(json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            logger.exception("llm_plot_lite failed")
            yield self.create_text_message(json.dumps({
                "render_type": "error",
                "can_render": False,
                "chart_type": "",
                "title": str(tool_parameters.get("title") or "图表生成失败"),
                "message": f"轻量图表配置生成失败: {exc}",
                "data": [],
                "table_rows": [],
                "option": None,
            }, ensure_ascii=False))

    def _parse_rows(self, data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "rows", "result", "results"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        text = str(data).strip()
        if not text:
            return []
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.I)
        if fence:
            text = fence.group(1).strip()
        match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
        if match:
            text = match.group(1)
        value = json.loads(text)
        return self._parse_rows(value)

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {str(key): self._normalize_value(value) for key, value in row.items()}

    def _normalize_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def _to_float(self, value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None

    def _is_numeric_field(self, rows: list[dict[str, Any]], field: str) -> bool:
        checked = 0
        numeric = 0
        for row in rows[:30]:
            value = row.get(field)
            if value is None or value == "":
                continue
            checked += 1
            if self._to_float(value) is not None:
                numeric += 1
        return checked > 0 and checked == numeric

    def _choose_x_field(self, fields: list[str], dimension_fields: list[str], question: str, sql: str) -> str:
        text = f"{question} {sql}".lower()
        preferred = [
            "day_period", "month_period", "year_period", "readable_create_time",
            "date", "time", "category", "name", "type",
            "日期", "时间", "算法", "名称", "类型", "区域", "设备", "摄像机",
        ]
        if any(word in text for word in ("趋势", "近一周", "本周", "按天", "按月", "按年", "trend")):
            preferred = ["day_period", "month_period", "year_period", "readable_create_time", "date", "time", "日期", "时间"] + preferred
        for keyword in preferred:
            for field in dimension_fields or fields:
                if keyword.lower() in field.lower():
                    return field
        return (dimension_fields or fields or [""])[0]

    def _choose_y_field(self, fields: list[str], numeric_fields: list[str]) -> str:
        preferred = ["alarm_count", "count", "total", "sum", "num", "value", "amount", "数量", "次数", "总数", "告警", "占比"]
        for keyword in preferred:
            for field in numeric_fields:
                if keyword.lower() in field.lower():
                    return field
        return (numeric_fields or [""])[0]

    def _choose_series_field(
        self,
        fields: list[str],
        dimension_fields: list[str],
        x_field: str,
        question: str,
        sql: str,
    ) -> str:
        text = f"{question} {sql}".lower()
        x_lower = x_field.lower()
        is_time_x = any(keyword in x_lower for keyword in ("time", "date", "period", "日期", "时间"))
        if not is_time_x and not any(word in text for word in ("各个", "各", "分别", "对比", "趋势", "algorithm", "算法")):
            return ""
        preferred = ["algorithm_name", "algorithm_id", "算法", "名称", "类型", "category", "name"]
        for keyword in preferred:
            for field in dimension_fields:
                if field != x_field and keyword.lower() in field.lower():
                    return field
        for field in dimension_fields:
            if field != x_field:
                return field
        return ""

    def _choose_chart_type(self, question: str, sql: str, rows: list[dict[str, Any]], x_field: str, y_field: str) -> str:
        text = f"{question} {sql} {x_field}".lower()
        if any(word in text for word in ("趋势", "走势", "变化", "按天", "按月", "按年", "近一周", "本周", "trend", "day_period", "month_period", "year_period", "time", "date")):
            return "line"
        if any(word in text for word in ("占比", "比例", "分布", "pie")) and len(rows) <= 12:
            return "pie"
        return "bar"

    def _build_echarts_option(
        self,
        title: str,
        rows: list[dict[str, Any]],
        chart_type: str,
        x_field: str,
        y_field: str,
        series_field: str,
    ) -> dict[str, Any]:
        x_label = self._field_label(x_field)
        y_label = self._field_label(y_field)
        if chart_type == "pie":
            return {
                "title": {"text": title},
                "tooltip": {"trigger": "item"},
                "legend": {"type": "scroll", "bottom": 0},
                "series": [{
                    "type": "pie",
                    "radius": "60%",
                    "data": [
                        {"name": str(row.get(x_field, "")), "value": self._to_float(row.get(y_field)) or 0}
                        for row in rows
                    ],
                }],
            }

        categories = self._ordered_unique([str(row.get(x_field, "")) for row in rows if row.get(x_field) is not None])
        series = []
        if series_field:
            names = self._ordered_unique([str(row.get(series_field, "")) for row in rows if row.get(series_field) is not None])
            for name in names:
                series.append({
                    "name": name,
                    "type": chart_type,
                    "data": self._aggregate_values(rows, categories, x_field, y_field, series_field, name),
                    **({"smooth": True} if chart_type == "line" else {}),
                })
        else:
            series.append({
                "name": y_label,
                "type": chart_type,
                "data": self._aggregate_values(rows, categories, x_field, y_field),
                **({"smooth": True} if chart_type == "line" else {}),
            })

        option = {
            "title": {"text": title},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 40, "right": 24, "top": 56, "bottom": 72, "containLabel": True},
            "xAxis": {"type": "category", "name": x_label, "data": categories},
            "yAxis": {"type": "value", "name": y_label},
            "series": series,
        }
        if len(series) > 1:
            option["legend"] = {"type": "scroll", "bottom": 0}
        return option

    def _field_label(self, field: str) -> str:
        labels = {
            "day_period": "日期",
            "month_period": "月份",
            "year_period": "年份",
            "readable_create_time": "告警时间",
            "create_time": "创建时间",
            "alarm_time": "告警时间戳",
            "alarm_count": "告警数量",
            "count": "数量",
            "total": "总数",
            "value": "数值",
            "category": "分类",
            "algorithm_name": "算法名称",
            "algorithm_id": "算法ID",
            "camera_name": "摄像机名称",
            "device_name": "设备名称",
            "regional_name": "区域名称",
            "alarm_level": "告警等级",
            "alarm_status": "告警状态",
            "alarm_info": "告警信息",
        }
        if not field:
            return ""
        if field in labels:
            return labels[field]
        text = field.replace("_", " ")
        return text[:1].upper() + text[1:]

    def _ordered_unique(self, values: list[str]) -> list[str]:
        result = []
        seen = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _aggregate_values(
        self,
        rows: list[dict[str, Any]],
        categories: list[str],
        x_field: str,
        y_field: str,
        series_field: str = "",
        series_name: str = "",
    ) -> list[float]:
        totals = {category: 0.0 for category in categories}
        for row in rows:
            if series_field and str(row.get(series_field, "")) != series_name:
                continue
            category = str(row.get(x_field, ""))
            if category not in totals:
                continue
            totals[category] += self._to_float(row.get(y_field)) or 0
        return [totals[category] for category in categories]
