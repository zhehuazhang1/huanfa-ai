#!/usr/bin/env python3
"""Patch _platform_llm_stats to add per-store breakdown."""

path = '/home/ubuntu/hair-ai-test/backend/app/services.py'

with open(path) as f:
    content = f.read()

# Locate method
idx = content.find('def _platform_llm_stats')
if idx < 0:
    print('ERROR: _platform_llm_stats not found')
    exit(1)

# Find end of method (next method at same indent level)
next_def = content.find('\n    def ', idx + 10)
if next_def < 0:
    print('ERROR: cannot find end of method')
    exit(1)

old_method = content[idx:next_def]
print('Old method length:', len(old_method))

new_method = '''_platform_llm_stats(self, month=None, tenant_id=None):
        """AI 对话成本统计，支持按月、按租户、按门店过滤。"""
        conds, params = [], []
        if month:
            conds.append("strftime('%Y-%m', created_at) = ?")
            params.append(month)
        if tenant_id:
            conds.append("tenant_id = ?")
            params.append(tenant_id)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        row = self.store.row(
            f"SELECT COUNT(*) AS total_turns, SUM(cost_fen) AS total_cost_fen FROM llm_chat_logs {where}",
            tuple(params),
        )
        if row is None:
            return {"total_turns": 0, "total_cost_fen": 0, "total_cost_yuan": 0, "avg_cost_fen_per_turn": 0, "by_tenant": []}
        total_cost_fen = int(row["total_cost_fen"] or 0)
        total_turns = int(row["total_turns"] or 0)
        tenant_rows = self.store.rows(
            f"SELECT tenant_id, COUNT(*) AS turns, SUM(cost_fen) AS cost_fen FROM llm_chat_logs {where} GROUP BY tenant_id ORDER BY cost_fen DESC",
            tuple(params),
        )
        by_tenant = []
        for r in tenant_rows:
            tid = int(r["tenant_id"])
            t_conds = list(conds) + ["tenant_id = ?"]
            t_params = list(params) + [tid]
            t_where = "WHERE " + " AND ".join(t_conds)
            store_rows = self.store.rows(
                f"SELECT store_id, COUNT(*) AS turns, SUM(cost_fen) AS cost_fen FROM llm_chat_logs {t_where} GROUP BY store_id ORDER BY cost_fen DESC",
                tuple(t_params),
            )
            by_tenant.append({
                "tenant_id": tid,
                "turns": int(r["turns"]),
                "cost_fen": int(r["cost_fen"]),
                "cost_yuan": round(int(r["cost_fen"]) / 100, 4),
                "by_store": [
                    {
                        "store_id": int(sr["store_id"]),
                        "turns": int(sr["turns"]),
                        "cost_fen": int(sr["cost_fen"]),
                        "cost_yuan": round(int(sr["cost_fen"]) / 100, 4),
                    }
                    for sr in store_rows
                ],
            })
        return {
            "total_turns": total_turns,
            "total_cost_fen": total_cost_fen,
            "total_cost_yuan": round(total_cost_fen / 100, 4),
            "avg_cost_fen_per_turn": round(total_cost_fen / total_turns, 1) if total_turns else 0,
            "by_tenant": by_tenant,
        }'''

# Replace method name + body (keep the `def ` prefix from original)
new_content = content[:idx] + 'def ' + new_method + content[next_def:]

# Verify
if 'by_store' in new_content:
    with open(path, 'w') as f:
        f.write(new_content)
    print('OK: _platform_llm_stats patched with by_store support')
else:
    print('ERROR: by_store not found in new content')
