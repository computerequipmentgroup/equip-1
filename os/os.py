import time
import shutil
import subprocess
from periphery import GPIO
from luma.core.interface.serial import i2c
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont


class RecorderState:
    def __init__(self):
        self.mode = "idle"         # "idle" or "recording"
        self.start_time = None
        self.process = None        # will hold dvgrab Popen

    def toggle(self):
        if self.mode == "idle":
            # enter recording
            self.mode = "recording"
            self.start_time = time.time()
            #self.process = subprocess.Popen(
            #    ["dvgrab", "--format", "dv2", "capture-"],
            #    stdout=subprocess.PIPE
            #)
        else:
            # stop recording
            self.mode = "idle"
            if self.process:
                self.process.terminate()
                self.process.wait()
                self.process = None
            self.start_time = None

    @property
    def elapsed_text(self):
        if self.mode != "recording" or self.start_time is None:
            return "00:00"
        elapsed = time.time() - self.start_time
        mm, ss = divmod(int(elapsed), 60)
        return f"{mm:02}:{ss:02}"

    @property
    def storage_text(self):
        total, used, free = shutil.disk_usage("/")
        free_gb = free // (1024**3)
        return f"{free_gb}G"


# === Setup ===
serial = i2c(port=0, address=0x3C)
device = sh1106(serial)

font_small = ImageFont.load_default()
font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)

state = RecorderState()

# Setup button on GPIO4_C4 = gpiochip4, line 20
button = GPIO("/dev/gpiochip4", 20, "in")

# === Main loop ===
try:
    while True:
        # Check button
        if button.read() == 0:  # active low
            state.toggle()
            time.sleep(0.3)  # debounce

        # Build frame
        img = Image.new("1", device.size)
        draw = ImageDraw.Draw(img)

        # REC label
        if state.mode == "recording":
            draw.text((0, 0), "REC", font=font_small, fill=255)

        # Storage top-right
        storage = state.storage_text
        bbox = draw.textbbox((0, 0), storage, font=font_small)
        text_w = bbox[2] - bbox[0]
        draw.text((device.width - text_w, 0), storage, font=font_small, fill=255)

        # Timer center
        draw.text((10, 25), state.elapsed_text, font=font_big, fill=255)

        device.display(img)
        time.sleep(0.1)

except KeyboardInterrupt:
    pass
finally:
    button.close()
