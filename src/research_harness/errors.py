class HarnessError(Exception):
    code = "RH_ERROR"
    def to_dict(self): return {"code":self.code,"message":"operation failed"}


class ValidationError(HarnessError):
    code = "RH_INVALID_INPUT"


class PreflightError(HarnessError):
    code = "RH_PRECONDITION"


class BusyError(HarnessError):
    code = "RH_WORKSPACE_BUSY"

class NotFoundError(HarnessError):
    code = "RH_NOT_FOUND"

class ExportError(HarnessError):
    code = "RH_EXPORT_FAILED"

class UnsupportedError(HarnessError):
    code = "RH_UNSUPPORTED"
