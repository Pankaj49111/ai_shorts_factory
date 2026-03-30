from voice_generator import generate_voice
import os

# Ensure the output directory exists
os.makedirs("assets/audio", exist_ok=True)

test_text = "This is a test sentence to compare speech speeds. Listen carefully to the difference."

print("Generating audio with default speed (1.15x)...")
generate_voice(
    test_text,
    "assets/audio/test_speed_115x.mp3",
    voice="en-US-JennyNeural" # Using JennyNeural as per pipeline_runner
)

print("Generating audio with 1.2x speed...")
generate_voice(
    test_text,
    "assets/audio/test_speed_120x.mp3",
    voice="en-US-JennyNeural", # Using JennyNeural as per pipeline_runner
    rate="+20%" # Explicitly set to 1.2x speed
)

print("\nTest complete. Check 'assets/audio/test_speed_115x.mp3' and 'assets/audio/test_speed_120x.mp3'")
print("You can run this test by executing: python pipeline/test_tts.py")
