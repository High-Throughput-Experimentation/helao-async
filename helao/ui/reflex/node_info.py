"""Info-box content for /group graph nodes: pure, so it is testable without Reflex."""

from typing import Optional

from helao.ui.shared.mask import mask_secrets


def _newest_finished(nonactive: Optional[dict]) -> Optional[str]:
    newest = None  # (timestamp, status)
    for status, bucket in (nonactive or {}).items():
        for a in (bucket or {}).values():
            ts = str((a or {}).get("action_finished_timestamp") or "")
            if newest is None or ts > newest[0]:
                newest = (ts, str(status))
    return newest[1] if newest else None


def endpoint_rows(status: dict) -> list:
    """One row per endpoint of a ``/get_status`` dump."""
    estop = bool(status.get("estop"))
    rows = []
    for name, ep in sorted((status.get("endpoints") or {}).items()):
        active = (ep or {}).get("active_dict") or {}
        if estop:
            state = "estop"
        elif active:
            state = "busy"
        else:
            state = _newest_finished((ep or {}).get("nonactive_dict")) or "idle"
        rows.append(
            {
                "name": name,
                "status": state,
                "non_idle": len(active),
                "active": [
                    {
                        "name": a.get("action_name"),
                        "uuid": str(a.get("action_uuid") or u),
                        "start": a.get("action_timestamp"),
                    }
                    for u, a in active.items()
                ],
            }
        )
    return rows


def server_info(cfg_entry: dict, status: Optional[dict]) -> dict:
    """Tree for an action-server node: masked config, driver status, endpoints."""
    info: dict = {"config": mask_secrets(cfg_entry or {})}
    if status is None:
        info["endpoints"] = "unavailable"
        return info
    info["driver_status"] = status.get("_driver_status")
    info["endpoints"] = {
        f"{r['name']} — {r['status']}, {r['non_idle']} non-idle": r["active"]
        for r in endpoint_rows(status)
    }
    return info


def config_info(cfg: dict) -> dict:
    """Tree for an orchestrator or runner node: its masked config only."""
    return {"config": mask_secrets(cfg or {})}
