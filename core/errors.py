class DomainError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self):
        result = {
            "code": self.code,
            "message": self.message,
        }

        if self.details:
            result["details"] = self.details

        return result
