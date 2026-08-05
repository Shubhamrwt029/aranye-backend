from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str
    success: bool = True
