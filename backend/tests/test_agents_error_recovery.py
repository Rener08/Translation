"""Tests for error recovery.

Phase 2: Test error classification and retry logic.
"""

import pytest
from app.agents.error_recovery import (
    ErrorCategory,
    RetryStrategy,
    classify_error,
    calculate_backoff_delay,
    should_retry,
)


class TestClassifyError:
    """Test classify_error function."""

    def test_classify_rate_limit_error(self):
        """Test classifying rate limit errors."""
        error = Exception("Rate limit exceeded")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.retry_strategy == RetryStrategy.EXPONENTIAL_BACKOFF
        assert classification.max_retries == 3
        assert "rate limit" in classification.reason.lower()

    def test_classify_429_error(self):
        """Test classifying 429 status code."""
        error = Exception("HTTP 429: Too many requests")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.retry_strategy == RetryStrategy.EXPONENTIAL_BACKOFF
        assert classification.max_retries == 3

    def test_classify_network_timeout(self):
        """Test classifying network timeout."""
        error = Exception("Connection timeout")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.retry_strategy == RetryStrategy.EXPONENTIAL_BACKOFF
        assert classification.max_retries == 2

    def test_classify_network_connection_error(self):
        """Test classifying connection errors."""
        error = Exception("Network unreachable")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.max_retries == 2

    def test_classify_provider_5xx_error(self):
        """Test classifying provider 5xx errors."""
        # Create a mock exception with the right type name
        class ContentRewriteProviderError(Exception):
            pass

        error = ContentRewriteProviderError("HTTP 503: Service unavailable")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.retry_strategy == RetryStrategy.EXPONENTIAL_BACKOFF
        assert classification.max_retries == 2

    def test_classify_provider_non_retryable_error(self):
        """Test classifying non-retryable provider errors."""
        class ContentRewriteProviderError(Exception):
            pass

        error = ContentRewriteProviderError("Invalid API key")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.PERMANENT
        assert classification.retry_strategy == RetryStrategy.NEVER
        assert classification.max_retries == 0

    def test_classify_configuration_error(self):
        """Test classifying configuration errors."""
        class ContentRewriteConfigurationError(Exception):
            pass

        error = ContentRewriteConfigurationError("Missing API key")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.USER_FIXABLE
        assert classification.retry_strategy == RetryStrategy.NEVER
        assert classification.max_retries == 0

    def test_classify_input_error(self):
        """Test classifying input validation errors."""
        class ContentRewriteInputError(Exception):
            pass

        error = ContentRewriteInputError("Invalid input format")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.PERMANENT
        assert classification.retry_strategy == RetryStrategy.NEVER

    def test_classify_value_error(self):
        """Test classifying ValueError."""
        error = ValueError("Invalid value")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.PERMANENT
        assert classification.retry_strategy == RetryStrategy.NEVER

    def test_classify_cancellation_error(self):
        """Test classifying cancellation."""
        error = Exception("Operation cancelled by user")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.PERMANENT
        assert classification.retry_strategy == RetryStrategy.NEVER

    def test_classify_unknown_error(self):
        """Test classifying unknown errors."""
        error = Exception("Some random error")

        classification = classify_error(error)

        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.retry_strategy == RetryStrategy.IMMEDIATE
        assert classification.max_retries == 1


class TestCalculateBackoffDelay:
    """Test calculate_backoff_delay function."""

    def test_backoff_first_attempt(self):
        """Test backoff delay for first retry."""
        delay = calculate_backoff_delay(0)

        assert delay == 1.0

    def test_backoff_second_attempt(self):
        """Test backoff delay for second retry."""
        delay = calculate_backoff_delay(1)

        assert delay == 2.0

    def test_backoff_third_attempt(self):
        """Test backoff delay for third retry."""
        delay = calculate_backoff_delay(2)

        assert delay == 4.0

    def test_backoff_exponential_growth(self):
        """Test exponential growth of backoff."""
        delays = [calculate_backoff_delay(i) for i in range(5)]

        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_backoff_max_delay(self):
        """Test that backoff is capped at max_delay."""
        delay = calculate_backoff_delay(10, max_delay=60.0)

        assert delay == 60.0

    def test_backoff_custom_base_delay(self):
        """Test backoff with custom base delay."""
        delay = calculate_backoff_delay(0, base_delay=2.0)

        assert delay == 2.0

    def test_backoff_custom_base_and_attempt(self):
        """Test backoff with custom base and attempt."""
        delay = calculate_backoff_delay(2, base_delay=0.5)

        assert delay == 2.0  # 0.5 * 2^2


class TestShouldRetry:
    """Test should_retry function."""

    def test_should_retry_transient_error(self):
        """Test retrying transient errors."""
        error = Exception("Rate limit exceeded")

        should, delay = should_retry(error, attempt=0)

        assert should is True
        assert delay > 0

    def test_should_retry_permanent_error(self):
        """Test not retrying permanent errors."""
        error = ValueError("Invalid input")

        should, delay = should_retry(error, attempt=0)

        assert should is False
        assert delay == 0.0

    def test_should_retry_max_attempts_reached(self):
        """Test not retrying after max attempts."""
        error = Exception("Rate limit exceeded")

        should, delay = should_retry(error, attempt=3)

        assert should is False
        assert delay == 0.0

    def test_should_retry_immediate_strategy(self):
        """Test immediate retry strategy."""
        error = Exception("Some random error")

        should, delay = should_retry(error, attempt=0)

        assert should is True
        assert delay == 0.0

    def test_should_retry_exponential_backoff(self):
        """Test exponential backoff strategy."""
        error = Exception("Rate limit exceeded")

        should1, delay1 = should_retry(error, attempt=0)
        should2, delay2 = should_retry(error, attempt=1)

        assert should1 is True
        assert should2 is True
        assert delay2 > delay1

    def test_should_retry_with_classification(self):
        """Test should_retry with pre-computed classification."""
        from app.agents.error_recovery import ErrorClassification

        error = Exception("test")
        classification = ErrorClassification(
            category=ErrorCategory.TRANSIENT,
            retry_strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=2,
            reason="test"
        )

        should, delay = should_retry(error, attempt=0, classification=classification)

        assert should is True
        assert delay > 0

    def test_should_retry_respects_max_retries(self):
        """Test that should_retry respects max_retries from classification."""
        from app.agents.error_recovery import ErrorClassification

        error = Exception("test")
        classification = ErrorClassification(
            category=ErrorCategory.TRANSIENT,
            retry_strategy=RetryStrategy.IMMEDIATE,
            max_retries=1,
            reason="test"
        )

        should1, _ = should_retry(error, attempt=0, classification=classification)
        should2, _ = should_retry(error, attempt=1, classification=classification)

        assert should1 is True
        assert should2 is False


class TestErrorCategoryEnum:
    """Test ErrorCategory enum."""

    def test_error_category_values(self):
        """Test ErrorCategory enum values."""
        assert ErrorCategory.TRANSIENT.value == "transient"
        assert ErrorCategory.PERMANENT.value == "permanent"
        assert ErrorCategory.USER_FIXABLE.value == "user_fixable"


class TestRetryStrategyEnum:
    """Test RetryStrategy enum."""

    def test_retry_strategy_values(self):
        """Test RetryStrategy enum values."""
        assert RetryStrategy.EXPONENTIAL_BACKOFF.value == "exponential_backoff"
        assert RetryStrategy.IMMEDIATE.value == "immediate"
        assert RetryStrategy.NEVER.value == "never"
