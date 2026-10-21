"""The shared vocabulary between the planner (which picks from it) and the stickman renderer (which draws it)."""
import re

PROPS = (
    "brain", "heart", "broken_heart", "clock", "phone", "bulb", "question", "alert", "chart_up", "chart_down",
    "people", "house", "magnifier", "lock", "battery", "scale", "mask", "target", "book", "eyes",
)
# Props that fit any sentence; the fallback planner cycles through these when no keyword matches.
NEUTRAL = ("bulb", "magnifier", "question", "book", "target", "scale")
POSES = ("idle", "talk", "point", "shrug", "think", "excited", "sad", "stop", "hips")
EMOTIONS = ("neutral", "happy", "sad", "surprised", "angry", "worried", "thinking")

# Fallback planner: first matching rule wins. Order matters (specific before generic).
KEYWORDS = (
    (r"\b(broken|breakup|break up|heartbreak|grief|lonely|loneliness|reject)", "broken_heart"),
    (r"\b(love|loved|attachment|affection|crush|romantic|heart)\b", "heart"),
    (r"\b(brain|neuron|mind|memory|memories|cognitive|mental)\b", "brain"),
    (r"\b(time|clock|hour|minute|wait|late|delay|procrastinat|deadline|years?)\b", "clock"),
    (r"\b(phone|text|texting|scroll|social media|notification|message|app)\b", "phone"),
    (r"\b(idea|realize|realise|insight|understand|learn|aha|solution|creative)\b", "bulb"),
    (r"\b(why|wonder|confus|question|mystery|unknown|ever)\b", "question"),
    (r"\b(danger|warning|threat|panic|alarm|careful|toxic|red flag)\b", "alert"),
    (r"\b(grow|growth|improve|success|progress|better|rise|increase)\b", "chart_up"),
    (r"\b(fall|decline|drop|worse|lose|loss|burnout|decrease|fail)\b", "chart_down"),
    (r"\b(friend|friends|people|partner|couple|relationship|together|others|everyone|social|family)\b", "people"),
    (r"\b(home|house|childhood|parents?|grew up)\b", "house"),
    (r"\b(notice|look|search|find|study|studies|research|evidence|observe)\b", "magnifier"),
    (r"\b(secret|private|hide|hidden|trapped|boundary|boundaries|safe|trust)\b", "lock"),
    (r"\b(tired|exhaust|energy|drained|burned|sleep|rest)\b", "battery"),
    (r"\b(choice|decide|decision|balance|weigh|fair|compare)\b", "scale"),
    (r"\b(pretend|mask|fake|persona|image|people-pleas|act like|perform)\b", "mask"),
    (r"\b(goal|focus|aim|habit|target|purpose|motivat|discipline)\b", "target"),
    (r"\b(book|read|story|chapter|lesson|theory)\b", "book"),
    (r"\b(watch|judge|judging|stare|eyes|attention|seen|see)\b", "eyes"),
)

_COMPILED = tuple((re.compile(p, re.I), prop) for p, prop in KEYWORDS)


def guess_prop(text: str, fallback: str) -> str:
    for rx, prop in _COMPILED:
        if rx.search(text):
            return prop
    return fallback


def emotion_for(delivery: str, text: str) -> str:
    t = text.lower()
    if "?" in text:
        return "thinking"
    if delivery == "hook":
        return "surprised"
    if delivery == "tense":
        return "worried"
    if delivery == "warm":
        return "happy"
    if delivery == "reflective":
        return "sad" if re.search(r"\b(alone|lonely|hurt|pain|sad|lost|loss|fear|afraid)\b", t) else "thinking"
    return "neutral"
