# Enclosure First-Pass Specification
## Chronis — HW-Track-2 Day 3 Deliverable

**STATUS: UNVERIFIED PLANNING DOCUMENT — datasheet-derived only. No physical parts exist yet.**
All dimensions are from public datasheets. Actual fit, heat behavior, and wearability must be
validated when hardware arrives. Treat this as a pre-order bill-of-materials layout, not a
finished mechanical design.

---

## Component Physical Dimensions (from public datasheets)

| Component | Part | PCB/Module Size (mm) | Key Depth/Height | Source |
|---|---|---|---|---|
| Main compute | Radxa Zero 3W | 65 × 37 mm | ~5 mm (board + components) | Radxa HW Design v1.2 |
| Camera sensor | IMX219 module (typical) | 25 × 24 mm | ~6 mm (w/ lens) | Sony IMX219 Product Brief |
| IMU | ICM-42688-P | 3 × 3 mm (QFN) | 0.9 mm | TDK DS Rev1.0 |
| HR/PPG sensor | MAX30102 | 5.6 × 3.3 mm | 1.7 mm | Maxim DS Rev3 |
| Crypto chip | ATECC608B | 3 × 2 mm (UDFN) | 0.6 mm | Microchip DS |
| RTC backup | DS3231SN | 16 × 9 mm (SO package) | 2.2 mm | Maxim DS |
| Battery (est.) | 3000 mAh LiPo (generic) | 60 × 40 mm | 5 mm | Generic LiPo spec |

---

## First-Pass Enclosure Envelope

```
Top view (approximate, not to scale):

┌─────────────────────────────────────────────────┐
│  [Camera opening]  [Status LED window]           │ ← 68 mm wide
│  ●                  ○                            │
│                                                  │
│  ┌─────────────────────────────────────────┐    │
│  │         Radxa Zero 3W (65×37)           │    │
│  │                               [ATECC]   │    │
│  │  [ICM-42688]   [MAX30102]    [DS3231]   │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│  ┌─────────────────────────────────────────┐    │
│  │         Battery (60×40 mm)              │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│              [USB-C Charging Port] →             │ ← right side
└─────────────────────────────────────────────────┘
         ↑ 90 mm tall
```

**Target envelope:** 90 mm × 68 mm × 18 mm
- Width (68 mm): Radxa board (37 mm) + lateral clearance + side walls
- Height (90 mm): Board (65 mm) + battery stacked (with 5 mm gap) + top/bottom walls
- Depth (18 mm): Battery (5 mm) + board (5 mm) + camera lens protrusion (6 mm) + top plate

---

## Wearability Notes

- **Weight estimate:** PCB ~15 g + battery ~50 g + enclosure shell ~20 g = ~85 g total
  (unverified — no physical parts). Wrist-wear viability requires validation with a prototype.
- **Weight distribution:** Battery should sit below the compute board (toward wrist) for center-of-mass stability.
- **Camera/mic placement:** Camera on top face, mic opening on side (away from wrist contact).
- **Charging port:** USB-C on bottom edge; right side is viable alternative pending ergonomic testing.
- **Strap lugs:** Standard 22 mm lug spacing assumed; exact attachment points TBD after shell prototype.

---

## Thermal Assessment (cross-check with power_thermal_estimate.py)

From the power/thermal estimate at L5 (maximum capture intensity):
- Estimated total power draw: ~5.4 W (see power_thermal_estimate.py output)
- This exceeds the 3 W thermal warning threshold defined in power_thermal_estimate.py
- At L3–L4 (typical sustained operation), draw is ~4–5 W

**Thermal flag:** Sustained L4–L5 operation in a sealed plastic enclosure will likely require
one or more of:
- Thermally conductive enclosure material (e.g., aluminum shell, not ABS)
- Thermal pad between SoC and enclosure wall
- Duty-cycling forced by the power management daemon (which already caps at L3 in Critical state)

**Action required before hardware:** Thermal simulation or early prototype measurement before
committing to enclosure material and wall thickness.

---

## Gaps — Cannot Be Validated Without Hardware

1. Actual PCB layout (component placement may differ from the datasheet footprints used here).
2. Camera lens protrusion depth (varies by module supplier).
3. Real thermal behavior under sustained load in an enclosed space.
4. Physical wearability, comfort, and strap attachment.
5. I2C/SPI bus address conflicts between ICM-42688-P, MAX30102, ATECC608B, DS3231 — must be checked once all are on the same bus.
6. USB-C port clearance with battery edge connector.
7. Actual weight once real components are sourced.
