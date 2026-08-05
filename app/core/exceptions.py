from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception with consistent error format."""

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


class NotFoundException(AppException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(detail=f"{resource} not found", status_code=status.HTTP_404_NOT_FOUND)


class UnauthorizedException(AppException):
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(detail=detail, status_code=status.HTTP_401_UNAUTHORIZED)


class ForbiddenException(AppException):
    def __init__(self, detail: str = "Not enough permissions"):
        super().__init__(detail=detail, status_code=status.HTTP_403_FORBIDDEN)


class ConflictException(AppException):
    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(detail=detail, status_code=status.HTTP_409_CONFLICT)


class TooManyRequestsException(AppException):
    def __init__(self, detail: str = "Too many requests. Please try again later."):
        super().__init__(detail=detail, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
