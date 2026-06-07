from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings


def require_agent_token(request: Request, settings: Settings = Depends(get_settings)) -> None:
    header = request.headers.get("Authorization", "")
    expected = f"Bearer {settings.auth_token}"
    if not settings.auth_token or settings.auth_token == "change-me":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RECOVERY_AUTH_TOKEN must be set before accepting recovery commands.",
        )
    if header != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Agent token.")
