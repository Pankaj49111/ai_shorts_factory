import re

def clean_script(script):

    lines = script.splitlines()

    cleaned = []

    for line in lines:
        line = line.strip()

        if not line:
            continue

        # Skip lines that look like word counts
        if re.search(r"(?i)^(word\s*count|words):\s*\d+", line):
            continue
        if re.search(r"(?i)\b\d+\s*words\b$", line) and len(line.split()) <= 5:
            continue

        # remove labels
        if line.startswith("HOOK:"):
            cleaned.append(line[6:].strip())
            continue
        if line.startswith("BODY:"):
            cleaned.append(line[6:].strip())
            continue
        if line.startswith("OUTRO:"):
            cleaned.append(line[7:].strip())
            continue
        
        # handle markdown bold labels anywhere in the line
        line = line.replace("**HOOK:**", "")
        line = line.replace("**BODY:**", "")
        line = line.replace("**OUTRO:**", "")
        
        # Remove any remaining asterisks used for emphasis/bold/italics
        line = line.replace("*", "")
        
        # trim any remaining whitespace after removing bold labels
        line = line.strip()
        
        if line:
            cleaned.append(line)

    return " ".join(cleaned)