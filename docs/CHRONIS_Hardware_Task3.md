#### **C H R O N I S  ·  H A R D W A R E   T R A C K** 

# **Chronis – Hardware Task #3** 

_The Remote-Completion Sprint — Closing Every Simulation-Only Gap Before Physical Hardware Arrives_ 

Prepared for the Hardware Team · 6 interns, working in 3 pairs · Duration: 4 working days, plus a Day 5 all-team integration day 

Follows directly from Hardware Task #1 (firmware simulation) and Hardware Task #2 (hardening & electrical blueprint) 

#### **A Note Before You Start** 

Tasks 1 and 2 built the core of the system and proved it survives abuse and attack in simulation. But cross-checking both sprints against the full CHRONIS specification turned up real, specific gaps: two entire firmware modules that were never built (the OLED display and the LED controller), a time-sync module that was skipped, and a set of behaviors inside already-built daemons that were simplified during the first two sprints and never brought back up to the full spec. 

The goal of this sprint is narrow and specific: close every single one of those gaps that can honestly be closed without a physical board in hand. Not "most of them" — all of them. By the end of Day 5, there should be exactly one list left in this project: the things that genuinely require a real Radxa Zero 3W to test. Everything else should be built, tested, and passing against the mock hardware layer. 

One honest calibration, same as the last two sprints: "everything remote-doable is done" is a real, achievable target for this sprint — but it is not the same claim as "the firmware is finished." A few items below are audits and corrections of existing modules, not new builds; treat a passing audit as just as valuable a deliverable as a new module, since finding a gap between what's built and what's spec'd is exactly what this sprint exists to do. 

### **What Carries Over From Tasks 1 and 2** 

The same Four Rules from Task 1 still govern every line of code written this sprint: nothing is written to storage without going through encryption first; the permanent record is append-only and can never be edited; missing sensor data is always flagged as missing, never faked as zero; and no daemon reaches directly into another daemon's private data without a defined interface. The mock hardware layer, the synthetic trace generator, the pin-map file from Task 2, and every daemon built so far are the foundation for everything below — this sprint extends and audits that work, it does not replace it. 

### **Team Structure** 

|**Team**<br>Team A|**Focus**<br>Perception & Capture<br>Hardening|**Headline Deliverable**<br>Every existing sensor daemon (CSE, audio, camera, IMU)<br>brought fully up to spec, including behaviors that were simplified<br>in Tasks 1–2.|
|---|---|---|
|Team B|Output & Timing Modules|Two entirely new firmware modules built from zero — LED<br>Controller and OLED Display Manager — plus NTP/RTC time<br>sync.|



Chronis – Hardware Task #3 

Page 1 

|Team C|Crypto Hardening, Data|Encryption pipeline brought to full spec, tamper-evident record|
|---|---|---|
||Integrity & Security Docs|chain, and every outstanding security document written.|



The Day 4 Gate, restated for this sprint: every remote-doable gap identified against the full CHRONIS specification is either closed or explicitly and honestly logged as hardware-dependent — and the full stack, old and new modules together, survives one more extended simulated run with zero crashes and zero Rule violations. 

Chronis – Hardware Task #3 

Page 2 

## **Team A — Perception & Capture Hardening** 

Goal: close the gap between what Tasks 1 and 2 actually built for the four core sensor daemons (CSE, audio, camera, IMU) and what the full specification requires. Several behaviors were simplified in the first sprint to hit the deadline — this team's job is to find every one of those simplifications and bring the code up to the real spec. 

#### **Day 1 — CSE Graceful-Degradation Matrix** 

- Build the four specific sensor-loss fallback behaviors the salience engine is supposed to have: PPG unavailable → reweight to voice + motion, salience ceiling drops to L4; IMU unavailable → compute salience from voice + PPG only; both IMU and PPG unavailable → voice-only salience, camera capped at L3 (4fps max); audio capture failure → visual-only salience, camera capped at L2 continuous, cannot exceed L3. 

