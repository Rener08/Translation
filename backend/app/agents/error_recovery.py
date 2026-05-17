"""Error recovery strategies for agent loop.

Phase 2: Error classification and retry logic.
"""

from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Error categories for recovery strategy selection."""
    TRANSIENT = "transient"  # Temporary errors (rate limit, network)
    PERMANENT = "permanent"  # Unrecoverable errors (invalid input, auth)
    USER_FIXABLE = "user_fixable"  # Requires user intervention (missing config)


class RetryStrategy(str, Enum):
    """Retry strategies for error recovery."""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    IMMEDIATE = "immediate"
    NEVER = "never"


@dataclass(frozen=True)
class ErrorClassification:
    """Classification of an error for recovery."""
    category: ErrorCategory
    retry_strategy: RetryStrategy
    max_retries: int
    reason: str


def classify_error(error: Exception) -> ErrorClassification:
    """Classify an error to determine recovery strategy.

    Args:
        error: The exception to classify

    Returns:
        ErrorClassification with recovery strategy
    """
    error_type = type(error).__name__
    error_msg = str(error).lower()

    # Rate limit errors (transient)
    if "rate limit" in error_msg or "429" in error_msg or "too many requests" in error_msg:
        return ErrorClassification(
            category=ErrorCategory.TRANSIENT,
            retry_strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=3,
            reason="Rate limit exceeded, will retry with backoff"
        )

    # Network errors (transient)
    if any(x in error_msg for x in ["timeout", "connection", "network", "unreachable"]):
        return ErrorClassification(
            category=ErrorCategory.TRANSIENT,
            retry_strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=2,
            reason="Network error, will retry"
        )

    # Provider errors (check if transient)
    if "ContentRewriteProviderError" in error_type:
        if any(x in error_msg for x in ["503", "502", "500", "server error"]):
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                retry_strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
                max_retries=2,
                reason="Provider server error, will retry"
            )
        else:
            return ErrorClassification(
                category=ErrorCategory.PERMANENT,
                retry_strategy=RetryStrategy.NEVER,
                max_retries=0,
                reason="Provider error (non-retryable)"
            )

    # Configuration errors (user fixable)
    if "ContentRewriteConfigurationError" in error_type:
        return ErrorClassification(
            category=ErrorCategory.USER_FIXABLE,
            retry_strategy=RetryStrategy.NEVER,
            max_retries=0,
            reason="Configuration error, requires user fix"
        )

    # Input errors (permanent)
    if "ContentRewriteInputError" in error_type or "ValueError" in error_type:
        return ErrorClassification(
            category=ErrorCategory.PERMANENT,
            retry_strategy=RetryStrategy.NEVER,
            max_retries=0,
            reason="Input validation error (non-retryable)"
        )

    # Cancellation (permanent)
    if "cancel" in error_msg:
        return ErrorClassification(
            category=ErrorCategory.PERMANENT,
            retry_strategy=RetryStrategy.NEVER,
            max_retries=0,
            reason="Operation cancelled by user"
        )

    # Default: treat as transient with limited retries
    return ErrorClassification(
        category=ErrorCategory.TRANSIENT,
        retry_strategy=RetryStrategy.IMMEDIATE,
        max_retries=1,
        reason="Unknown error, will retry once"
    )


def calculate_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """Calculate exponential backoff delay.

    Args:
        attempt: Retry attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        Delay in seconds
    """
    delay = base_delay * (2 ** attempt)
    return min(delay, max_delay)


def should_retry(
    error: Exception,
    attempt: int,
    classification: ErrorClassification | None = None
) -> tuple[bool, float]:
    """Determine if an error should be retried.

    Args:
        error: The exception that occurred
        attempt: Current retry attempt (0-indexed)
        classification: Optional pre-computed classification

    Returns:
        Tuple of (should_retry, delay_seconds)
    """
    if classification is None:
        classification = classify_error(error)

    if classification.retry_strategy == RetryStrategy.NEVER:
        return False, 0.0

    if attempt >= classification.max_retries:
        return False, 0.0

    if classification.retry_strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
        delay = calculate_backoff_delay(attempt)
        return True, delay

    # IMMEDIATE
    return True, 0.0
