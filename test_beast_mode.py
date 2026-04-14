#!/usr/bin/env python3
import os
from moviepy import ColorClip, TextClip, AudioClip, CompositeVideoClip, AudioFileClip
from pipeline.caption_generator import build_caption_clips

def main():
    test_audio = "assets/runs/20260412_234447/narration.mp3"
    if not os.path.exists(test_audio):
        print("No audio found, please point to a valid narration.mp3 file.")
        return

    print("Testing beast mode caption generation...")
    try:
        # Use beast mode
        caption_clips = build_caption_clips(test_audio, video_size=(1080, 1920), model_size="base", caption_mode="beast")
        print(f"Generated {len(caption_clips)} caption clips")

        if caption_clips:
            # Take only the first 5 seconds to test
            test_dur = 5.0
            bg = ColorClip(size=(1080, 1920), color=(50, 50, 50), duration=test_dur)
            
            # Filter clips that fall within our test duration
            valid_clips = []
            for c in caption_clips:
                if c.start < test_dur:
                    valid_clips.append(c)

            test_video = CompositeVideoClip([bg] + valid_clips, size=(1080, 1920)).with_duration(test_dur)

            audio = AudioFileClip(test_audio)
            test_video = test_video.with_audio(audio.subclipped(0, min(test_dur, audio.duration)))

            output_path = "beast_test.mp4"
            test_video.write_videofile(output_path, fps=30, codec="libx264")
            print(f"Test video saved: {output_path}")
            
    except Exception as e:
        print(f"Error testing captions: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
