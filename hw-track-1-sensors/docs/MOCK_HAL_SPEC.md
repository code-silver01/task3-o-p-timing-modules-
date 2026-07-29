# Mock Hardware Abstraction Layer — Interface Specification

**Status:** Simulation-only (no real hardware)  
**Sprint:** Chronis Hardware Track 1, Day 1  
**Authors:** Arpit, Aditya

---

## Overview

The Mock HAL provides a software layer that behaves identically to the real sensor chips, minus the physical chip. All daemon code is written against this interface. When real hardware arrives, only this layer gets swapped — everything above it stays unchanged.

## Sensor Interfaces

### MockIMU (ICM-42688-P)
| Method | Returns | Real chip equivalent |
|--------|---------|---------------------|
| `i2c_read()` | `IMUReading` | `i2c_read(0x68, 0x3B, 14)` |
| `set_values(accel, gyro)` | — | N/A (test control) |
| `set_available(bool, reason)` | — | N/A (test control) |
| `set_fault(bool)` | — | N/A (test control) |
| `set_noise(float)` | — | N/A (test control) |

**IMUReading fields:** `timestamp, status, accel_x/y/z (g), gyro_x/y/z (deg/s)`  
**Computed:** `accel_magnitude` — returns None if unavailable

### MockPPG (MAX30102)
| Method | Returns | Real chip equivalent |
|--------|---------|---------------------|
| `i2c_read()` | `PPGReading` | `i2c_read(0x57, ...)` |
| `set_values(hr, spo2, quality)` | — | N/A |
| `set_worn(bool)` | — | N/A |
| `set_available(bool, reason)` | — | N/A |

**PPGReading fields:** `timestamp, status, heart_rate_bpm, spo2_percent, ir_value, red_value, signal_quality (0-1)`  
**Special state:** `NOT_WORN` — distinct from UNAVAILABLE, means skin contact lost

### MockCamera (IMX219)
| Method | Returns | Real chip equivalent |
|--------|---------|---------------------|
| `capture_frame(compression)` | `CameraReading` | CSI frame capture |
| `set_face(detected, expression)` | — | N/A |
| `set_available(bool, reason)` | — | N/A |

**CameraReading fields:** `timestamp, status, frame_id, width, height, compression_level, face_detected, face_expression`

### MockMicrophone
| Method | Returns | Real chip equivalent |
|--------|---------|---------------------|
| `read_chunk()` | `AudioReading` | I2S/PDM audio read |
| `set_values(energy, speech, speakers)` | — | N/A |
| `set_sample_rate(int)` | — | N/A |
| `set_available(bool, reason)` | — | N/A |

**AudioReading fields:** `timestamp, status, energy_rms (0-1), peak_db, sample_rate_hz, speech_detected, num_speakers`

### MockGPIO
| Method | Returns |
|--------|---------|
| `gpio_read(pin_id)` | `GPIOReading` |
| `set_pin(pin_id, bool)` | — |

## Data Types

### SensorStatus (enum)
`OK` | `UNAVAILABLE` | `NOT_WORN` | `CALIBRATING` | `FAULT`

### UnavailableReason (enum)
`SENSOR_NOT_FOUND` | `I2C_TIMEOUT` | `DEVICE_NOT_WORN` | `SELF_TEST_FAILED` | `POWER_SAVING` | `HARDWARE_FAULT`

### Rule Enforcement Types
- **EncryptedPayload** — the ONLY type MockStorage.write() accepts (Rule 1)
- **RawPayload** — explicitly rejected by MockStorage.write() (Rule 1)

## Rule 3 Guarantee

Every sensor's read method, when the sensor is unavailable, returns:
- `status` = `UNAVAILABLE` or `NOT_WORN` or `FAULT`
- `unavailable_reason` = specific enum explaining why
- All value fields = `None` (never 0, never default)

Downstream code MUST check `reading.is_valid` before using values.

## MockHAL (unified interface)

```python
hal = MockHAL()
hal.read_imu()        # -> IMUReading
hal.read_ppg()        # -> PPGReading
hal.capture_frame()   # -> CameraReading
hal.read_audio()      # -> AudioReading
hal.read_gpio(pin)    # -> GPIOReading
hal.set_all_available(False)  # kill all sensors at once
```