- Test each fallback individually against a synthetic trace with the relevant sensor deliberately killed mid-session. 

- Test the compound-failure case: two or more sensors going down at the same time. Confirm the salience engine degrades to the correct lower ceiling and never crashes or freezes. 

- Confirm the recovery path: when a lost sensor comes back, salience re-integrates it rather than staying stuck in the degraded ceiling. 

**_Deliverable: degradation-matrix-report.md, plus a passing test suite covering all four single-sensor-loss fallbacks and at least one compound-failure case._** 

#### **Day 2 — Audio Daemon: Retroactive Buffer + Exact Codec Tiers** 

- Implement the always-on 120-second rolling ring buffer for audio, separate from what's currently stored. 

- On any transition into L3 or higher, retroactively flush the preceding 120 seconds from the ring buffer into permanent storage, tagged with a retroactive-write flag and its exact duration. This has never been built — the current daemon only stores audio going forward from the transition moment. 

•  Implement the exact six-tier codec/bitrate table: L0 = 8kHz mono, ring-buffer only, never written; L1 = 8kHz stereo, OPUS 24kbps; L2 = 16kHz stereo, OPUS 24kbps; L3 = 16kHz, OPUS 32kbps; L4 = 16kHz dual-boosted channels, OPUS 64kbps; L5 = 48kHz/24-bit, lossless FLAC. 

- Write a test that steps through all six levels in sequence and confirms the codec/bitrate switch happens exactly at the transition boundary, with no gap in coverage and no double-encoding of the same audio. 

**_Deliverable: Updated audio daemon passing a test suite that proves both the retroactive-buffer behavior and the exact per-level codec selection._** 

#### **Day 3 — Camera Daemon: On-Device Face Detection + Metadata Audit** 

- Implement lightweight on-device face detection (a standard Haar-cascade classifier is sufficient) against synthetic test frames. Output must be region-of-interest coordinates only. 

- Write an explicit, deliberate test proving no identity data, face embedding, or cropped face image ever leaves this module — only bounding-box coordinates in metadata. This is a privacy-critical guarantee, so the test should try to make the module leak more than coordinates and confirm it can't. 

- Audit the full frame metadata schema against the ten required fields: timestamp_ntp, salience_level, cse_inputs, imu_orientation, imu_motion_state, ppg_bpm, ppg_sqi, ambient_light, kill_switch_active, temperature. Fill in whichever fields are currently missing from Task 1's implementation. 

- Confirm L5 capture writes rolling 30-second encrypted chunks rather than one large session file (limits how much is lost if a single chunk is corrupted). Fix this if the current implementation uses session-length files. 

**_Deliverable: Face-detection module with a passing non-identity-leak test, plus a corrected frame metadata schema matching all ten required fields._** 

#### **Day 4 — IMU Daemon: IPC Schema, CUSUM, Posture & Sleep Cross-Check** 

Chronis – Hardware Task #3 

Page 3 

•  Implement and test the exact IPC JSON payload broadcast every 100ms over the Unix domain socket: motion_state, orientation_quaternion, gesture_energy, worn_confidence, sleep_probability, posture_estimate, double_tap_event, timestamp_ms. If the current broadcast is missing fields or uses different names, correct it — this is the contract every other daemon depends on. 

- Formalize CUSUM change-point detection as its own tested function rather than folded into a general "motion shift" check. Feed it a synthetic step-change trace and test both detection latency and that the cumulative sum resets correctly after a detected change. 

- Rebuild posture classification as the specified three-tier pitch-angle threshold: pitch above 70° = upright, 20–70° 

- = slouched, below 20° = reclined. Test all three bands plus the two boundary values. 

•  Cross-check sleep detection against PPG variance, not IMU stillness alone. Write a test with a trace where the person is physically still but PPG shows an awake heart-rate pattern, and confirm this does NOT get flagged as asleep. 

