import time
import shutil
from luma.core.interface.serial import i2c
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont

# I2C setup: bus 0, address 0x3C
serial = i2c(port=0, address=0x3C)
device = sh1106(serial)

# Fonts
font_small = ImageFont.load_default()
font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)

start_time = time.time()

while True:
    # Timer
    elapsed = time.time() - start_time
    mm, ss = divmod(int(elapsed), 60)
    ms = int((elapsed - int(elapsed)) * 1000)
    timer_text = f"{mm:02}:{ss:02}.{ms:03}"

    # Disk free space (in GB)
    total, used, free = shutil.disk_usage("/")
    free_gb = free // (1024**3)  # integer GB
    storage_text = f"{free_gb}G"

    # Create frame
    img = Image.new("1", device.size)
    draw = ImageDraw.Draw(img)

    # REC label (top-left)
    draw.text((0, 0), "REC", font=font_small, fill=255)

    # Storage free (top-right) — use bbox instead of textsize
    bbox = draw.textbbox((0, 0), storage_text, font=font_small)
    text_w = bbox[2] - bbox[0]
    draw.text((device.width - text_w, 0), storage_text, font=font_small, fill=255)

    # Timer (center)
    draw.text((10, 25), timer_text, font=font_big, fill=255)

    # Send to display
    device.display(img)