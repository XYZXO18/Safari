from rembg import remove
from PIL import Image
import os

img_dir = "static/images"
images = [
    "riyadh_icon.png",
    "makkah_icon.png",
    "madinah_icon.png",
    "eastern_icon.png",
    "asir_icon.png",
    "alula_icon.png"
]

for img_name in images:
    img_path = os.path.join(img_dir, img_name)
    if os.path.exists(img_path):
        print(f"Processing {img_name}...")
        try:
            input_img = Image.open(img_path)
            output_img = remove(input_img)
            output_img.save(img_path)
            print(f"Saved {img_name}")
        except Exception as e:
            print(f"Error processing {img_name}: {e}")
