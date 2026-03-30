import re

EMOTION_SETTINGS = {
 'surprise': {'pitch': '+10%', 'rate': '+6%'},
 'curiosity': {'pitch': '+3%', 'rate': '+2%'},
 'explanation': {'pitch': '0%', 'rate': '0%'},
 'excited': {'pitch': '+8%', 'rate': '+7%'},
 'cta': {'pitch': '+3%', 'rate': '+2%'}
}

def split_into_sentences(text):
 parts=[]
 for line in text.splitlines():
  line=line.strip()
  if not line or line.endswith(':'):
   continue
  parts.append(line)
 return parts

def detect_emotion(sentence):
 s=sentence.lower()
 if "did you know" in s:
  return "surprise"
 if "scientists" in s:
  return "curiosity"
 if "called" in s:
  return "excited"
 if "follow" in s:
  return "cta"
 return "explanation"

def sentence_to_ssml(sentence,emotion):
 settings=EMOTION_SETTINGS.get(emotion)
 return f'<prosody pitch="{settings["pitch"]}" rate="{settings["rate"]}">{sentence}</prosody>'

def build_ssml(script, voice="en-US-JennyNeural"):
 sentences = split_into_sentences(script)
 parts = []
 for s in sentences:
  e = detect_emotion(s)
  parts.append(sentence_to_ssml(s, e))
  parts.append('<break time="300ms"/>')

 body = "\n".join(parts)
 return f'<speak>{body}</speak>'
