"""
Chronis Task 3, Team B, Day 2 — Mock Display Buffer.

Same idea as Day 1's mock LED driver: this is dumb pretend hardware.
It remembers three things — what's currently drawn, how bright the
screen is, and whether the privacy pixel is on — and does no thinking
of its own. All decisions live in oled_controller.py.
"""


class MockDisplayBuffer:
    def __init__(self):
        self.content = {"state": None}   # whatever's currently on screen
        self.brightness_cdm2 = 0.0       # cd/m² = the unit the spec uses
        self.privacy_pixel_on = False

    def set_frame(self, content: dict, brightness_cdm2: float, privacy_pixel_on: bool):
        self.content = dict(content)
        self.brightness_cdm2 = brightness_cdm2
        self.privacy_pixel_on = privacy_pixel_on

    def snapshot(self):
        return {
            "content": dict(self.content),
            "brightness_cdm2": self.brightness_cdm2,
            "privacy_pixel_on": self.privacy_pixel_on,
        }