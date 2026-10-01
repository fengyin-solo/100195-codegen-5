"""场站消防设施检验台账业务规则。

核心口径都收在这里，保证列表页、批量入账与运营概览看到同一套结果：
- 到期未检：设施未作废，且下次检验月份早于当前月份（按月比较）；
- 批量检验：同一场站的多条设施一次提交，逐条校验、逐条入账，单条失败不影响其他条目；
- 幂等：检验记录按（批次号, 设施ID）去重，同一批次重复提交不会多出记录。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "fire"
LOG_MODULE = "firelog"

REQUIRED_FIELDS = ["设施名称", "所属场站", "灭火器数量", "下次检验月份"]
STATUS_ORDER = ["待检验", "检验合格", "已作废"]
ACTION_RULES = {"作废设施": "已作废"}
ACTION_MESSAGES = {"作废设施": "设施已作废"}
NEGATIVE_ACTIONS = ["作废设施"]

# 灭火器压力表合理量程（MPa）：低于下限视为欠压、高于上限视为超压，都不得入账。
PRESSURE_MIN = 0.5
PRESSURE_MAX = 2.5
PRESSURE_RANGE_TEXT = f"{PRESSURE_MIN}~{PRESSURE_MAX} MPa"

DATE_FMT = "%Y-%m-%d"
MONTH_FMT = "%Y-%m"


def _current_month() -> str:
    return date.today().strftime(MONTH_FMT)


def _norm_date(value: Any) -> str | None:
    """把输入规范成 YYYY-MM-DD；无法解析时返回 None。"""
    try:
        return datetime.strptime(str(value).strip(), DATE_FMT).strftime(DATE_FMT)
    except (TypeError, ValueError):
        return None


def _norm_month(value: Any) -> str | None:
    """把输入规范成 YYYY-MM；无法解析时返回 None。"""
    try:
        return datetime.strptime(str(value).strip(), MONTH_FMT).strftime(MONTH_FMT)
    except (TypeError, ValueError):
        return None


def is_overdue(row: dict[str, Any]) -> bool:
    """到期未检：设施未作废，且下次检验月份已过当前月份。"""
    if row.get("status") == "已作废":
        return False
    next_month = _norm_month(row.get("下次检验月份"))
    return next_month is not None and next_month < _current_month()


def _parse_pressure(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class FireService:
    # ---- 台账查询 ----
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        station: str | None = None,
        status: str | None = None,
        overdue: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for row in rows:
            # 行上的待处理标记随时与到期口径同步，导出和详情看到的也是同一结论。
            row["pending"] = is_overdue(row)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("设施编号", "")) or keyword in str(row.get("设施名称", ""))
            ]
        if station:
            rows = [row for row in rows if station in str(row.get("所属场站", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if overdue is not None:
            rows = [row for row in rows if is_overdue(row) is overdue]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [{**row, "overdue": is_overdue(row)} for row in rows[start:start + size]]
        return page_rows, total

    def summary(self) -> dict[str, int]:
        """列表页统计卡片：到期未检数与运营概览的待处理口径完全一致。"""
        rows = store.rows(MODULE)
        month = _current_month()
        return {
            "total": len(rows),
            "overdue": sum(1 for row in rows if is_overdue(row)),
            "scrapped": sum(1 for row in rows if row.get("status") == "已作废"),
            "inspected_this_month": sum(
                1 for log in store.rows(LOG_MODULE) if str(log.get("检验日期", "")).startswith(month)
            ),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        row["pending"] = is_overdue(row)
        return {**row, "overdue": is_overdue(row)}

    # ---- 设施登记 ----
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]

        raw_count = str(values.get("灭火器数量")).strip()
        if not raw_count.isdigit() or int(raw_count) <= 0:
            return None, ["灭火器数量需为正整数"]
        next_month = _norm_month(values.get("下次检验月份"))
        if next_month is None:
            return None, ["下次检验月份格式应为 YYYY-MM"]

        last_date = values.get("上次检验日期")
        if last_date not in (None, ""):
            last_date = _norm_date(last_date)
            if last_date is None:
                return None, ["上次检验日期格式应为 YYYY-MM-DD"]

        pressure = values.get("压力表读数")
        if pressure not in (None, ""):
            pressure = _parse_pressure(pressure)
            if pressure is None:
                return None, ["压力表读数需为数字"]
            if not PRESSURE_MIN <= pressure <= PRESSURE_MAX:
                return None, [f"压力表读数超出合理范围（{PRESSURE_RANGE_TEXT}）"]

        rows = store.rows(MODULE)
        entry_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry: dict[str, Any] = {
            "id": entry_id,
            "设施编号": str(values.get("设施编号") or "").strip() or f"FIRE-{entry_id:04d}",
            "设施名称": str(values.get("设施名称")).strip(),
            "所属场站": str(values.get("所属场站")).strip(),
            "灭火器数量": int(raw_count),
            "上次检验日期": last_date or None,
            "压力表读数": pressure if pressure != "" else None,
            "下次检验月份": next_month,
            "abnormal": False,
        }
        entry["status"] = "检验合格" if last_date else STATUS_ORDER[0]
        entry["设施状态"] = entry["status"]
        entry["pending"] = is_overdue(entry)
        rows.append(entry)
        return entry, []

    # ---- 单条动作 ----
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"消防设施 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于消防设施可执行范围"
        target = ACTION_RULES[action]
        if entry.get("status") == target:
            return None, f"设施已处于「{target}」，无需重复操作"
        entry["status"] = target
        entry["设施状态"] = target
        entry["pending"] = is_overdue(entry)
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, ACTION_MESSAGES.get(action, f"消防设施已{action}")

    # ---- 批量检验入账 ----
    def inspect_batch(
        self,
        *,
        batch_id: str | None,
        inspect_date: str | None,
        next_month: str | None,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        batch_no = (batch_id or "").strip() or f"BAT-{datetime.now():%Y%m%d%H%M%S}"
        results: list[dict[str, Any]] = []
        recorded = failed = duplicated = 0

        if not items:
            return {
                "ok": False,
                "message": "本次提交没有需要检验的设施",
                "batch_id": batch_no,
                "recorded": 0,
                "failed": 0,
                "duplicated": 0,
                "results": [],
            }

        for item in items:
            outcome, message = self._inspect_one(
                batch_no=batch_no,
                item=item,
                default_date=inspect_date,
                default_month=next_month,
            )
            results.append({"id": item.get("id"), "ok": outcome != "failed", "message": message})
            if outcome == "recorded":
                recorded += 1
            elif outcome == "duplicated":
                duplicated += 1
            else:
                failed += 1

        return {
            "ok": failed == 0,
            "message": f"批次 {batch_no} 提交完成：入账 {recorded} 条，失败 {failed} 条，重复 {duplicated} 条",
            "batch_id": batch_no,
            "recorded": recorded,
            "failed": failed,
            "duplicated": duplicated,
            "results": results,
        }

    def _inspect_one(
        self,
        *,
        batch_no: str,
        item: dict[str, Any],
        default_date: str | None,
        default_month: str | None,
    ) -> tuple[str, str]:
        """校验并入账单条设施；任何一条失败都只影响自己，其余照常入账。

        返回 (outcome, message)，outcome ∈ {recorded, duplicated, failed}。
        """
        entry_id = item.get("id")
        row = store.find(MODULE, int(entry_id)) if str(entry_id or "").isdigit() else None
        if row is None:
            return "failed", f"设施 {entry_id} 不存在或已归档，本条未入账"
        label = str(row.get("设施编号") or entry_id)
        if row.get("status") == "已作废":
            return "failed", f"设施 {label} 已作废，不能登记检验"

        # 幂等：同一批次号对同一设施只入账一次，重复提交直接跳过。
        if self._find_log(batch_no, int(row["id"])) is not None:
            return "duplicated", "重复提交：该批次此设施已入账，未重复记录"

        inspect_date = _norm_date(item.get("inspect_date") or default_date or "")
        if inspect_date is None:
            return "failed", f"设施 {label} 缺少检验日期或格式不是 YYYY-MM-DD，本条未入账"
        next_month = _norm_month(item.get("next_month") or default_month or "")
        if next_month is None:
            return "failed", f"设施 {label} 缺少下次检验月份或格式不是 YYYY-MM，本条未入账"

        pressure = _parse_pressure(item.get("pressure"))
        if pressure is None:
            return "failed", f"设施 {label} 压力表读数缺失或不是数字，本条未入账"
        if not PRESSURE_MIN <= pressure <= PRESSURE_MAX:
            return "failed", f"设施 {label} 压力表读数 {pressure} 超出合理范围（{PRESSURE_RANGE_TEXT}），本条未入账"

        last_date = _norm_date(row.get("上次检验日期"))
        if last_date is not None and inspect_date < last_date:
            return "failed", f"设施 {label} 检验日期 {inspect_date} 早于上次检验日期 {last_date}，本条未入账"
        if next_month < inspect_date[:7]:
            return "failed", f"设施 {label} 下次检验月份 {next_month} 早于本次检验月份，本条未入账"

        row["上次检验日期"] = inspect_date
        row["压力表读数"] = pressure
        row["下次检验月份"] = next_month
        row["status"] = "检验合格"
        row["设施状态"] = "检验合格"
        row["pending"] = is_overdue(row)

        logs = store.rows(LOG_MODULE)
        log_id = max((int(log.get("id", 0)) for log in logs), default=0) + 1
        logs.append({
            "id": log_id,
            "status": "已入账",
            "pending": False,
            "abnormal": False,
            "记录编号": f"FLOG-{log_id:04d}",
            "批次号": batch_no,
            "设施ID": int(row["id"]),
            "设施编号": row.get("设施编号"),
            "所属场站": row.get("所属场站"),
            "检验日期": inspect_date,
            "压力表读数": pressure,
            "下次检验月份": next_month,
            "检验结论": "合格",
        })
        return "recorded", f"设施 {label} 检验已入账"

    def _find_log(self, batch_no: str, entry_id: int) -> dict[str, Any] | None:
        for log in store.rows(LOG_MODULE):
            if log.get("批次号") == batch_no and int(log.get("设施ID", 0)) == entry_id:
                return log
        return None

    def list_logs(
        self,
        *,
        batch_id: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(LOG_MODULE)
        if batch_id:
            rows = [log for log in rows if log.get("批次号") == batch_id]
        if keyword:
            rows = [log for log in rows if keyword in str(log.get("设施编号", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total


# 概览的“待处理”直接复用到期未检口径，台账和概览的到期未检数天然一致。
store.register_pending_rule(MODULE, is_overdue)
