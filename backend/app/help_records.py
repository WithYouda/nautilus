"""Version-local help request, reply, and client display facts."""

from typing import Any


HELP_PROMPTS = {
    "hint": "用户本轮请求提示：给一个有用的线索，留出自行思考空间；若用户文字明确要求更多解释，以文字请求为准。",
    "explain_step": "用户本轮请求解释当前步骤：聚焦正在卡住的一步，说明依据，不必要求先经过提示阶梯；以本轮文字表达的具体需要为准。",
    "example": "用户本轮请求换个例子：用不同情境说明同一要点；换例子本身不代表提高提示强度；以本轮文字表达的具体需要为准。",
    "try_first": "用户本轮想先自行尝试：简短确认并等待其作答，不抢先解释或给出解法；若本轮文字已包含其尝试，则按其具体请求回应。",
}


def public_help(snapshot: dict[str, Any], content: str | None, status: str, finished_at: str | None) -> dict[str, Any]:
    request = snapshot.get("help_request")
    display = snapshot.get("help_display")
    body = content or ""
    return {
        "request": request if isinstance(request, dict) else None,
        "provided": {
            "kind": "reply_body",
            "characters": len(body),
            "at": finished_at,
            "partial": status not in {"complete", "succeeded"},
        } if body.strip() else None,
        "display": display if isinstance(display, dict) else None,
    }


def record_display(snapshot: dict[str, Any], characters: int, at: str) -> bool:
    """Record the greatest client-reported display extent, keeping its first time."""
    current = snapshot.get("help_display") or {}
    if characters <= current.get("characters", 0):
        return False
    snapshot["help_display"] = {"characters": characters, "at": current.get("at") or at, "basis": "client_report"}
    return True
