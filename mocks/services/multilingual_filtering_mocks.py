"""
Multi-language Content Filtering Mock Services

This module provides mock services for testing multi-language content filtering
in Stageflow pipelines, including:
- Language detection
- Content filtering (profanity, toxicity)
- Translation services
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple
from enum import Enum
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)


class LanguageCode(str, Enum):
    """Supported language codes."""
    EN = "en"
    ES = "de"
    FR = "fr"
    DE = "de"
    AR = "ar"
    RU = "ru"
    HI = "hi"
    TA = "ta"
    KN = "kn"
    ML = "ml"
    AM = "am"
    ZH = "zh"
    JA = "ja"
    KO = "ko"
    IT = "it"
    PT = "pt"


@dataclass
class LanguageDetectionResult:
    """Result of language detection."""
    language: str
    confidence: float
    script: Optional[str] = None
    is_code_mixed: bool = False
    mixed_languages: List[str] = field(default_factory=list)


@dataclass
class ContentFilterResult:
    """Result of content filtering."""
    is_clean: bool
    categories: List[str]
    confidence: float
    matched_patterns: List[str]
    matched_words: List[str]
    severity: str  # "low", "medium", "high", "critical"
    processing_time_ms: float


@dataclass
class TranslationResult:
    """Result of translation."""
    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    confidence: float
    was_refused: bool = False


# ============================================================
# LANGUAGE DETECTION MOCK
# ============================================================

class MockLanguageDetector:
    """
    Mock language detection service.
    Supports multiple languages with configurable accuracy.
    """
    
    # Language-specific character patterns
    LANGUAGE_PATTERNS = {
        'en': r'[a-zA-Z\s\.\,\!\?]+',
        'es': r'[a-zA-Zñáéíóúü\s\.\,\!\?]+',
        'de': r'[a-zA-Zäöüß\s\.\,\!\?]+',
        'fr': r'[a-zA-Zàâäéèêëïîôùûüÿ\s\.\,\!\?]+',
        'ar': r'[\u0600-\u06FF\s\.\,\!\؟]+',
        'ru': r'[а-яА-ЯёЁ\s\.\,\!\?]+',
        'hi': r'[\u0900-\u097F\s\.\,\!\?]+',
        'ta': r'[\u0B80-\u0BFF\s\.\,\!\?]+',
        'kn': r'[\u0C80-\u0CFF\s\.\,\!\?]+',
        'ml': r'[\u0D00-\u0D7F\s\.\,\!\?]+',
        'am': r'[\u1200-\u137F\s\.\,\!\?]+',
        'zh': r'[\u4E00-\u9FFF\s\.\,\!\?]+',
        'ja': r'[\u3040-\u309F\u30A0-\u30FF\s\.\,\!\?]+',
        'ko': r'[\uAC00-\uD7AF\u1100-\u11FF\s\.\,\!\?]+',
    }
    
    # Common words for detection
    LANGUAGE_INDICATORS = {
        'en': ['the', 'is', 'are', 'hello', 'good', 'thanks', 'please', 'you', 'have'],
        'es': ['el', 'la', 'es', 'son', 'hola', 'bueno', 'gracias', 'por', 'favor', 'tienes'],
        'de': ['der', 'die', 'das', 'ist', 'sind', 'hallo', 'gut', 'danke', 'bitte', 'hast'],
        'fr': ['le', 'la', 'est', 'sont', 'bonjour', 'bien', 'merci', "s'il", 'vous', 'avez'],
        'ar': ['ال', 'هو', 'هي', 'في', 'من', 'إلى', 'مرحبا', 'شكرا', 'الرجاء', 'هل'],
        'ru': ['и', 'в', 'не', 'он', 'на', 'я', 'с', 'что', 'привет', 'спасибо'],
        'hi': ['है', 'हैं', 'का', 'की', 'में', 'और', 'से', 'नमस्ते', 'धन्यवाद', 'कृपया'],
        'ta': ['இது', 'அது', 'என்று', 'மற்றும்', 'உள்ள', 'வணக்கம்', 'நன்றி', 'தயவு'],
    }
    
    def __init__(
        self,
        *,
        latency_ms: int = 50,
        accuracy: float = 0.95,
        event_emitter: Callable[[str, dict | None], None] | None = None,
    ) -> None:
        self.latency_ms = latency_ms
        self.accuracy = accuracy
        self.event_emitter = event_emitter or (lambda *args: None)
    
    async def detect(self, text: str) -> LanguageDetectionResult:
        """Detect the language of the given text."""
        await asyncio.sleep(self.latency_ms / 1000)
        
        # Check for script-based detection first
        for lang, pattern in self.LANGUAGE_PATTERNS.items():
            if re.match(pattern, text[:100]):
                # Check for code-mixing
                mixed = self._detect_code_mixing(text)
                if mixed:
                    return LanguageDetectionResult(
                        language=mixed[0],
                        confidence=self.accuracy * 0.9,
                        script=self._get_script(lang),
                        is_code_mixed=True,
                        mixed_languages=mixed,
                    )
                return LanguageDetectionResult(
                    language=lang,
                    confidence=self.accuracy,
                    script=self._get_script(lang),
                )
        
        # Default to English if no match
        return LanguageDetectionResult(
            language='en',
            confidence=0.5,
            is_code_mixed=False,
        )
    
    def _detect_code_mixing(self, text: str) -> List[str]:
        """Detect if text contains code mixing."""
        languages = []
        text_lower = text.lower()
        
        for lang, indicators in self.LANGUAGE_INDICATORS.items():
            for indicator in indicators:
                if indicator in text_lower:
                    if lang not in languages:
                        languages.append(lang)
        
        return languages if len(languages) > 1 else []
    
    def _get_script(self, lang: str) -> str:
        """Get script type for language."""
        scripts = {
            'ar': 'Arabic', 'ru': 'Cyrillic', 'hi': 'Devanagari',
            'ta': 'Tamil', 'kn': 'Kannada', 'ml': 'Malayalam',
            'am': 'Ge\'ez', 'zh': 'CJK', 'ja': 'Japanese',
            'ko': 'Hangul',
        }
        return scripts.get(lang, 'Latin')
    
    async def detect_batch(self, texts: List[str]) -> List[LanguageDetectionResult]:
        """Detect languages for multiple texts."""
        return [await self.detect(text) for text in texts]


# ============================================================
# CONTENT FILTERING MOCK
# ============================================================

class MockContentFilter:
    """
    Mock content filtering service.
    Detects profanity, hate speech, and other harmful content.
    """
    
    # Comprehensive profanity lists by language
    PROFANITY_LISTS = {
        'en': {
            'high': ['fuck', 'shit', 'asshole', 'bitch', 'cunt', 'dick', 'cock', 'pussy'],
            'medium': ['damn', 'hell', 'bastard', 'ass', 'crap', 'bitch'],
            'low': ['idiot', 'stupid', 'dumb', 'moron', 'fool', 'jerk'],
        },
        'es': {
            'high': ['mierda', 'puta', 'joder', 'cabrón', 'coño', 'culo'],
            'medium': ['idiota', 'estúpido', 'tonto', 'pendejo'],
            'low': [],
        },
        'de': {
            'high': ['scheiße', 'fick', 'arschloch', 'mist'],
            'medium': ['verdammt', 'holer'],
            'low': [],
        },
        'fr': {
            'high': ['putain', 'merde', 'salope', 'connard', 'culo'],
            'medium': ['idiot', 'stupide', 'con'],
            'low': [],
        },
        'ar': {
            'high': ['كس', 'زب', 'شاذ', 'كلب'],
            'medium': ['غبي', 'حقير'],
            'low': [],
        },
        'ru': {
            'high': ['блядь', 'пизда', 'хуй', 'ебать', 'сука'],
            'medium': ['чёрт', 'дурак', 'идиот'],
            'low': [],
        },
        'hi': {
            'high': ['बकवास', 'छिन्न', 'भोसड़ा'],
            'medium': ['बेवकूफ', 'मूर्ख'],
            'low': [],
        },
        'ta': {
            'high': ['முட்டாள்', 'சனி'],
            'medium': [],
            'low': [],
        },
    }
    
    # Obfuscation patterns
    OBFUSCATION_PATTERNS = {
        'leet': {
            'a': ['4', '@'], 'e': ['3', '€'], 'i': ['1', '!'],
            'o': ['0', '°'], 's': ['5', '$'], 't': ['7', '+'],
        },
        'homoglyph': {
            'a': ['а', 'ɑ'], 'e': ['е', 'ε'], 'o': ['о', '0'],
            'c': ['с'], 'p': ['р'], 'y': ['у'],
        },
    }
    
    def __init__(
        self,
        *,
        latency_ms: int = 30,
        sensitivity: float = 0.8,
        enabled_categories: List[str] = None,
        event_emitter: Callable[[str, dict | None], None] | None = None,
    ) -> None:
        self.latency_ms = latency_ms
        self.sensitivity = sensitivity
        self.enabled_categories = enabled_categories or ['profanity', 'hate_speech']
        self.event_emitter = event_emitter or (lambda *args: None)
    
    async def filter(self, text: str, language: str = 'en') -> ContentFilterResult:
        """Filter content for harmful material."""
        import time
        start = time.perf_counter()
        
        await asyncio.sleep(self.latency_ms / 1000)
        
        text_lower = text.lower()
        matched_patterns = []
        matched_words = []
        categories = []
        
        # Check profanity
        if 'profanity' in self.enabled_categories:
            profanity = self._check_profanity(text_lower, language)
            if profanity['has_match']:
                matched_words.extend(profanity['words'])
                matched_patterns.extend(profanity['patterns'])
                categories.append('profanity')
        
        # Check hate speech patterns
        if 'hate_speech' in self.enabled_categories:
            hate_speech = self._check_hate_speech(text_lower)
            if hate_speech['has_match']:
                matched_patterns.extend(hate_speech['patterns'])
                categories.append('hate_speech')
        
        # Determine severity
        severity = self._calculate_severity(matched_words, matched_patterns)
        is_clean = len(categories) == 0
        
        processing_time_ms = (time.perf_counter() - start) * 1000
        
        result = ContentFilterResult(
            is_clean=is_clean,
            categories=categories,
            confidence=0.9 if is_clean else 0.85,
            matched_patterns=matched_patterns,
            matched_words=matched_words,
            severity=severity,
            processing_time_ms=processing_time_ms,
        )
        
        self.event_emitter("content_filter.completed", {
            "text_length": len(text),
            "is_clean": is_clean,
            "categories": categories,
            "severity": severity,
        })
        
        return result
    
    def _check_profanity(self, text: str, language: str) -> Dict[str, Any]:
        """Check for profanity in text."""
        results = {'has_match': False, 'words': [], 'patterns': []}
        
        lang_profanity = self.PROFANITY_LISTS.get(language, self.PROFANITY_LISTS['en'])
        
        # Check all severity levels
        for severity, words in lang_profanity.items():
            for word in words:
                # Direct match
                if word in text:
                    results['has_match'] = True
                    results['words'].append(f"{word} ({severity})")
                    results['patterns'].append(f"direct:{word}")
                
                # Pattern match with leetspeak
                for pattern in self._generate_leet_patterns(word):
                    if pattern in text:
                        results['has_match'] = True
                        results['words'].append(f"{word} ({severity})")
                        results['patterns'].append(f"obfuscated:{word}")
                        break
        
        return results
    
    def _generate_leet_patterns(self, word: str) -> List[str]:
        """Generate leetspeak variations of a word."""
        patterns = []
        if not word:
            return patterns
        
        # Generate a few variations
        chars = list(word)
        for i, char in enumerate(chars):
            if char in self.OBFUSCATION_PATTERNS['leet']:
                for replacement in self.OBFUSCATION_PATTERNS['leet'][char][:2]:
                    new_chars = chars.copy()
                    new_chars[i] = replacement
                    patterns.append(''.join(new_chars))
        
        return patterns
    
    def _check_hate_speech(self, text: str) -> Dict[str, Any]:
        """Check for hate speech patterns."""
        results = {'has_match': False, 'patterns': []}
        
        hate_patterns = [
            r'(all|everyone|people) (of|like) .+ (are|is) (stupid|dumb|idiot|worthless)',
            r'(hate|despise|loathe) (you|people|them)',
            r'(go away|leave|get out).+(here|now)',
            r'(nobody|women|men| minorities).+(shouldnt|should not|can not)',
        ]
        
        for pattern in hate_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                results['has_match'] = True
                results['patterns'].append(f"hate_pattern:{pattern[:30]}...")
        
        return results
    
    def _calculate_severity(self, words: List[str], patterns: List[str]) -> str:
        """Calculate overall severity of matches."""
        high_count = sum(1 for w in words if 'high' in w)
        if high_count > 0:
            return 'high'
        if len(patterns) > 2:
            return 'medium'
        if len(patterns) > 0:
            return 'low'
        return 'none'
    
    async def filter_batch(
        self, texts: List[Tuple[str, str]]
    ) -> List[ContentFilterResult]:
        """Filter multiple texts."""
        return [await self.filter(text, lang) for text, lang in texts]


# ============================================================
# TRANSLATION MOCK
# ============================================================

class MockTranslationService:
    """
    Mock translation service.
    Simulates MT systems with configurable refusal rates.
    """
    
    # Simple dictionary for demonstration
    TRANSLATION_DICT = {
        ('es', 'en'): {
            'hola': 'hello',
            'gracias': 'thank you',
            'idiota': 'idiot',
            'mierda': 'shit',
            'maldito': 'damned',
        },
        ('de', 'en'): {
            'hallo': 'hello',
            'danke': 'thank you',
            'scheiße': 'shit',
            'verdammt': 'damned',
        },
        ('fr', 'en'): {
            'bonjour': 'hello',
            'merci': 'thank you',
            'putain': 'fuck',
            'idiot': 'idiot',
        },
        ('ar', 'en'): {
            'مرحبا': 'hello',
            'شكرا': 'thank you',
        },
        ('ru', 'en'): {
            'привет': 'hello',
            'спасибо': 'thank you',
            'дурак': 'fool',
        },
        ('hi', 'en'): {
            'नमस्ते': 'hello',
            'धन्यवाद': 'thank you',
            'बेवकूफ': 'idiot',
        },
        ('ta', 'en'): {
            'வணக்கம்': 'hello',
            'நன்றி': 'thank you',
        },
    }
    
    def __init__(
        self,
        *,
        latency_ms: int = 100,
        refusal_rate: float = 0.1,
        quality: float = 0.9,
        event_emitter: Callable[[str, dict | None], None] | None = None,
    ) -> None:
        self.latency_ms = latency_ms
        self.refusal_rate = refusal_rate
        self.quality = quality
        self.event_emitter = event_emitter or (lambda *args: None)
    
    async def translate(
        self, text: str, source_lang: str, target_lang: str = 'en'
    ) -> TranslationResult:
        """Translate text from source to target language."""
        await asyncio.sleep(self.latency_ms / 1000)
        
        # Simulate refusal for toxic content
        if self._should_refuse(text):
            self.event_emitter("translation.refused", {
                "text_length": len(text),
                "source_lang": source_lang,
            })
            return TranslationResult(
                original_text=text,
                translated_text="",
                source_language=source_lang,
                target_language=target_lang,
                confidence=0.0,
                was_refused=True,
            )
        
        # Simple translation (in real system, would use MT)
        translated = self._simple_translate(text, source_lang, target_lang)
        
        if not translated:
            # Fallback: return original with indicator
            translated = f"[EN-TRANS]: {text}"
        
        self.event_emitter("translation.completed", {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "confidence": self.quality,
        })
        
        return TranslationResult(
            original_text=text,
            translated_text=translated,
            source_language=source_lang,
            target_language=target_lang,
            confidence=self.quality,
            was_refused=False,
        )
    
    def _should_refuse(self, text: str) -> bool:
        """Determine if content should be refused."""
        toxic_indicators = ['fuck', 'shit', 'bitch', 'asshole', 'hate', 'kill']
        text_lower = text.lower()
        
        # Random refusal based on configured rate
        import random
        if random.random() < self.refusal_rate:
            return True
        
        # Refusal for explicitly toxic content
        for indicator in toxic_indicators:
            if indicator in text_lower:
                return True
        
        return False
    
    def _simple_translate(self, text: str, source: str, target: str) -> str:
        """Simple word-by-word translation."""
        if source == target:
            return text
        
        # Use dictionary for known words
        translations = self.TRANSLATION_DICT.get((source, target), {})
        words = text.split()
        translated_words = []
        
        for word in words:
            word_clean = word.lower().strip('.,!?')
            if word_clean in translations:
                translated_words.append(translations[word_clean])
            else:
                translated_words.append(word)
        
        return ' '.join(translated_words)
    
    async def translate_batch(
        self, texts: List[Tuple[str, str, str]]
    ) -> List[TranslationResult]:
        """Translate multiple texts."""
        return [
            await self.translate(text, source, target)
            for text, source, target in texts
        ]


# ============================================================
# DUPLEX AUDIO MOCKS (from components.audio)
# ============================================================

class MockMultilingualAudioProcessor:
    """
    Mock audio processor for multilingual content.
    Combines STT, translation, and TTS for end-to-end processing.
    """
    
    def __init__(self):
        self.stt = MockLanguageDetector(latency_ms=80)
        self.translator = MockTranslationService(latency_ms=120)
        self.filter = MockContentFilter(latency_ms=40)
        self.event_emitter: Callable[[str, dict | None], None] = lambda *args: None
    
    async def process_audio_input(
        self, audio_data: bytes, language: str = 'en'
    ) -> Dict[str, Any]:
        """Process audio through STT -> Detect -> Filter pipeline."""
        # Simulate STT
        await asyncio.sleep(0.1)
        transcribed = "Sample transcribed text for audio processing"
        
        # Detect language
        lang_result = await self.stt.detect(transcribed)
        
        # Filter content
        filter_result = await self.filter.filter(transcribed, lang_result.language)
        
        return {
            "transcribed_text": transcribed,
            "detected_language": lang_result.language,
            "confidence": lang_result.confidence,
            "is_clean": filter_result.is_clean,
            "filter_result": filter_result,
        }
    
    async def generate_audio_response(
        self, text: str, target_language: str = 'en'
    ) -> bytes:
        """Generate audio response from text."""
        # Simulate TTS
        await asyncio.sleep(0.08)
        return f"TTS_AUDIO:{text}".encode('utf-8')


# ============================================================
# FACTORY FUNCTIONS
# ============================================================

def create_language_detector(
    latency_ms: int = 50,
    accuracy: float = 0.95,
) -> MockLanguageDetector:
    """Create a language detector with given parameters."""
    return MockLanguageDetector(latency_ms=latency_ms, accuracy=accuracy)


def create_content_filter(
    latency_ms: int = 30,
    sensitivity: float = 0.8,
) -> MockContentFilter:
    """Create a content filter with given parameters."""
    return MockContentFilter(latency_ms=latency_ms, sensitivity=sensitivity)


def create_translation_service(
    latency_ms: int = 100,
    refusal_rate: float = 0.1,
) -> MockTranslationService:
    """Create a translation service with given parameters."""
    return MockTranslationService(
        latency_ms=latency_ms,
        refusal_rate=refusal_rate,
    )


def create_full_audio_processor() -> MockMultilingualAudioProcessor:
    """Create a complete audio processing pipeline."""
    return MockMultilingualAudioProcessor()


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    'MockLanguageDetector',
    'MockContentFilter',
    'MockTranslationService',
    'MockMultilingualAudioProcessor',
    'LanguageDetectionResult',
    'ContentFilterResult',
    'TranslationResult',
    'create_language_detector',
    'create_content_filter',
    'create_translation_service',
    'create_full_audio_processor',
]
