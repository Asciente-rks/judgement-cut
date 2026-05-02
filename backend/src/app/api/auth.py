from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..db import database, users, pwd_context
from ..core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from datetime import datetime, timedelta
from jose import jwt


class LoginIn(BaseModel):
    username: str
    password: str


router = APIRouter()


@router.post("/login")
async def login(payload: LoginIn):
    query = users.select().where(users.c.username == payload.username)
    record = await database.fetch_one(query)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not pwd_context.verify(payload.password, record["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    to_encode = {"sub": record["username"], "is_admin": bool(record["is_admin"])}
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}
