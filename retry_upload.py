import sys
import json
from pathlib import Path

# Add the current directory to sys.path so we can import from pipeline
sys.path.append(str(Path(__file__).parent))

from pipeline_runner import _get_next_publish_time
from pipeline.youtube_uploader import upload_short, QuotaExceededError

def retry_upload(run_dir_str):
    run_dir = Path(run_dir_str)
    meta_path = run_dir / "meta.json"
    
    if not meta_path.exists():
        print(f"Error: {meta_path} not found.")
        return
        
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
        
    yt_meta = meta.get("youtube_metadata")
    if not yt_meta:
        print("Error: No youtube_metadata found in meta.json.")
        return
        
    output_path = meta.get("output_path", str(run_dir / "output.mp4"))
    if not Path(output_path).exists():
        print(f"Error: Video file {output_path} not found.")
        return

    print(f"Retrying upload for: {yt_meta['title']}")
    
    # We do not commit the time yet. We just get the proposed time.
    publish_at_iso = _get_next_publish_time(commit=False)
    print(f"Using scheduled time: {publish_at_iso}")
    
    try:
        video_id = upload_short(
            video_path         = output_path,
            title              = yt_meta["title"],
            description        = yt_meta["description"],
            tags               = yt_meta["tags"],
            category_id        = yt_meta.get("category_id", "27"),
            privacy            = "private",
            notify_subscribers = False,
            publish_at         = publish_at_iso,
        )
        
        # If we get here, upload succeeded! Now we commit the time so the next video gets the next slot.
        _get_next_publish_time(commit=True)

        print(f"\nSuccess! Uploaded: https://www.youtube.com/shorts/{video_id}")
        
        # Update meta.json with the successful upload info
        meta["youtube_video_id"] = video_id
        meta["youtube_url"] = f"https://www.youtube.com/shorts/{video_id}"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            
    except QuotaExceededError as q_err:
        print(f"\nUpload failed: ⚠️ {q_err}")
        print("YouTube quota limit reached for today. Please try again tomorrow.")
    except Exception as exc:
        print(f"\nUpload failed: {exc}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python retry_upload.py <run_directory_path>")
        print(r"Example: python retry_upload.py assets\runs\20260327_145149")
        sys.exit(1)
    retry_upload(sys.argv[1])