**_Deliverable: IMU daemon test suite covering the exact IPC schema, standalone CUSUM detection, three-tier posture classification, and PPG-cross-checked sleep detection — all passing._** 

_What this team needs from us: A laptop each, GitHub access, OpenCV available for the Haar-cascade work. No new tools beyond Tasks 1 and 2._ 

Chronis – Hardware Task #3 

Page 4 

## **Team B — Output & Timing Modules** 

Goal: build the two firmware modules that were never started in Tasks 1 or 2, plus the time-sync module that was also skipped. All three are self-contained, well-specified state machines — genuinely new code, not an audit of existing code — and all three are fully testable against a mock display buffer, mock LED driver, and mock clock source with no physical hardware required. 

#### **Day 1 — LED Controller: Full State Machine** 

•  Build the LED state machine against a mock LED driver (12 front-arc LEDs + 3 separately addressable back zones). Implement all twelve automatic states: charging fill animation, sync chase, low-battery pulse, new-insight flash, not-worn breathing amber (back zones), kill-switch confirmation flash, tamper alert pulse, BLE pairing chase, mode-change confirmation flash, plus the CSE-level-dependent capture-active indicator (visible dim dot at L4–L5, no LED at all at L3 and below). 

•  Implement the suppression rule exactly: the user can disable every automatic state except two. Write a test that deliberately tries to suppress the tamper alert and the kill-switch confirmation flash and confirms both requests are rejected. 

- Implement the sleep schedule: auto-dim starting 10pm, full off at 11pm, user-adjustable, overridden (LEDs active) whenever the device is charging. 

**_Deliverable: LED controller passing a test for every one of the twelve states, plus the unsuppressible-alert test._** 

#### **Day 2 — OLED Display Manager: Priority Stack** 

•  Build the display manager against a mock display buffer implementing the eight-level priority stack, highest real-world priority first in testing even though it's last in the spec's enumerated list: tamper alert (full-screen warning), BLE pairing QR (first setup only), camera-killed icon (persists until slider reset), charging fill animation, low-battery icon, insight notification (60-character limit, 10-second auto-dismiss, tap-to-expand), capture-active indicator (minimal waveform, non-distracting), idle face (clock, battery %, sync dot, mode indicator, CSE level). 

•  Implement always-on ambient mode: 5 cd/m² brightness, a status dot that cycles battery/sync/capture state every 5 seconds. 

- Implement tap-to-wake: a simulated IMU single-tap event brings up the full display for 15 seconds, then returns to ambient. 

•  Implement the firmware-drawn privacy pixel and write a test proving it cannot be disabled through any software code path — app, user setting, or custom watch face — while the camera is active. 

**_Deliverable: OLED display manager passing tests for all eight priority states plus the unremovable-privacy-pixel proof._** 

#### **Day 3 — Voice-Gated Wake/Sleep + NTP Time Sync** 

•  Build a simple on-device voice-enrollment stub: store a fingerprint/embedding at setup time from a mock enrolled-voice sample, then implement the wake/sleep trigger against it. Test with a mock "enrolled voice" sample and a mock "other voice" sample, and confirm only the enrolled one triggers the display. 

•  Build the NTP Time Sync daemon: sync-on-WiFi-connect logic, then the exact three-tier drift correction — drift under 100ms gets a gradual slew correction with no disruption to ongoing timestamps; drift 100ms to 1 second gets a stepped correction, logged, with retrospective adjustment of recent sensor records; drift over 1 second gets a stepped correction plus an alert pushed to the phone. 

- Test all three drift tiers against a mock time source that reports controlled drift amounts, plus the boundary values (exactly 100ms, exactly 1s). 

- Build the DS3231 RTC fallback path for boot-without-WiFi, and the persistent drift log file. 

Chronis – Hardware Task #3 

Page 5 

**_Deliverable: Voice-gated wake/sleep test suite, plus an NTP daemon test suite covering all three drift tiers, both boundaries, and the RTC fallback path._** 

