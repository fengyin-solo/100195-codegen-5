"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any, Callable

from app.seed import SEED_ROWS

# 内部使用的辅助表：不进入运营概览的模块列表与卡片汇总。
HIDDEN_TABLES = {"fire_inspection"}

# 部分模块的“待处理”口径不是行上的 pending 字段，而是业务规则实时算出的值
# （消防设施取“到期未检数”），概览与台账页必须共用同一份口径，避免两个页面数字对不上。
PENDING_COUNTERS: dict[str, Callable[[list[dict[str, Any]]], int]] = {}


def _register_pending_counter(module: str):
    def decorator(func: Callable[[list[dict[str, Any]]], int]):
        PENDING_COUNTERS[module] = func
        return func
    return decorator


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in HIDDEN_TABLES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def pending_count(self, module: str, rows: list[dict[str, Any]] | None = None) -> int:
        """统一的待处理量口径：有自定义计数器的模块走业务规则，其余回到 pending 字段。"""
        rows = self.rows(module) if rows is None else rows
        counter = PENDING_COUNTERS.get(module)
        if counter is not None:
            return counter(rows)
        return sum(1 for row in rows if row.get("pending"))

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": self.pending_count(name, rows),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
