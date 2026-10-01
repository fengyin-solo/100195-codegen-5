"""消防设施检验台账业务规则。

口径约定（台账页与运营概览共用，避免两边数字对不上）：
- 到期未检：设施的“下次检验月份”（YYYY-MM）不晚于当前月，即视为到期未检。
- 整批检验：一次提交只允许同一场站的多条设施；逐条校验、逐条入账，
  某一条（例如压力表读数超合理范围）失败不影响同批其他设施。
- 幂等：同一批次号重复提交不会再追加检验记录，直接回放上一次的逐条结果。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import _register_pending_counter, store

MODULE = "fire"
RECORD_MODULE = "fire_inspection"
REQUIRED_FIELDS = ["设施编号", "所属场站", "设施类型", "灭火器数量", "上次检验日期", "压力表读数", "下次检验月份"]

# 灭火器压力表正常区域为绿区，按常用表计量程约定为 1.00~1.40 MPa。
PRESSURE_MIN = 1.00
PRESSURE_MAX = 1.40


def current_month() -> str:
    """当前月份（YYYY-MM）。到期判定的唯一时间来源。"""
    return date.today().strftime("%Y-%m")


def parse_month(value: Any) -> str | None:
    """把“下次检验月份”归一成 YYYY-MM；无法识别时返回 None。"""
    text = str(value or "").strip()
    if len(text) >= 7 and text[4] == "-":
        head = text[:7]
        try:
            year, month = head.split("-")
            if len(year) == 4 and 1 <= int(month) <= 12:
                return head
        except ValueError:
            return None
    return None


def parse_date(value: Any) -> date | None:
    """解析 YYYY-MM-DD 检验日期；兼容只给到月份的写法。"""
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def is_overdue(row: dict[str, Any], month: str | None = None) -> bool:
    month = month or current_month()
    next_month = parse_month(row.get("下次检验月份"))
    return next_month is not None and next_month <= month


@_register_pending_counter(MODULE)
def count_overdue(rows: list[dict[str, Any]]) -> int:
    """到期未检数：概览待处理量与台账统计卡片都调它，保证两边一致。"""
    month = current_month()
    return sum(1 for row in rows if is_overdue(row, month))


def _refresh_status(entry: dict[str, Any]) -> None:
    """检验完成后按下次检验月份重算状态与待处理标记。"""
    overdue = is_overdue(entry)
    entry["pending"] = overdue
    entry["status"] = "到期未检" if overdue else "正常"


class FireService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        station: str | None = None,
        overdue: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        month = current_month()
        rows = store.rows(MODULE)
        # 列表状态实时按月份重算，避免检验后还挂着旧状态。
        for row in rows:
            _refresh_status(row)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设施编号", ""))]
        if station:
            rows = [row for row in rows if str(row.get("所属场站", "")) == station]
        if overdue is not None:
            rows = [row for row in rows if is_overdue(row, month) == overdue]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> dict[str, int]:
        """台账页统计卡片；到期未检数与 /api/overview 里 fire 模块的 pending 同源。"""
        rows = store.rows(MODULE)
        overdue = count_overdue(rows)
        return {
            "total": len(rows),
            "overdue": overdue,
            "stations": len({str(row.get("所属场站", "")) for row in rows if row.get("所属场站")}),
            "inspections": len(store.rows(RECORD_MODULE)),
        }

    def stations(self) -> list[str]:
        return sorted({str(row.get("所属场站", "")) for row in store.rows(MODULE) if row.get("所属场站")})

    def list_records(self, batch_no: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(RECORD_MODULE)
        if batch_no:
            rows = [row for row in rows if row.get("批次号") == batch_no]
        return rows

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if str(values.get(field) or "").strip() == ""]
        if missing:
            return None, missing
        rows = store.rows(MODULE)

        pressure = self._parse_float(values.get("压力表读数"))
        if pressure is None or not (PRESSURE_MIN <= pressure <= PRESSURE_MAX):
            return None, [f"压力表读数需在 {PRESSURE_MIN:.2f}~{PRESSURE_MAX:.2f} MPa 之间"]
        count = self._parse_int(values.get("灭火器数量"))
        if count is None or count <= 0:
            return None, ["灭火器数量需为正整数"]
        if parse_date(values.get("上次检验日期")) is None:
            return None, ["上次检验日期格式应为 YYYY-MM-DD"]
        if parse_month(values.get("下次检验月份")) is None:
            return None, ["下次检验月份格式应为 YYYY-MM"]

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["压力表读数"] = pressure
        entry["灭火器数量"] = count
        _refresh_status(entry)
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def submit_batch(
        self,
        *,
        batch_no: str,
        station: str,
        inspect_date: str,
        next_month: str,
        items: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, int, str]:
        """整批提交检验结果。

        返回 (批次结果, HTTP状态码, 批次级错误信息)。
        批次级问题（空批次/跨场站）整体拒绝；条目级问题逐条失败、其余照常入账。
        """
        records = store.rows(RECORD_MODULE)

        if not items:
            return None, 400, "批次里没有可提交的设施，请先勾选"

        parsed_date = parse_date(inspect_date)
        if parsed_date is None:
            return None, 400, "检验日期格式应为 YYYY-MM-DD"
        parsed_month = parse_month(next_month)
        if parsed_month is None:
            return None, 400, "下次检验月份格式应为 YYYY-MM"
        if parsed_month < parsed_date.strftime("%Y-%m"):
            return None, 400, "下次检验月份不能早于检验日期所在月份"

        facility_rows = store.rows(MODULE)

        # 跨场站属于整批操作前提不成立：整批拦下，提示用户分批提交。
        for item in items:
            entry = self._find_facility(item.get("facility_id"), facility_rows)
            if entry is None:
                return None, 404, f"设施 {item.get('facility_id')} 不存在或已注销"
            if str(entry.get("所属场站", "")) != station:
                return None, 400, (
                    f"设施 {entry.get('设施编号')} 不属于场站「{station}」，"
                    "同一次提交只能选择同一场站的设施"
                )

        # 幂等：同一批次号重复提交时，已经入账过的设施直接跳过、不再追加记录；
        # 若整批设施都入账过，原样回放上一次的提交结果。
        recorded_facility_ids = {
            next(
                (int(r.get("id", 0)) for r in facility_rows if r.get("设施编号") == row.get("设施编号")),
                0,
            )
            for row in records
            if row.get("批次号") == batch_no
        }
        submitted_ids: list[int] = [
            fid for fid in (self._parse_int(item.get("facility_id")) for item in items) if fid is not None
        ]
        if recorded_facility_ids and submitted_ids and all(fid in recorded_facility_ids for fid in submitted_ids):
            return self._replay_batch(batch_no, set(submitted_ids), facility_rows), 200, ""

        seen: set[int] = set()
        results: list[dict[str, Any]] = []
        success = 0
        failure = 0
        skipped = 0
        for item in items:
            facility_id = int(item.get("facility_id", 0))
            entry = self._find_facility(facility_id, facility_rows)
            if entry is None:
                failure += 1
                results.append(self._item_result(facility_id, None, False, "设施不存在或已注销"))
                continue
            if facility_id in seen:
                failure += 1
                results.append(self._item_result(facility_id, str(entry.get("设施编号")), False, "同一设施在批次内重复出现，只能提交一次"))
                continue
            seen.add(facility_id)
            if facility_id in recorded_facility_ids:
                # 同一批次已入账：不拦截整批，但这条不会再多出记录。
                skipped += 1
                results.append(self._item_result(
                    facility_id, str(entry.get("设施编号")), True,
                    "该设施在本批次已入账，未重复生成记录", duplicated=True,
                ))
                continue

            pressure = self._parse_float(item.get("pressure"))
            if pressure is None or not (PRESSURE_MIN <= pressure <= PRESSURE_MAX):
                # 读数超合理范围：只拦这一条，其他条目继续入账。
                failure += 1
                results.append(self._item_result(
                    facility_id, str(entry.get("设施编号")), False,
                    f"压力表读数 {item.get('pressure')} MPa 超出合理范围（{PRESSURE_MIN:.2f}~{PRESSURE_MAX:.2f} MPa），本条不入账",
                ))
                continue

            count = self._parse_int(item.get("extinguisher_count"))
            if count is not None and count <= 0:
                failure += 1
                results.append(self._item_result(facility_id, str(entry.get("设施编号")), False, "灭火器数量需为正整数，本条不入账"))
                continue
            count = count if count is not None else int(entry.get("灭火器数量", 0) or 0)

            last_date = parse_date(entry.get("上次检验日期"))
            if last_date is not None and parsed_date < last_date:
                failure += 1
                results.append(self._item_result(
                    facility_id, str(entry.get("设施编号")), False,
                    f"检验日期 {inspect_date} 早于上次检验日期 {entry.get('上次检验日期')}，本条不入账",
                ))
                continue

            entry["上次检验日期"] = inspect_date
            entry["压力表读数"] = pressure
            entry["灭火器数量"] = count
            entry["下次检验月份"] = parsed_month
            entry["abnormal"] = False
            _refresh_status(entry)

            record = {
                "id": max((int(row.get("id", 0)) for row in records), default=0) + 1,
                "批次号": batch_no,
                "设施编号": entry.get("设施编号"),
                "所属场站": station,
                "检验日期": inspect_date,
                "下次检验月份": parsed_month,
                "压力表读数": pressure,
                "灭火器数量": count,
            }
            records.append(record)
            success += 1
            results.append(self._item_result(facility_id, str(entry.get("设施编号")), True, "检验结果已入账"))

        batch_result = {
            "ok": failure == 0,
            "message": (
                f"批次 {batch_no} 提交完成：新入账 {success} 条，失败 {failure} 条"
                + (f"，跳过已入账 {skipped} 条" if skipped else "")
            ),
            "batch_no": batch_no,
            "success_count": success,
            "failure_count": failure,
            "skipped_count": skipped,
            "duplicated": success == 0 and skipped > 0 and failure == 0,
            "results": results,
        }
        return batch_result, 200, ""

    def _replay_batch(
        self,
        batch_no: str,
        facility_ids: set[int],
        facility_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """整批重复提交：不新增任何记录，只回放上一次的入账条目。"""
        results = []
        for facility_id in sorted(facility_ids):
            entry = next((row for row in facility_rows if int(row.get("id", 0)) == facility_id), None)
            results.append(self._item_result(
                facility_id,
                str(entry.get("设施编号")) if entry else None,
                True,
                "该批次已提交过，未重复生成记录",
                duplicated=True,
            ))
        return {
            "ok": True,
            "message": f"批次 {batch_no} 已提交过，本次为重复提交，未新增检验记录（{len(results)} 条）",
            "batch_no": batch_no,
            "success_count": 0,
            "failure_count": 0,
            "skipped_count": len(results),
            "duplicated": True,
            "results": results,
        }

    @staticmethod
    def _find_facility(facility_id: Any, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        try:
            target = int(facility_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return next((row for row in rows if int(row.get("id", 0)) == target), None)

    @staticmethod
    def _item_result(
        facility_id: Any,
        facility_no: str | None,
        ok: bool,
        message: str,
        *,
        duplicated: bool = False,
    ) -> dict[str, Any]:
        return {
            "facility_id": facility_id,
            "facility_no": facility_no,
            "ok": ok,
            "duplicated": duplicated,
            "message": message,
        }

    @staticmethod
    def _parse_float(value: Any) -> float | None:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
