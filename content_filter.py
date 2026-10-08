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


def _masked_sequence_regex(parts: tuple[str, ...], alphabet: str) -> re.Pattern[str]:
    """Match a compact/punctuated word or letters deliberately split one by one."""
    punctuation_separated = r"[^\w\s]*".join(parts)
    fully_spaced = r"(?:[^\w]*\s[^\w]*)".join(parts)
    return re.compile(
        rf"(?<![{alphabet}])(?:{punctuation_separated}|{fully_spaced})(?![{alphabet}])",
        re.IGNORECASE,
    )


_LATIN_HARD_SLUR_RE = _masked_sequence_regex(
    ("n", r"[i1!|]", "g", "g", r"[e3]", "r"),
    "a-z",
)
_CYRILLIC_HARD_SLUR_RE = _masked_sequence_regex(
    ("н", "и", "г", "г", "е", "р"),
    "а-я",
)
_KYS_RE = _masked_sequence_regex(("k", "y", "s"), "a-z")

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
    "шизофреник",
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
    "shizofrenik",
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

# Корни нельзя проверять обычным startswith: тогда «даунтаун», «жидкость»
# или «хачапури» ошибочно становятся нарушениями. Для каждого корня перечислены
# только окончания, которые образуют формы самого запрещённого слова.
_COMMON_NOUN_SUFFIXES = frozenset((
    "", "а", "у", "ом", "е", "ы", "и", "ов", "ей", "ам", "ям", "ами", "ями", "ах", "ях",
))
_COMMON_LATIN_SUFFIXES = frozenset((
    "", "a", "u", "om", "e", "y", "i", "ov", "ey", "am", "ami", "ah",
))
_ADJECTIVE_SUFFIXES = frozenset((
    "ый", "ая", "ое", "ые", "ого", "ой", "ому", "ым", "ую", "ых", "ыми",
))

_ROOT_SUFFIXES: dict[str, frozenset[str]] = {
    "черножоп": _ADJECTIVE_SUFFIXES,
    "черномаз": _ADJECTIVE_SUFFIXES,
    "чурк": frozenset(("а", "и", "у", "е", "ой", "ою", "ам", "ами", "ах")),
    "хач": _COMMON_NOUN_SUFFIXES | frozenset((
        "ур", "ура", "уру", "уром", "уре", "уры", "уров", "урам", "урами", "урах",
    )),
    "жидяр": frozenset(("а", "у", "е", "ой", "ою", "ы", "ам", "ами", "ах")),
    "жид": _COMMON_NOUN_SUFFIXES,
    "хохол": frozenset(("", "ы")),
    "хохл": frozenset(("а", "у", "ом", "е", "ы", "ов", "ам", "ами", "ах")),
    "кацап": _COMMON_NOUN_SUFFIXES,
    "москал": frozenset(("ь", "я", "ю", "ем", "е", "и", "ей", "ям", "ями", "ях")),
    "русн": frozenset(("я", "ю", "е", "и", "ей")),
    "пидор": _COMMON_NOUN_SUFFIXES,
    "пидарас": _COMMON_NOUN_SUFFIXES,
    "гомик": _COMMON_NOUN_SUFFIXES,
    "трансух": frozenset(("а", "и", "у", "е", "ой", "ою", "ам", "ами", "ах")),
    "даун": _COMMON_NOUN_SUFFIXES | frozenset((
        "ский", "ская", "ское", "ские", "ского", "ской", "скому", "ским", "скую", "ских", "скими",
    )),
    "аутист": _COMMON_NOUN_SUFFIXES,
    "шизофреник": _COMMON_NOUN_SUFFIXES,
    "инвалид": _COMMON_NOUN_SUFFIXES,
    "chernozhop": frozenset(("iy", "aya", "oe", "ye", "ogo", "omu", "ym", "uyu", "yh", "ymi")),
    "chernomaz": frozenset(("iy", "aya", "oe", "ye", "ogo", "omu", "ym", "uyu", "yh", "ymi")),
    "churka": _COMMON_LATIN_SUFFIXES,
    "hach": _COMMON_LATIN_SUFFIXES | frozenset(("ur", "ura", "uru", "urom", "ure", "ury", "urov")),
    "zhid": _COMMON_LATIN_SUFFIXES,
    "hohol": _COMMON_LATIN_SUFFIXES,
    "kacap": _COMMON_LATIN_SUFFIXES,
    "moskal": _COMMON_LATIN_SUFFIXES,
    "rusnya": _COMMON_LATIN_SUFFIXES,
    "pidor": _COMMON_LATIN_SUFFIXES,
    "pidaras": _COMMON_LATIN_SUFFIXES,
    "gomik": _COMMON_LATIN_SUFFIXES,
    "transuha": _COMMON_LATIN_SUFFIXES,
    "daun": _COMMON_LATIN_SUFFIXES,
    "autist": _COMMON_LATIN_SUFFIXES,
    "shizofrenik": _COMMON_LATIN_SUFFIXES,
    "мраз": frozenset(("ь", "и", "ью", "ей", "ям", "ями", "ях")),
    "твар": frozenset(("ь", "и", "ью", "ей", "ям", "ями", "ях")),
    "уебок": frozenset(("",)),
    "уебан": _COMMON_NOUN_SUFFIXES,
    "долбоеб": _COMMON_NOUN_SUFFIXES,
    "мудак": _COMMON_NOUN_SUFFIXES,
    "гнид": frozenset(("а", "ы", "е", "у", "ой", "ою", "ам", "ами", "ах")),
    "чмо": frozenset(("",)),
    "падаль": frozenset(("", "ю", "и")),
    "ничтож": frozenset(("ество", "ества", "еству", "еством", "естве", "ествах", "ествами")),
    "урод": _COMMON_NOUN_SUFFIXES,
    "дегенерат": _COMMON_NOUN_SUFFIXES,
    "кретин": _COMMON_NOUN_SUFFIXES,
    "дебил": _COMMON_NOUN_SUFFIXES,
    "имбецил": _COMMON_NOUN_SUFFIXES,
    "шлюх": frozenset(("а", "и", "е", "у", "ой", "ою", "ам", "ами", "ах")),
    "проститут": frozenset(("ка", "ки", "ке", "ку", "кой", "кою", "ок", "кам", "ками", "ках")),
    "mraz": _COMMON_LATIN_SUFFIXES,
    "tvar": _COMMON_LATIN_SUFFIXES,
    "uebok": _COMMON_LATIN_SUFFIXES,
    "dolboeb": _COMMON_LATIN_SUFFIXES,
    "mudak": _COMMON_LATIN_SUFFIXES,
    "gnida": _COMMON_LATIN_SUFFIXES,
    "chmo": frozenset(("",)),
    "urod": _COMMON_LATIN_SUFFIXES,
    "degenerat": _COMMON_LATIN_SUFFIXES,
    "debil": _COMMON_LATIN_SUFFIXES,
    "imbecil": _COMMON_LATIN_SUFFIXES,
    "shluha": _COMMON_LATIN_SUFFIXES,
}

