"""
Report generation (design.md §12).

Produces the summary block (similarity %, counts by difference type) and
per-difference findings from a DifferenceEngine.compare() result. Visual
evidence is a separate module — see src/reporting/visualize.py.
"""

import json
from pathlib import Path


class ReportGenerator:
    def generate(self, production_doc, client_doc, differences) -> dict:
        counts = {}
        for d in differences:
            counts[d.type] = counts.get(d.type, 0) + 1

        total = len(differences)
        matches = counts.get("MATCH", 0)
        similarity = round(100 * matches / total, 1) if total else 0.0

        prod_by_id = {el.id: el for el in production_doc.elements}
        client_by_id = {el.id: el for el in client_doc.elements}

        findings = []
        for d in differences:
            if d.type == "MATCH":
                continue
            p = prod_by_id.get(d.production_id)
            c = client_by_id.get(d.client_id)
            reference = p or c
            findings.append({
                "type": d.type,
                "production_id": d.production_id,
                "client_id": d.client_id,
                "class": reference.class_ if reference else None,
                "text": reference.text if reference else None,
                "details": d.details,
            })

        return {
            "screen": production_doc.screen_id,
            "similarity_percent": similarity,
            "summary": {"total_compared": total, **counts},
            "findings": findings,
        }

    @staticmethod
    def save_json(report: dict, path: Path):
        Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
