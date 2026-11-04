"""Serves the built frontend (`make run`, spec 002 §2.4)."""

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class WebApp(StaticFiles):
    """Static files, with every unknown path answered by the app's own router (index.html).

    Paths under /api are never answered with the app: a client expecting JSON
    must get a 404, not a 200 with HTML.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)
