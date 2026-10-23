from fastapi import APIRouter, Depends

from app.api.v1 import documents, exports, goals, lessons, me, quizzes, roadmaps
from app.core.errors import ProblemDetail
from app.core.security import get_principal

# Authentication is attached to the router, not to individual handlers: any route added under
# /v1 requires a verified access token even if its author forgets to ask for the principal.
router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(get_principal)],
    responses={
        401: {"model": ProblemDetail, "description": "Missing, invalid or expired access token"},
        503: {"model": ProblemDetail, "description": "A dependency is temporarily unavailable"},
    },
)
router.include_router(me.router)
router.include_router(goals.router)
router.include_router(roadmaps.router)
router.include_router(lessons.router)
router.include_router(quizzes.router)
router.include_router(documents.router)
router.include_router(exports.router)
