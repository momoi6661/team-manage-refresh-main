"""
认证依赖
用于保护需要认证的路由
"""
import logging
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)


def get_current_user(request: Request) -> dict:
    """
    获取当前登录用户
    从 Session 中获取用户信息

    Args:
        request: FastAPI Request 对象

    Returns:
        用户信息字典

    Raises:
        HTTPException: 如果未登录
    """
    user = request.session.get("user")

    if not user:
        logger.warning("未登录用户尝试访问受保护资源")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录"
        )

    return user


async def require_admin(request: Request) -> dict:
    """要求当前浏览器已建立管理员 Session。"""
    user = request.session.get("user")
    if user and user.get("is_admin"):
        return user

    logger.warning("认证失败: 未登录管理员会话")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="管理员会话未登录"
    )


def optional_user(request: Request) -> dict | None:
    """
    可选的用户信息
    如果已登录则返回用户信息，否则返回 None

    Args:
        request: FastAPI Request 对象

    Returns:
        用户信息字典或 None
    """
    return request.session.get("user")
