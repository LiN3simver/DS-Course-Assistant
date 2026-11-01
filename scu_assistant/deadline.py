import time

from .llm import OllamaError


class ResponseDeadlineExceeded(OllamaError):
    pass


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ResponseDeadlineExceeded('本地模型未能在處理期限內完成回答與核對。')
    return seconds
