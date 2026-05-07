from fastapi import Request

from ragstudio.config import AppSettings


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings
