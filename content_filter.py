from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


DetectionLevel = Literal["obvious", "suspicious"]


@dataclass(frozen=True)
class ContentDetection:
    level: DetectionLevel
    rule: str
    matched: str


_CONFUSABLES = str.maketrans(
    {
        "a": "а",
        "c": "с",
        "e": "е",
        "k": "к",
        "m": "м",
        "o": "о",
        "p": "р",
        "t": "т",
        "x": "х",
        "y": "у",
        "0": "о",
        "3": "з",
        "4": "ч",
        "6": "б",
    }
)

_HATEFUL_ROOTS = (
    "черножоп",
    "черномаз",
    "чурк",
    "хач",
    "жидяр",
    "жид",
    "хохол",
    "хохл",
    "кацап",
    "москал",
    "русн",
    "пидор",
    "пидарас",
    "гомик",
    "трансух",
    "даун",
    "аутист",
    "шизофрен",
    "инвалид",
)

_LATIN_HATEFUL_ROOTS = (
    "chernozhop",
    "chernomaz",
    "churka",
    "hach",
    "zhid",
    "hohol",
    "kacap",
    "moskal",
    "rusnya",
    "pidor",
    "pidaras",
    "gomik",
    "transuha",
    "daun",
    "autist",
    "shizofren",
)

_SEVERE_INSULT_ROOTS = (
    "мраз",
    "твар",
    "уебок",
    "уебан",
    "долбоеб",
    "мудак",
    "гнид",
    "чмо",
    "падаль",
    "ничтож",
    "урод",
    "дегенерат",
    "кретин",
    "дебил",
    "имбецил",
    "шлюх",
    "проститут",
)

_LATIN_SEVERE_INSULT_ROOTS = (
    "mraz",
    "tvar",
    "uebok",
    "dolboeb",
    "mudak",
    "gnida",
    "chmo",
    "urod",
    "degenerat",
    "debil",
    "imbecil",
    "shluha",
)

_ROOT_EXCEPTIONS = (
    "жидк",  # жидкость, жидкий
)

_DIRECT_ADDRESS_RE = re.compile(
    r"(?:^|\s)(?:ты|вы|он|она|они|этот|эта|эти|все|вся|весь)(?:\s|$)|"
    r"^\s*@?[a-zа-я0-9_]{2,32}\s*[,;:—–-]",
    re.IGNORECASE,
)

_SELF_HARM_PATTERNS = (
    (re.compile(r"\bk[\W_]*y[\W_]*s\b", re.IGNORECASE), "призыв к самоубийству"),
    (re.compile(r"\b(?:убейся|сдохни|выпились|повесься|застрелись)\b", re.IGNORECASE), "призыв к самоубийству или смерти"),
)

_GROUP_VIOLENCE_RE = re.compile(
    r"\b(?:убить|убива(?:й|йте)|уничтожить|уничтожа(?:й|йте)|вырезать|выреза(?:й|йте))\s+"
    r"(?:их\s+)?(?:всех|каждого|каждую)\b",
    re.IGNORECASE,
)

_THREAT_RE = re.compile(
    r"\b(?:я\s+тебя\s+|тебя\s+|тебе\s+)?(?:убью|зарежу|застрелю|сломаю|изобью|найду\s+и\s+убью)\b",
    re.IGNORECASE,
)

_CONTEXT_RE = re.compile(
    r"\b(?:цитат\w*|слово\w*|назвал\w*|называ(?:й|ют|л)\w*|сказал\w*|написал\w*|"
    r"обсужд\w*|запрещен\w*|банворд\w*|список\w*|наказыва\w*|осужд\w*|"
    r"не\s+говори\w*|нельзя\s+говорить)\b",
    re.IGNORECASE,
)


def normalize_content(value: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", value).lower().replace("ё", "е")
    normalized = "".join(
        character if unicodedata.category(character) not in {"Cf", "Cc"} else " "
        for character in normalized
    )
    normalized = re.sub(r"(.)\1{2,}", r"\1\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized, normalized.translate(_CONFUSABLES)


def _root_match(text: str, roots: tuple[str, ...]) -> tuple[str, str] | None:
    words = re.findall(r"[a-zа-я0-9_]+", text)
    for word in words:
        compact_word = word.replace("_", "")
        if compact_word.startswith(_ROOT_EXCEPTIONS):
            continue
        for root in roots:
            if compact_word.startswith(root):
                return root, word

    # Отдельно проверяем намеренное разделение букв знаками или пробелами.
    for root in roots:
        separated = r"(?<![a-zа-я0-9])" + r"[\W_]*".join(map(re.escape, root)) + r"[a-zа-я0-9_]*"
        match = re.search(separated, text, re.IGNORECASE)
        if match:
            compact_match = re.sub(r"[^a-zа-я0-9]", "", match.group(0))
            if compact_match.startswith(_ROOT_EXCEPTIONS):
                continue
            return root, match.group(0)
    return None


def detect_prohibited_content(
    content: str,
    *,
    has_mention: bool = False,
    is_reply: bool = False,
) -> ContentDetection | None:
    plain, folded = normalize_content(content)
    if not plain:
        return None
    contextualized = bool(_CONTEXT_RE.search(folded))

    hard_r = re.search(r"(?<![a-z])n[\W_]*[i1!|][\W_]*g[\W_]*g[\W_]*[e3][\W_]*r(?![a-z])", plain)
    if hard_r:
        return ContentDetection("obvious", "расистский слур", hard_r.group(0))
    cyrillic_hard_r = re.search(r"(?<![а-я])н[\W_]*и[\W_]*г[\W_]*г[\W_]*е[\W_]*р(?![а-я])", folded)
    if cyrillic_hard_r:
        return ContentDetection("obvious", "расистский слур", cyrillic_hard_r.group(0))

    for pattern, rule in _SELF_HARM_PATTERNS:
        match = pattern.search(plain) or pattern.search(folded)
        if match:
            return ContentDetection("suspicious" if contextualized else "obvious", rule, match.group(0))

    group_violence = _GROUP_VIOLENCE_RE.search(folded)
    if group_violence:
        return ContentDetection(
            "suspicious" if contextualized else "obvious",
            "призыв к насилию над группой людей",
            group_violence.group(0),
        )

    hateful = _root_match(folded, _HATEFUL_ROOTS) or _root_match(plain, _LATIN_HATEFUL_ROOTS)
    if hateful:
        root, matched = hateful
        level: DetectionLevel = "suspicious" if contextualized else "obvious"
        rule = "дискриминационное оскорбление" if not contextualized else "возможное цитирование дискриминационного оскорбления"
        return ContentDetection(level, rule, matched or root)

    threat = _THREAT_RE.search(folded)
    if threat:
        return ContentDetection("suspicious", "возможная угроза", threat.group(0))

    insult = _root_match(folded, _SEVERE_INSULT_ROOTS) or _root_match(plain, _LATIN_SEVERE_INSULT_ROOTS)
    if insult:
        root, matched = insult
        return ContentDetection("suspicious", "возможное тяжёлое оскорбление", matched or root)

    return None
