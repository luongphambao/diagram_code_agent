"""Re-export shim — moved to ``memory/stores/comments.py``."""

from __future__ import annotations

from memory.stores.comments import (
    COMMENT_LOG_NAME,
    CommentRecord,
    append_comment,
    comments_for,
    new_comment_record,
    read_comments,
    resolve_comment,
    next_seq,
)
