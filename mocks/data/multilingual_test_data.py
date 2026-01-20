"""
Multi-language Content Filtering Mock Data Generator

This module provides comprehensive test data for multi-language content filtering,
covering various languages, content types, and edge cases.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional
import json


class ContentCategory(str, Enum):
    """Categories of content for filtering tests."""
    CLEAN = "clean"
    PROFANITY = "profanity"
    HATE_SPEECH = "hate_speech"
    HARASSMENT = "harassment"
    SELF_HARM = "self_harm"
    VIOLENCE = "violence"
    SPAM = "spam"


class LanguageTier(str, Enum):
    """Resource tier for languages."""
    HIGH = "high"      # EN, ES, DE, FR
    MEDIUM = "medium"  # RU, AR, ZH
    LOW = "low"        # AM, TA, KN, ML


class ObfuscationType(str, Enum):
    """Types of obfuscation to test."""
    NONE = "none"
    LEET_SPEAK = "leet"
    HOMOGLYPH = "homoglyph"
    SPACING = "spacing"
    NUMERIC = "numeric"
    COMBINED = "combined"


@dataclass
class TestExample:
    """A single test example for content filtering."""
    text: str
    language: str
    category: ContentCategory
    tier: LanguageTier
    obfuscation: ObfuscationType = ObfuscationType.NONE
    expected_result: bool = True  # True = should pass filter (clean)
    notes: str = ""


# ============================================================
# HIGH-RESOURCE LANGUAGE TEST DATA
# ============================================================

ENGLISH_CLEAN = [
    "Hello, how are you today?",
    "I really enjoyed the movie last night.",
    "The weather is beautiful today.",
    "Thank you for your help with the project.",
    "Can you recommend a good restaurant?",
    "The team did an excellent job on this.",
    "I have a question about the schedule.",
    "Looking forward to seeing you soon!",
]

ENGLISH_PROFANITY = [
    ("You are a damn idiot!", True),
    ("What the hell happened here?", True),
    ("That's some crazy shit right there.", True),
    ("Holy crap, I can't believe it!", True),
    ("Stop being such an asshole.", True),
    ("This is fucking amazing!", True),
]

ENGLISH_HATE_SPEECH = [
    ("All [group] people are stupid and should leave.", True),
    ("I hate people like you, you're worthless.", True),
    ("Nobody wants you here, go away.", True),
]

ENGLISH_CODE_MIXED = [
    ("This is damn cool yaar, truly!", True),  # Hinglish
    ("The party was totally lit last night!", True),  # Gen Z slang
    ("That movie was amazing, bro!", True),
]

# ============================================================
# SPANISH TEST DATA
# ============================================================

SPANISH_CLEAN = [
    "Hola, ¿cómo estás hoy?",
    "Me gustó mucho el restaurante.",
    "El clima está muy bonito hoy.",
    "Gracias por tu ayuda.",
    "¿Puedes ayudarme con esto?",
]

SPANISH_PROFANITY = [
    ("¡Eres un maldito idiota!", True),  # You're a fucking idiot
    ("¡Qué carajo pasó aquí!", True),    # What the hell happened
    ("¡Vaya mierda de situación!", True),  # What a shit situation
    ("¡Este trabajo es una puta locura!", True),  # This work is fucking crazy
]

SPANISH_HATE_SPEECH = [
    ("Todos ustedes son unos idiotas y deberían irse.", True),
    ("Odio a las personas como tú.", True),
]

# ============================================================
# GERMAN TEST DATA
# ============================================================

GERMAN_CLEAN = [
    "Hallo, wie geht es dir heute?",
    "Das Wetter ist sehr schön heute.",
    "Vielen Dank für deine Hilfe.",
]

GERMAN_PROFANITY = [
    ("Du bist ein verdammter Idiot!", True),  # You are a fucking idiot
    ("Was zum Teufel ist hier passiert!", True),  # What the hell happened
    ("Scheiße, ich kann das nicht glauben!", True),  # Shit, I can't believe it
]

# ============================================================
# FRENCH TEST DATA
# ============================================================

FRENCH_CLEAN = [
    "Bonjour, comment allez-vous aujourd'hui?",
    "J'ai vraiment apprécié le film.",
    "Merci beaucoup pour votre aide.",
]

FRENCH_PROFANITY = [
    ("Tu es un putain d'idiot!", True),  # You are a fucking idiot
    ("Qu'est-ce que l'enfer s'est passé ici?", True),  # What the hell happened
    ("Putain, c'est incroyable!", True),  # Fuck, it's incredible
]

# ============================================================
# ARABIC TEST DATA
# ============================================================

ARABIC_CLEAN = [
    "مرحبا، كيف حالك اليوم؟",
    "لقد استمتعت حقاً بالفيلم.",
    "الطقس جميل جداً اليوم.",
    "شكرا لك على مساعدتك.",
]

ARABIC_PROFANITY = [
    ("أنت غبي!", True),  # You're stupid
    ("ما هذا الهراء!", True),  # What this nonsense
    ("كأنها لعين!", True),  # Like hell
]

# ============================================================
# RUSSIAN TEST DATA
# ============================================================

RUSSIAN_CLEAN = [
    "Привет, как дела сегодня?",
    "Мне очень понравился фильм.",
    "Спасибо за помощь.",
]

RUSSIAN_PROFANITY = [
    ("Ты чертовский идиот!", True),  # You are a fucking idiot
    ("Какого черта здесь произошло!", True),  # What the hell happened
    ("Черт возьми, я не могу в это поверить!", True),  # Damn it, I can't believe it
]

# ============================================================
# HINDI TEST DATA
# ============================================================

HINDI_CLEAN = [
    "नमस्ते, आज कैसे हैं?",
    "फिल्म बहुत अच्छी थी।",
    "आज मौसम बहुत अच्छा है।",
    "धन्यवाद आपकी मदद के लिए।",
]

HINDI_PROFANITY = [
    ("तुम बकवास कर रहे हो!", True),  # You're talking nonsense
    ("यह बेकार है!", True),  # This is useless
    ("क्या हो गया है भाई?", True),  # What happened brother
]

# ============================================================
# TAMIL TEST DATA
# ============================================================

TAMIL_CLEAN = [
    "வணக்கம், நாளைக்கு எப்படி இருக்கீர்கள்?",
    "இன்று காலை நன்றாக இருந்தது।",
    "திரைப்படம் மிகவும் நன்றாக இருந்தது।",
]

TAMIL_PROFANITY = [
    ("நீ ஒரு முட்டாள்!", True),  # You're an idiot
    ("இது என்ன சனியன்!", True),  # What the hell
]

# ============================================================
# LOW-RESOURCE LANGUAGE DATA
# ============================================================

AMHARIC_CLEAN = [
    "ሰላም፣ እንዴት ነህ?",
    "ዛሬ የስራ ቀን ነው።",
    "ፊልም ጥሩ ነበር።",
]

KANNADA_CLEAN = [
    "ನಮಸ್ಕಾರ, ಇಂದು ಹೇಗಿದ್ದೀರಿ?",
    "ಚಲನಚಿತ್ರ ಉತ್ತಮವಾಗಿತ್ತು।",
    "ನಾನು ಕೆಲಸ ಮಾಡುತ್ತಿದ್ದೇನೆ।",
]

# ============================================================
# CODE-MIXED TEST DATA
# ============================================================

CODE_MIXED_EXAMPLES = [
    ("This is damn cool yaar, truly!", "en-hi", "Hinglish - English/Hindi mix"),
    ("That movie was amazing bro!", "en", "Informal English"),
    ("El trabajo es muy difícil pero lo haré.", "es", "Spanish with neutral tone"),
    ("Main kal office jaa raha hoon.", "en-hi", "Hinglish - sentence mixing"),
    ("C'est très bien, mon ami!", "fr", "French with friendly tone"),
]

# ============================================================
# OBFUSCATION TEST DATA
# ============================================================

OBFUSCATION_MAPPINGS = {
    "fuck": [
        "f4ck", "f*ck", "f**k", "f u c k",
        "phuck", "fuk", "feck", "f@ck",
        "fxck", "fk", "fucx", "fuuck",
    ],
    "shit": [
        "sh1t", "s**t", "sh*t", "sht",
        "shit", "shyt", "sh!t", "sht.",
    ],
    "ass": [
        "@ss", "a$$", "azz", "as5",
        "arse", "a**", "azz", "4ss",
    ],
    "bitch": [
        "b1tch", "b**ch", "b*tch", "bih",
        "biatch", "bich", "bitxh", "btch",
    ],
    "damn": [
        "d4mn", "d**n", "dmn", "dam",
        "damn", "damb", "d@mn", "dmmm",
    ],
    "hell": [
        "h3ll", "h**l", "hll", "he11",
        "hell", "h3l", "hll", "he77",
    ],
}

# ============================================================
# TEST GENERATOR FUNCTIONS
# ============================================================

def generate_obfuscated_profanity(word: str, obfuscation_type: ObfuscationType) -> List[str]:
    """Generate obfuscated versions of profanity."""
    if obfuscation_type == ObfuscationType.NONE:
        return [word]
    
    if obfuscation_type == ObfuscationType.LEET_SPEAK:
        return OBFUSCATION_MAPPINGS.get(word, [word])
    
    if obfuscation_type == ObfuscationType.HOMOGLYPH:
        # Simple homoglyph examples
        homoglyphs = {
            'a': ['а', 'ɑ', 'α'],
            'e': ['е', 'ε', 'ɛ'],
            'o': ['о', '0', 'ο'],
            'i': ['і', '1', 'ι'],
        }
        results = [word]
        for char, replacements in homoglyphs.items():
            for replacement in replacements:
                results.append(word.replace(char, replacement))
        return results
    
    if obfuscation_type == ObfuscationType.SPACING:
        return [word[0] + ' ' + ' '.join(word[1:]), word[:2] + ' ' + word[2:]]
    
    if obfuscation_type == ObfuscationType.NUMERIC:
        numeric_map = {'a': '4', 'e': '3', 'i': '1', 'o': '0', 's': '5'}
        result = ''.join(numeric_map.get(c.lower(), c) for c in word)
        return [result]
    
    return [word]


def get_test_examples() -> List[TestExample]:
    """Generate comprehensive test examples."""
    examples = []
    
    # Clean content for all languages
    for text in ENGLISH_CLEAN:
        examples.append(TestExample(
            text=text, language="en", category=ContentCategory.CLEAN,
            tier=LanguageTier.HIGH, expected_result=True
        ))
    
    for text in SPANISH_CLEAN:
        examples.append(TestExample(
            text=text, language="es", category=ContentCategory.CLEAN,
            tier=LanguageTier.HIGH, expected_result=True
        ))
    
    for text in GERMAN_CLEAN:
        examples.append(TestExample(
            text=text, language="de", category=ContentCategory.CLEAN,
            tier=LanguageTier.HIGH, expected_result=True
        ))
    
    for text in FRENCH_CLEAN:
        examples.append(TestExample(
            text=text, language="fr", category=ContentCategory.CLEAN,
            tier=LanguageTier.HIGH, expected_result=True
        ))
    
    for text in ARABIC_CLEAN:
        examples.append(TestExample(
            text=text, language="ar", category=ContentCategory.CLEAN,
            tier=LanguageTier.MEDIUM, expected_result=True
        ))
    
    for text in RUSSIAN_CLEAN:
        examples.append(TestExample(
            text=text, language="ru", category=ContentCategory.CLEAN,
            tier=LanguageTier.MEDIUM, expected_result=True
        ))
    
    for text in HINDI_CLEAN:
        examples.append(TestExample(
            text=text, language="hi", category=ContentCategory.CLEAN,
            tier=LanguageTier.LOW, expected_result=True
        ))
    
    for text in TAMIL_CLEAN:
        examples.append(TestExample(
            text=text, language="ta", category=ContentCategory.CLEAN,
            tier=LanguageTier.LOW, expected_result=True
        ))
    
    # Profanity tests
    for text, _ in ENGLISH_PROFANITY:
        examples.append(TestExample(
            text=text, language="en", category=ContentCategory.PROFANITY,
            tier=LanguageTier.HIGH, expected_result=False,
            notes="Basic English profanity"
        ))
    
    for text in SPANISH_PROFANITY:
        examples.append(TestExample(
            text=text, language="es", category=ContentCategory.PROFANITY,
            tier=LanguageTier.HIGH, expected_result=False,
            notes="Spanish profanity"
        ))
    
    for text in GERMAN_PROFANITY:
        examples.append(TestExample(
            text=text, language="de", category=ContentCategory.PROFANITY,
            tier=LanguageTier.HIGH, expected_result=False,
            notes="German profanity"
        ))
    
    for text in FRENCH_PROFANITY:
        examples.append(TestExample(
            text=text, language="fr", category=ContentCategory.PROFANITY,
            tier=LanguageTier.HIGH, expected_result=False,
            notes="French profanity"
        ))
    
    for text in ARABIC_PROFANITY:
        examples.append(TestExample(
            text=text, language="ar", category=ContentCategory.PROFANITY,
            tier=LanguageTier.MEDIUM, expected_result=False,
            notes="Arabic profanity"
        ))
    
    for text in RUSSIAN_PROFANITY:
        examples.append(TestExample(
            text=text, language="ru", category=ContentCategory.PROFANITY,
            tier=LanguageTier.MEDIUM, expected_result=False,
            notes="Russian profanity"
        ))
    
    for text in HINDI_PROFANITY:
        examples.append(TestExample(
            text=text, language="hi", category=ContentCategory.PROFANITY,
            tier=LanguageTier.LOW, expected_result=False,
            notes="Hindi profanity"
        ))
    
    # Low-resource language tests
    for text in AMHARIC_CLEAN:
        examples.append(TestExample(
            text=text, language="am", category=ContentCategory.CLEAN,
            tier=LanguageTier.LOW, expected_result=True,
            notes="Amharic clean content"
        ))
    
    for text in KANNADA_CLEAN:
        examples.append(TestExample(
            text=text, language="kn", category=ContentCategory.CLEAN,
            tier=LanguageTier.LOW, expected_result=True,
            notes="Kannada clean content"
        ))
    
    # Obfuscation tests
    base_profanity = [
        ("fuck you", "en", False),
        ("shit happens", "en", False),
        ("asshole", "en", False),
        ("bitch", "en", False),
    ]
    
    for word, lang, _ in base_profanity:
        for obfuscation_type in ObfuscationType:
            obfuscated = generate_obfuscated_profanity(word.split()[0], obfuscation_type)
            for variant in obfuscated[:3]:  # Limit variants
                examples.append(TestExample(
                    text=variant + " " + " ".join(word.split()[1:]),
                    language=lang, category=ContentCategory.PROFANITY,
                    tier=LanguageTier.HIGH, expected_result=False,
                    obfuscation=obfuscation_type,
                    notes=f"Obfuscation type: {obfuscation_type.value}"
                ))
    
    return examples


def export_test_data(filepath: str):
    """Export test data to JSON file."""
    examples = get_test_examples()
    data = {
        "total_examples": len(examples),
        "examples": [
            {
                "text": e.text,
                "language": e.language,
                "category": e.category.value,
                "tier": e.tier.value,
                "obfuscation": e.obfuscation.value,
                "expected_result": e.expected_result,
                "notes": e.notes,
            }
            for e in examples
        ]
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


if __name__ == "__main__":
    data = export_test_data("mocks/data/multilingual_test_data.json")
    print(f"Generated {data['total_examples']} test examples")
