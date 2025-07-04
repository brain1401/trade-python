from fastapi import APIRouter

from app.api.v1.endpoints import chat, news, monitoring

api_router = APIRouter()

# Chat 관련 라우터 포함
api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["Chat"],
    responses={
        404: {"description": "채팅 엔드포인트를 찾을 수 없음"},
        500: {"description": "서버 내부 오류"},
    },
)

# News 생성 라우터 포함
api_router.include_router(
    news.router,
    prefix="/news",
    tags=["News"],
    responses={
        404: {"description": "뉴스 엔드포인트를 찾을 수 없음"},
        500: {"description": "서버 내부 오류"},
    },
)

# Monitoring 라우터 포함
api_router.include_router(
    monitoring.router,
    prefix="/monitoring",
    tags=["Monitoring"],
    responses={
        404: {"description": "모니터링 엔드포인트를 찾을 수 없음"},
        500: {"description": "서버 내부 오류"},
    },
)
