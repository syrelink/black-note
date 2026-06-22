from pydantic import BaseModel, field_validator


class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("用户名不能为空")
        return v.strip()


class LoginRequest(BaseModel):
    username: str
    password: str


class UserUpdateRequest(BaseModel):
    nickname: str | None = None
    avatar:   str | None = None


class LoginResponse(BaseModel):
    token:    str
    id:       str        # MongoDB ObjectId hex string
    username: str
    nickname: str | None = None
    avatar:   str | None = None


class UserResponse(BaseModel):
    id:       str        # MongoDB ObjectId hex string
    username: str
    nickname: str | None = None
    avatar:   str | None = None