#### **Day 4 — Consolidation + Cross-Module Wiring Prep** 

•  Wire LED, OLED, and NTP into the existing mock HAL alongside every daemon from Tasks 1 and 2. Confirm none of the three new modules interfere with existing daemon timing — specifically, that LED/OLED updates never block the CSE's 500ms tick. 

•  Run each new module against all four synthetic scenario traces from Task 1 Day 1 (idle/dormant, ambient alone, active conversation, multi-party high-energy) and confirm correct behavior in every scenario — for example, the OLED shows the correct capture-active waveform at the correct CSE level in each trace, and the LED shows the correct not-worn amber breathing during the idle/dormant trace. 

**_Deliverable: LED, OLED, and NTP modules fully integrated into the mock stack, each independently verified against the existing scenario trace library._** 

_What this team needs from us: A laptop each, GitHub access. No new tools required — a mock display buffer and mock LED driver can both be built as simple in-memory data structures._ 

Chronis – Hardware Task #3 

Page 6 

## **Team C — Crypto Hardening, Data Integrity & Security Docs** 

Goal: bring the encryption and storage layers up to the exact spec (not just "an" encryption scheme, but the specific multi-key, multi-step one), close the one explicitly-flagged open decision in the whole project (the KDF choice), and write the security documents that were scoped in Week 1 planning but may never have actually been written. 

#### **Day 1 — Encryption Daemon: 7-Step Pipeline Audit + Dual-Key Wrap** 

•  Line-by-line audit Task 1's encryption daemon against the exact required pipeline: (1) raw sensor data arrives RAM-only, never touches disk raw; (2) compress in RAM by data type; (3) AES-256-GCM with the Data Session Key, random 96-bit nonce generated per file; (4) wrap an outer layer with the User Public Key; (5) write to the exact /vault/YYYY-MM-DD/[type]/[uuid].enc path; (6) SHA-256 checksum the encrypted file; (7) store the checksum alongside it. 

- Fix whichever step is missing. The most likely gap: Task 1 built single-layer DSK encryption without the outer UPK wrap — if so, add the second layer. 

- Write a test proving the two-layer structure is real, not just declared: knowing only the DSK should NOT be enough to fully recover plaintext; the UPK-wrapped outer layer must also be removed. 

**_Deliverable: Encryption daemon updated to the full 7-step spec, with a passing test proving the DSK+UPK dual-layer structure is enforced, not cosmetic._** 

#### **Day 2 — KDF Decision + Server Transport Key Forward-Secrecy Test** 

- Research and benchmark PBKDF2 vs. Argon2 specifically for this use case: a secure-element-backed key derivation running on a low-power ARM target. This closes an item that has been explicitly left open since Week 1 planning — write a short decision document with the reasoning, not just a preference. 

- Implement the Server Transport Key as session-ephemeral ECDH P-256, generated fresh per upload session. 

- Write a perfect-forward-secrecy test: simulate a compromised long-term key after the fact and confirm previously-recorded session transcripts still cannot be decrypted with it. 

**_Deliverable: KDF-decision.md with a clear recommendation and benchmark-backed reasoning, plus a passing forward-secrecy test for the transport key._** 

#### **Day 3 — Storage: Tamper-Evident Manifest Chain** 

- Implement the daily manifest.sha: an HMAC-SHA256 signature over each day's full file manifest, signed with a key derived from the Device Identity Key. This makes the canonical record tamper- _evident_ , not just append-only — a real gap, since Task 1 built append-only enforcement but not this signature chain. 

- Write a test that tampers with a single file's checksum entry after the manifest is signed, and confirms the signature check catches the tampering. 

•  Audit the storage manager's tiered thresholds against the exact spec: 80% full → pause captures, alert the phone, wait 24 hours for a sync opportunity; 95% full with no confirmed uploads → urgent alert, "connect to WiFi immediately" state, throttle capture to L1/L2 as a last resort. Fix any threshold in Task 1's implementation that doesn't match exactly. 