_EXACT_ROOT_EXCEPTIONS = frozenset((
    "хачу",  # частая опечатка в слове «хочу»
    "hachu",
))

_ROOT_PREFIX_EXCEPTIONS = (
    "жидк",  # жидкость, жидкий
    "уродил",  # уродился, уродилась
    "хачапур",  # хачапури и производные
    "хачипур",
    "хачупур",
    "hachapur",
    "hachipur",
    "hachupur",
)

_SELF_HARM_PATTERNS = (
    (_KYS_RE, "призыв к самоубийству"),
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


def _is_root_exception(value: str) -> bool:
    return value in _EXACT_ROOT_EXCEPTIONS or value.startswith(_ROOT_PREFIX_EXCEPTIONS)


def _is_prohibited_word(value: str, root: str) -> bool:
    if _is_root_exception(value) or not value.startswith(root):
        return False
    return value[len(root):] in _ROOT_SUFFIXES[root]


def _root_match(text: str, roots: tuple[str, ...]) -> tuple[str, str] | None:
    words = re.findall(r"[a-zа-я0-9_]+", text)
    for word in words:
        compact_word = word.replace("_", "")
        for root in roots:
            if _is_prohibited_word(compact_word, root):
                return root, word

    # Отдельно проверяем намеренное разделение букв. Пробелы нельзя считать
    # произвольным разделителем: иначе обычное "да у нас" склеивается в "даун".
    for root in roots:
        boundary = r"(?<![a-zа-я0-9])"
        suffix = r"[a-zа-я0-9_]*"
        punctuation_separated = boundary + r"[^\w\s]*".join(map(re.escape, root)) + suffix
        fully_spaced = boundary + r"(?:[^\w]*\s[^\w]*)".join(map(re.escape, root)) + suffix
        for pattern in (punctuation_separated, fully_spaced):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                compact_match = re.sub(r"[^a-zа-я0-9]", "", match.group(0))
                if _is_prohibited_word(compact_match, root):
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

    hard_r = _LATIN_HARD_SLUR_RE.search(plain)
    if hard_r:
        return ContentDetection("obvious", "расистский слур", hard_r.group(0))
    cyrillic_hard_r = _CYRILLIC_HARD_SLUR_RE.search(folded)
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
