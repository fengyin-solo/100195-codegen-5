"""消防设施检验台账接口：按场站登记设施、整批提交检验、查询检验流水。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchInspectionResult,
    EntryPayload,
    FireInspectionBatchPayload,
    PageResult,
)
from app.services.fire import FireService

router = APIRouter(prefix="/api/fire", tags=["消防设施检验"])

service = FireService()


@router.get("/stats")
def get_stats() -> dict[str, int]:
    """台账页统计卡片；到期未检数与运营概览共用同一份口径。"""
    return service.stats()


@router.get("/stations")
def get_stations() -> dict[str, list[str]]:
    """场站下拉选项：取自已登记设施，保证整批提交只能选同一场站。"""
    return {"items": service.stations()}


@router.get("/inspections")
def list_inspections(batch_no: str | None = None) -> dict[str, Any]:
    """检验流水：可按批次号回查一次整批提交落了哪些记录。"""
    items = service.list_records(batch_no=batch_no)
    return {"total": len(items), "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按设施编号检索"),
    station: str | None = Query(default=None, description="按所属场站精确过滤"),
    overdue: bool | None = Query(default=None, description="true 只看到期未检，false 只看在检"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按设施编号、场站与到期状态过滤消防设施；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, station=station, overdue=overdue, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出消防设施台账：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "fire", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条消防设施明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"消防设施 {entry_id} 不存在或已注销")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """按场站登记一件消防设施（灭火器数量、检验日期、压力表读数、下次检验月份）。"""
    entry, error = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=f"登记失败：{'、'.join(error)}")
    return ActionResult(ok=True, message="消防设施已登记", entry=entry)


@router.post("/inspections/batch", response_model=BatchInspectionResult)
def submit_batch(payload: FireInspectionBatchPayload) -> BatchInspectionResult:
    """整批提交同一场站多条设施的检验结果，逐条成功或失败，互不连坐。

    压力表读数超合理范围、检验日期早于上次检验等问题只拦对应条目；
    同一批次号重复提交不会多出检验记录。
    """
    result, status_code, message = service.submit_batch(
        batch_no=payload.batch_no,
        station=payload.station,
        inspect_date=payload.inspect_date,
        next_month=payload.next_month,
        items=[item.model_dump() for item in payload.items],
    )
    if result is None:
        # 批次级问题（空批次、跨场站等）：整批拒绝，由统一异常处理返回 detail。
        raise HTTPException(status_code=status_code, detail=message)
    return BatchInspectionResult(**result)
