from pydantic import BaseModel
from typing import Optional


class UserOut(BaseModel):
    username: str
    is_admin: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
