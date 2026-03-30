import os
import sys

# Add pipeline directory to path so we can import from it
sys.path.append(os.path.join(os.path.dirname(__file__), "pipeline"))
from voice_generator import generate_voice

# Ensure the output directory exists
output_dir = "assets/audio/test_voices"
os.makedirs(output_dir, exist_ok=True)

# 24-word test script
test_text = "Did you know that honey never spoils? Archaeologists have found pots of honey in ancient Egyptian tombs that are over three thousand years old."

popular_voices = [
    # The US Champions
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-US-ChristopherNeural",
    # Canadian (Neutral & Clear)
    "en-CA-ClaraNeural",
    "en-CA-LiamNeural",
    # Australian (Friendly & Engaging)
    "en-AU-NatashaNeural",
    "en-AU-WilliamMultilingualNeural",
    # Expressive Indian
    "en-IN-NeerjaExpressiveNeural",
    # Storyteller Irish
    "en-IE-ConnorNeural",
    "en-IE-EmilyNeural"
]

print("Generating voice samples (this may take a minute)...")
print("-" * 50)

for voice in popular_voices:
    output_path = os.path.join(output_dir, f"{voice}.mp3")
    print(f"Generating sample for: {voice}")
    try:
        # Using default rate (+15%) as set in voice_generator.py
        generate_voice(test_text, output_path, voice=voice)
        print(f"  -> Saved to {output_path}")
    except Exception as e:
        print(f"  -> Failed: {e}")

print("-" * 50)
print(f"All samples generated in: {output_dir}")
