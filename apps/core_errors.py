"""Erreurs métier levées par les services, indépendantes de HTTP."""


class BusinessError(Exception):
    code = "business_error"
    http_status = 400

    def __init__(self, message: str, code: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status


class InvalidTransition(BusinessError):
    code = "invalid_transition"
    http_status = 409


class Conflict(BusinessError):
    code = "conflict"
    http_status = 409


class Forbidden(BusinessError):
    code = "forbidden"
    http_status = 403
