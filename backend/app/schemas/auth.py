from pydantic import BaseModel


class LoginRequest(BaseModel):
    student_id: int
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    student: "StudentMe"


class StudentMe(BaseModel):
    student_id: int
    name: str
    major: str
    admission_year: int
    status: str


TokenResponse.model_rebuild()
