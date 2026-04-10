import asyncio
import edge_tts
import os
import sys
import time

def generate_voice(text, output, voice="en-US-JennyNeural", rate="+18%", pitch="+12Hz"): # Tweaked for higher energy
    """
    Generate voice using Edge TTS.

    Args:
        text: Text to convert to speech
        output: Output file path
        voice: Voice to use (default: en-US-JennyNeural - clear and natural)
        rate: Speech rate adjustment (-50% to +50%)
        pitch: Pitch adjustment (-100Hz to +100Hz)
    """

    os.makedirs(os.path.dirname(output), exist_ok=True)

    if os.path.exists(output):
        os.remove(output)

    return _generate_edge_tts(text, output, voice, rate, pitch)


def _generate_edge_tts(text, output, voice, rate, pitch):
    """Generate voice using Edge TTS (free, good quality)."""

    async def _generate():
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch
        )
        await communicate.save(output)

    try:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        asyncio.run(_generate())

    except Exception as e:
        print("❌ Edge TTS Error:", e)
        raise Exception("Edge TTS generation failed")

    # ✅ WAIT for file to stabilize
    time.sleep(1)

    # ✅ Retry check
    for _ in range(3):
        if os.path.exists(output) and os.path.getsize(output) > 1000:
            print(f"✅ Edge TTS Audio generated: {output} ({os.path.getsize(output)} bytes)")
            return
        time.sleep(0.5)

    raise Exception("❌ Edge TTS failed — invalid audio file")