**_Deliverable: Tamper-evident manifest chain with a passing tamper-detection test, plus a corrected storage-threshold implementation matching the exact two-tier policy._** 

#### **Day 4 — OTA Gating + Security Documentation** 

- Tighten the OTA update apply-window logic beyond "never mid-session": never while CSE is at L3 or higher, never while syncing, never while charging with CSE above L0. Write a test for each of the three blocking conditions individually. 

Chronis – Hardware Task #3 

Page 7 

•  Write THREAT_MODEL.md covering the four named adversaries (network attacker intercepting traffic, malicious backend operator, device theft, a reverse engineer with physical access) and the specific protection mapped to each. Include an honestly-worded note on the one open risk that was explicitly deferred in early planning: physical key extraction from the ATECC608B is plausible given lab equipment and sustained physical access; rate-limiting and tamper detection are partial mitigations, not a closed problem. 

- Manually audit at least 20 of the crash logs already generated by Task 2's fuzzing runs and confirm zero user data appears in any of them — daemon state only, as required. Log the findings, good or bad. 

- Draft the responsible-disclosure / bug-bounty policy text intended for chronis.in/security: submission process, 48-hour acknowledgment commitment, 90-day remediation window before public disclosure. 

**_Deliverable: OTA gating test suite (three conditions, all passing), THREAT_MODEL.md, a written crash-log audit with findings, and the disclosure policy draft._** 

_What this team needs from us: A laptop each, GitHub access. No new tools required beyond Tasks 1 and 2._ 

Chronis – Hardware Task #3 

Page 8 

**Day 5 — All-Team Integration + Final Hardware-Only Gap List** 

Why this day exists: this is the day the project either can or cannot honestly say "nothing remote-doable is left." Everything built across Teams A, B, and C this week gets wired into the same mock stack as Tasks 1 and 2, run together, and then checked off, module by module, against the full specification. 

•  Wire the new modules (LED, OLED, NTP) and the hardened modules (CSE degradation matrix, audio retroactive buffer, camera face detection, IMU sub-tasks, dual-layer encryption, tamper-evident manifest, tightened OTA gating) into the full stack alongside everything from Tasks 1 and 2. 

•  Run one extended simulated session exercising all four scenario traces plus deliberate compound sensor failures (two or more sensors down at once), confirming zero crashes and zero Rule violations across the now-complete stack. 

•  As a full team, go through every one of the 17 firmware modules (plus the CSE) from the master specification, one at a time, and mark each as fully complete in simulation, partially complete with a named gap, or not applicable to this sprint. No module gets marked complete without someone besides its builder confirming the test suite actually passes. 

•  Produce the single most important artifact of this sprint: a definitive, explicit list of every remaining item that genuinely cannot be completed without a physical Radxa Zero 3W in hand — I²C bus scans and address confirmation, UART/JTAG physical disabling, real thermal and voltage measurement, execution of Task 2's bring-up checklist, and real-world battery validation against actual usage patterns. This is the handoff document for whoever manages procurement and scheduling from here. 

**_Deliverable: HARDWARE_READINESS_REPORT_TASK3.md (full-stack extended run results and the module-by-module checklist) plus HARDWARE_ONLY_REMAINING.md (the definitive, final list of hardware-dependent work)._** 

### **Final Sync Meeting — Agenda** 

- Team A presents the CSE degradation matrix, the audio retroactive-buffer work, camera face detection, and the IMU sub-task results (10 minutes) 

- Team B presents the LED controller, OLED display manager, and NTP time sync — three modules built from zero (10 minutes) 

•  Team C presents the encryption pipeline audit, the KDF decision, the tamper-evident manifest chain, and the security documents (10 minutes) 

•  The whole team presents the Day 5 integration results and walks through the module-by-module checklist together (10 minutes) 

