from PIL import Image
import os

def process_avatar(input_path, output_path="assets/avatars/processed.png"):

    img = Image.open(input_path)

    width, height = img.size

    target_ratio = 9 / 16

    current_ratio = width / height

    # If already close to 9:16, just resize
    if abs(current_ratio - target_ratio) < 0.05:
        img = img.resize((1080, 1920), Image.LANCZOS)
    else:
        # Crop center
        new_width = int(height * target_ratio)

        left = (width - new_width) // 2
        right = left + new_width

        img = img.crop((left, 0, right, height))

        img = img.resize((1080, 1920), Image.LANCZOS)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    img.save(output_path)

    return output_path