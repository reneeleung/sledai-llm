import re
import numpy as np
from typing import List


# ---------- Text utilities ----------
def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def split_entities(label: str) -> List[str]:
    if not label or not label.strip():
        return []
    return [normalize_text(x) for x in label.split('\n') if x.strip()]

def tokenize_words(s: str) -> List[str]:
    return re.findall(r"[a-z0-9%]+(?:'[a-z0-9]+)?", normalize_text(s))

def jaccard_overlap(a_tokens: List[str], b_tokens: List[str]) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    a_set, b_set = set(a_tokens), set(b_tokens)
    inter = len(a_set & b_set)
    union = len(a_set | b_set)
    return inter / union if union else 0.0

def exact_phrase_present(phrase: str, text: str) -> bool:
    pattern = r'\b' + re.escape(phrase) + r'\b'
    return re.search(pattern, text) is not None

# ---------- Quoted evidence extraction ----------

def extract_quoted_spans(text: str) -> List[str]:
    spans = re.findall(r'["“”](.+?)["“”]', text) + re.findall(r"'(.+?)'", text)
    spans = list({normalize_text(s) for s in spans if s.strip()})
    return spans

def measure_entity_coverage(entity: str, text: str, quoted_spans: List[str]) -> float:
    if not entity.strip():
        return 0.0
    if exact_phrase_present(entity, text):
        return 1.0
    entity_tokens = tokenize_words(entity)
    best_quote = 0.0
    for q in quoted_spans:
        if exact_phrase_present(entity, q):
            return 1.0
        q_tokens = tokenize_words(q)
        best_quote = max(best_quote, jaccard_overlap(entity_tokens, q_tokens))
    text_tokens = tokenize_words(text)
    fuzzy = jaccard_overlap(entity_tokens, text_tokens)
    return max(best_quote * 1.1, fuzzy)

# ---------- Intent gates with proximity ----------

EXCLUSION_INTENT_WORDS = [
    "exclusion", "exclude", "excluded", "excludes", "excluding",
    "ruled out", "not met", "not meet",
]

TREATMENT_INTENT_WORDS = [
    "treat", "treated", "treatment", "therapy", "therapeutic",
    "responded", "response", "escalated", "escalation",
]

def intent_near_entity(entity: str, text: str, intent_words: List[str], window: int = 50) -> bool:
    text_norm = normalize_text(text)
    entity_norm = normalize_text(entity)
    for m in re.finditer(re.escape(entity_norm), text_norm):
        start, end = m.start(), m.end()
        left = max(0, start - window)
        right = min(len(text_norm), end + window)
        span = text_norm[left:right]
        if any(w in span for w in intent_words):
            return True
    return False

def gated_entity_coverage(entity: str, text: str, quoted_spans: List[str], intent_words: List[str]) -> float:
    base = measure_entity_coverage(entity, text, quoted_spans)
    if base == 0.0:
        return 0.0
    return base if intent_near_entity(entity, text, intent_words) else base * 0.25

# ---------- Anti-hacking penalty ----------

def nonlabel_quote_penalty(text: str, quoted_spans: List[str], label_entities_all: List[str]) -> float:
    if not quoted_spans:
        return 0.0
    label_tokens = set()
    for e in label_entities_all:
        label_tokens.update(tokenize_words(e))
    total_quote_tokens = 0
    nonlabel_tokens = 0
    for q in quoted_spans:
        q_tokens = tokenize_words(q)
        total_quote_tokens += len(q_tokens)
        nonlabel_tokens += sum(1 for tok in q_tokens if tok not in label_tokens)
    if total_quote_tokens == 0:
        return 0.0
    proportion_nonlabel = nonlabel_tokens / total_quote_tokens
    excess = max(0.0, proportion_nonlabel - 0.40)
    penalty = min(0.3, excess * 0.6)
    return penalty

# ---------- Core scoring ----------

def score_entities(label: str, text: str, is_gated: bool, intent_words: List[str]) -> float:
    entities = split_entities(label)
    if not entities:
        return np.nan
    quoted_spans = extract_quoted_spans(text)
    scores = []
    for e in entities:
        if is_gated:
            s = gated_entity_coverage(e, text, quoted_spans, intent_words)
        else:
            s = measure_entity_coverage(e, text, quoted_spans)
        s = max(0.0, min(1.0, s))
        scores.append(s)
    if not scores:
        return 0.0
    return float(np.mean(scores))
