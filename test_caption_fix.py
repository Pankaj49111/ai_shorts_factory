#!/usr/bin/env python3
"""
Test caption positioning fix.
Generates a short test video with captions to verify they're not cut off.
"""

import os
from moviepy import ColorClip, TextClip
from pipeline.caption_generator import build_caption_clips

# Use existing narration audio if available, otherwise create test audio
test_audio = "assets/audio/narration.mp3"
if not os.path.exists(test_audio):
    print("No existing narration.mp3 found, creating test audio...")
    # Create a 3-second silent audio file
    from moviepy import AudioClip
    silent_audio = AudioClip(lambda t: 0, duration=3)
    silent_audio.write_audiofile(test_audio, fps=44100)
    print(f"Created test audio: {test_audio}")
else:
    print(f"Using existing audio: {test_audio}")

# Test caption generation
print("Testing caption generation...")
try:
    caption_clips = build_caption_clips(test_audio, video_size=(1080, 1920), model_size="tiny")
    print(f"Generated {len(caption_clips)} caption clips")

    if caption_clips:
        # Create a simple background video
        from moviepy import CompositeVideoClip, AudioFileClip
        bg = ColorClip(size=(1080, 1920), color=(0, 0, 0), duration=3)

        # Add captions
        test_video = CompositeVideoClip([bg] + caption_clips)

        # Add audio
        if os.path.exists(test_audio):
            audio = AudioFileClip(test_audio)
            test_video = test_video.with_audio(audio.subclipped(0, min(3, audio.duration)))

        output_path = "assets/final_ready/caption_test.mp4"
        test_video.write_videofile(output_path, fps=30, codec="libx264")
        print(f"Test video saved: {output_path}")
        print("Check the video to verify captions are fully visible and not cut off.")
    else:
        print("No captions generated (likely no speech detected in audio)")

except Exception as e:
    print(f"Error testing captions: {e}")
    import traceback
    traceback.print_exc()
