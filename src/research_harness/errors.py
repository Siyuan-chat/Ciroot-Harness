class HarnessError(Exception):
    code = "RH_ERROR"


class ValidationError(HarnessError):
    code = "RH_INVALID_INPUT"


class PreflightError(HarnessError):
    code = "RH_PRECONDITION"


class BusyError(HarnessError):
    code = "RH_WORKSPACE_BUSY"