•  The whole team reviews HARDWARE_ONLY_REMAINING.md line by line and confirms, honestly, that nothing on it could have been done remotely (remaining time) 

All presentations feed into one file: **HARDWARE_READINESS_REPORT_TASK3.md** , alongside the reports from Tasks 1 and 2, plus the standalone HARDWARE_ONLY_REMAINING.md handoff document. 

### **What This Sprint Is Not Claiming** 

•  "Nothing remote-doable is left" is a claim about this sprint's honest scope, not a guarantee that zero bugs remain in any module — simulation-only testing still can't catch real silicon timing quirks, real component interactions, or a datasheet inaccuracy, exactly as Tasks 1 and 2 already stated. 

•  The KDF decision and the threat-model documentation are planning artifacts based on current best understanding, not a completed external security audit — the pen-test scoped for later in the build (hardware attack surface, firmware reverse engineering) still needs to happen once real hardware and a stable firmware 

Chronis – Hardware Task #3 

Page 9 

image both exist. 

•  The face-detection and voice-enrollment work is tested against synthetic frames and mock audio samples, not real faces or real voices — real-world accuracy validation is a hardware-stage task, not a claim made here. 

•  None of this removes the need for real-hardware validation. It removes the remote-doable portion of the remaining work from the critical path once hardware does arrive. 

### **What We Need to Provide** 

- The same GitHub access, laptops, and shared reporting space already in place from Tasks 1 and 2 

- OpenCV (free) for Team A's face-detection work — no other new tools required 

- About 40–50 minutes of time on Day 5 for the final sync 

•  A decision-maker in the loop on Day 5 to receive HARDWARE_ONLY_REMAINING.md directly, since that document is the trigger for procurement/scheduling next steps 

### **Repository Structure — Where Everything Gets Saved** 

|`chronis-aic/`||
|---|---|
|III`hw-track-1-sensors/`|`(from Task 1)`|
|III`hw-track-2-security-boot/`|`(from Task 1)`|
|III`hw-track-3-connectivity/`|`(from Task 1)`|
|III`integration/`|`(from Task 1's Day 5)`|
|III`hardening-security/`|`(from Task 2, Team A)`|
|III`observability-fleet/`|`(from Task 2, Team B)`|
|III`hardware-design/`|`(from Task 2, Team C)`|
|III`red-team/`|`(from Task 2, Day 5)`|
|III`perception-capture-hardening/`|`Team A — CSE degradation matrix,`|
|I|`audio retroactive buffer, face detection,`|
|I|`IMU sub-tasks`|
|III`output-timing-modules/`|`Team B — LED controller, OLED display`|
|I|`manager, voice-gated wake/sleep, NTP sync`|
|III`crypto-integrity-security/`|`Team C — 7-step pipeline audit, KDF`|
|I|`decision, tamper-evident manifest,`|
|I|`OTA gating, THREAT_MODEL.md`|
|III`integration-task3/`|`Day 5 findings, full-stack run logs`|
|III`docs/`||
|III`HARDWARE_READINESS_REPORT.`|`md         (Task 1)`|
|III`COMPONENT_SPEC_LIST.md`|`(Task 1)`|
|III`HARDWARE_READINESS_REPORT_`|`TASK2.md   (Task 2)`|
|III`HARDWARE_READINESS_REPORT_`|`TASK3.md   (Task 3)`|
|III`HARDWARE_ONLY_REMAINING.md`|`(Task 3 — the final handoff list)`|



**_Final reminder, same as Tasks 1 and 2:_** _if any task in this document seems to require a real physical chip to complete, stop and re-read the relevant section — it almost certainly doesn't. Everything here is built and verified using published specifications, synthetic data, and free tools, with no physical hardware required. The one exception is the final list this sprint produces on Day 5 — and that list existing, named and explicit, is itself the point of doing this sprint._ 

Chronis – Hardware Task #3 

Page 10 

