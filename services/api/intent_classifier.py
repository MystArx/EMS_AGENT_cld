import re

def classify_intent(text: str) -> str:
    text = text.lower().strip()

    if re.match(r"^(hi|hello|hey)\b", text):
        return "GREETING"

    if "how do i" in text:
        return "FAQ"

    return "ANALYTICS"
