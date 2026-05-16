from dataclasses import dataclass


class TranslationError(Exception):
    """Base error for translation failures."""


class TranslationProviderError(TranslationError):
    """Raised when the upstream translation provider fails."""


class RetryableTranslationContentError(TranslationProviderError):
    """Raised when the provider returns retryable but unusable content."""


class NonJsonTranslationContentError(RetryableTranslationContentError):
    """Raised when the provider returns non-JSON translation content."""


class PartialTranslationsContentError(RetryableTranslationContentError):
    """Raised when the provider returns a partial structured translation payload."""

    def __init__(
        self,
        message: str,
        *,
        partial_translations: dict[int, str],
        missing_indices: list[int],
    ) -> None:
        super().__init__(message)
        self.partial_translations = partial_translations
        self.missing_indices = missing_indices


@dataclass(frozen=True)
class TranslationChunkItem:
    index: int
    start: float
    end: float
    source_text: str
