# app/nlp/language_detector.py

from typing import Optional
from langdetect import detect, detect_langs, LangDetectException
from langdetect import DetectorFactory

from app.utils.logger import get_logger

# Seed for reproducibility
DetectorFactory.seed = 42

logger = get_logger(__name__)

# ─── Supported Languages ───────────────────────────────────────────────────────
SUPPORTED_LANGUAGES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ar": "Arabic",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
    "hi": "Hindi",
}

DEFAULT_LANGUAGE = "en"
MIN_TEXT_LENGTH  = 50    # Minimum chars needed for reliable detection


class LanguageDetector:
    """
    Detects the language of resume text using langdetect.
    Falls back to English if detection fails or confidence is low.
    """

    def detect(
        self,
        text: str,
        min_confidence: float = 0.80,
    ) -> dict:
        """
        Detect language of the given text.

        Args:
            text:           Text to analyze
            min_confidence: Minimum confidence threshold

        Returns:
            {
                "language":    str,   # ISO 639-1 code (e.g., 'en')
                "language_name": str, # Full name (e.g., 'English')
                "confidence":  float,
                "all_scores":  list[dict],
                "is_reliable": bool,
            }
        """
        if not text or len(text.strip()) < MIN_TEXT_LENGTH:
            logger.debug("Text too short for language detection, defaulting to English")
            return self._default_result()

        # Use a sample for efficiency (first 1000 chars)
        sample = text[:1000].strip()

        try:
            # Get all language probabilities
            lang_probs = detect_langs(sample)

            if not lang_probs:
                return self._default_result()

            # Top result
            top        = lang_probs[0]
            lang_code  = top.lang
            confidence = round(float(top.prob), 3)

            # Build all scores
            all_scores = [
                {"language": lp.lang, "confidence": round(float(lp.prob), 3)}
                for lp in lang_probs
            ]

            is_reliable = confidence >= min_confidence

            if not is_reliable:
                logger.debug(
                    f"Low confidence language detection: "
                    f"{lang_code} ({confidence:.2f}), defaulting to English"
                )
                lang_code  = DEFAULT_LANGUAGE
                confidence = 0.0

            lang_name = SUPPORTED_LANGUAGES.get(lang_code, lang_code.upper())

            logger.info(
                f"Language detected: {lang_code} ({lang_name}) "
                f"confidence={confidence:.2f}"
            )

            return {
                "language":      lang_code,
                "language_name": lang_name,
                "confidence":    confidence,
                "all_scores":    all_scores,
                "is_reliable":   is_reliable,
            }

        except LangDetectException as e:
            logger.warning(f"Language detection failed: {e}")
            return self._default_result()

    def detect_language_code(self, text: str) -> str:
        """
        Quick method — returns just the language code.
        Falls back to 'en' on failure.
        """
        result = self.detect(text)
        return result["language"]

    def is_english(self, text: str) -> bool:
        """Check if text is in English."""
        return self.detect_language_code(text) == "en"

    def get_language_name(self, lang_code: str) -> str:
        """Get full language name from ISO code."""
        return SUPPORTED_LANGUAGES.get(lang_code, lang_code.upper())

    def _default_result(self) -> dict:
        """Return default English result."""
        return {
            "language":      DEFAULT_LANGUAGE,
            "language_name": "English",
            "confidence":    0.0,
            "all_scores":    [],
            "is_reliable":   False,
        }


# ─── Singleton ─────────────────────────────────────────────────────────────────
language_detector = LanguageDetector()
