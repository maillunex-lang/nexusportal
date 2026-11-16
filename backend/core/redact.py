"""Удаление секретов из текста перед логированием, памятью и промптами."""
import logging
import re

_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)(authorization|token|password|secret|api[_-]?key)(\s*[:=]\s*)(\S+)"),
]


def redact(text: str, extra: list[str] | tuple[str, ...] = ()) -> str:
    if not text:
        return text
    for s in extra:
        if s and len(s) >= 6:
            text = text.replace(s, "***")
    for p in _PATTERNS:
        if p.groups == 3:
            text = p.sub(lambda m: m.group(1) + m.group(2) + "***", text)
        else:
            text = p.sub("***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


def install_log_redaction() -> None:
    root = logging.getLogger()
    for h in root.handlers or []:
        h.addFilter(RedactingFilter())
    root.addFilter(RedactingFilter())
