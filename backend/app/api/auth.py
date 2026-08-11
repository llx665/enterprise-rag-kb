"""认证接口：注册 / 登录 / 刷新令牌 / 修改密码 / 当前用户。"""
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from ..core.deps import CurrentUser, DbDep
from ..core.limiter import limiter
from ..core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from ..models import User
from ..schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from ..schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserOut, summary="用户注册")
@limiter.limit("10/minute")
async def register(request: Request, data: RegisterRequest, db: DbDep):
    # 检查用户名是否已存在
    existing = await db.scalar(select(User).where(User.username == data.username))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被占用")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        nickname=data.nickname or data.username,
        role="user",  # 注册用户一律为普通用户，管理员仅系统内置
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse, summary="登录")
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, db: DbDep):
    user = await db.scalar(select(User).where(User.username == data.username))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse, summary="刷新令牌")
async def refresh(data: RefreshRequest, db: DbDep):
    try:
        payload = decode_token(data.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效或已过期"
        )
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌类型错误")

    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.put("/password", summary="修改密码")
async def change_password(data: ChangePasswordRequest, db: DbDep, user: CurrentUser):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码错误")
    user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"message": "密码修改成功"}


@router.get("/me", response_model=UserOut, summary="当前用户信息")
async def get_me(user: CurrentUser):
    return user
