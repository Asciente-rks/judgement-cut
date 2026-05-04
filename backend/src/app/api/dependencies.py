from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from ..core.config import SECRET_KEY, ALGORITHM
from ..db import database, users

security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Decode the JWT, look up the user, and return identity + admin flag.

    Raises 401 on any failure (invalid token, missing user).
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    query = users.select().where(users.c.username == username)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=401, detail="User not found")
    return {
        "id": record["id"],
        "username": record["username"],
        "is_admin": bool(record["is_admin"]),
    }


async def require_user(user=Depends(get_current_user)):
    """Authenticated user. Alias of get_current_user for route readability."""
    return user


async def require_admin(user=Depends(get_current_user)):
    """Authenticated admin user. Raises 403 if the caller isn't an admin."""
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
