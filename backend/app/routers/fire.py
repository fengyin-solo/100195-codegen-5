"""消防设施检验台账接口：按场站登记设施、挑到期未检、批量提交检验结果。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, FireInspectPayload, FireInspectResult, PageResult
from app.services.fire import FireService

router = APIRouter(prefix="/api/fire", tags=["消防设施"])

service = FireService()

LIST_FIELDS = ["设施编号", "设施名称", "所属场站", "灭火器数量", "上次检验日期", "压力表读数", "下次检验月份", "设施状态"]
STATUSES = ["待检验", "检验合格", "已作废"]

OVERDUE_TRUE = {"true", "1", "是"}
OVERDUE_FALSE = {"false", "0", "否"}


def _parse_overdue(raw: str | None) -> bool | None:
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    if value in OVERDUE_TRUE:
        return True
    if value in OVERDUE_FALSE:
        return False
    return None


@router.get("/summary")
def summary() -> dict[str, int]:
    """台账统计卡片：到期未检数与运营概览的待处理口径一致。"""
    return service.summary()


@router.get("/logs")
def list_logs(
    batch_id: str | None = Query(default=None, description="按批次号检索检验记录"),
    keyword: str | None = Query(default=None, description="按设施编号检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """检验入账记录：同一批次重复提交不会产生新记录。"""
    items, total = service.list_logs(batch_id=batch_id, keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出消防设施台账：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "fire", "total": total, "items": items}


@router.post("/inspect", response_model=FireInspectResult)
def inspect_batch(payload: FireInspectPayload) -> FireInspectResult:
    """一次提交同一场站多条设施的检验结果，逐条返回成功或失败。

    单条压力表读数超出合理范围只拦这一条；检验日期早于上次检验的条目单独拦截；
    同一批次号重复提交不会多出记录。
    """
    result = service.inspect_batch(
        batch_id=payload.batch_id,
        inspect_date=payload.inspect_date,
        next_month=payload.next_month,
        items=[item.model_dump() for item in payload.items],
    )
    return FireInspectResult(**result)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按设施编号或名称检索"),
    station: str | None = Query(default=None, description="按所属场站检索"),
    status: str | None = Query(default=None, description="待检验、检验合格、已作废"),
    overdue: str | None = Query(default=None, description="传 true 时整批挑出到期未检设施"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按场站、状态与到期口径过滤消防设施列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        station=station,
        status=status,
        overdue=_parse_overdue(overdue),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条消防设施明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"消防设施 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条消防设施，缺字段或数值不合理时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="消防设施已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条设施执行作废设施等动作；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
