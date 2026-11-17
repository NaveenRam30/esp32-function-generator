/*
 * esp32_function_generator.ino
 *
 * Firmware for the "ESP32 Function Generator" PC GUI (see function_generator/).
 *
 *   - Classic ESP32 (DAC1 on GPIO25), Arduino-ESP32 core 2.x or 3.x
 *   - Direct-digital-synthesis (DDS): a 32-bit phase accumulator steps through
 *     a 256-point wavetable, driven by a hardware timer at FS_HZ.
 *   - The 8-bit DAC is written from the timer ISR with a single register
 *     write, so the sample rate is steady and independent of serial traffic.
 *   - Serial protocol: ASCII lines at 115200 baud, see the README / protocol.py.
 *
 * Signal chain:  wavetable -> DAC1 (GPIO25) -> [your filter / output stage]
 * Voltage mapping is defined by OUT_MIN_V / OUT_MAX_V below. Change them if an
 * external stage rescales the DAC (for example -5 V ... +5 V).
 */
#include <Arduino.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "soc/rtc_io_reg.h"
#include "soc/sens_reg.h"

#if !CONFIG_IDF_TARGET_ESP32
#error "This sketch needs a classic ESP32 (built-in DAC on GPIO25/26 with RTC_IO registers)."
#endif

// ===========================================================================
// Configuration
// ===========================================================================
#define FW_VERSION "1.0.0"

static const uint32_t SERIAL_BAUD = 115200;
static const uint8_t  DAC_PIN     = 25;         // DAC1
static const uint8_t  LED_PIN     = 2;          // lit while output is RUNNING

static const uint32_t FS_HZ       = 200000;     // DDS sample rate (must divide 1 000 000)
static const int      TABLE_SIZE  = 256;        // fixed: index = top 8 bits of phase
static_assert(1000000UL % FS_HZ == 0, "FS_HZ must divide 1 MHz (timer tick)");

// Voltage that DAC code 0 / 255 produces at the OUTPUT (after any external
// stage). Direct ESP32 output: about 0 ... 3.3 V.
static const double OUT_MIN_V = 0.0;
static const double OUT_MAX_V = 3.3;

// Parameter limits (must agree with, or be wider than, the GUI's config.py)
static const double FREQ_MIN_HZ  = 1.0;
static const double FREQ_MAX_HZ  = 50000.0;
static const double VPP_MAX      = 5.0;
static const double OFFSET_MIN_V = -5.0;
static const double OFFSET_MAX_V = 5.0;
static const double DUTY_MIN     = 1.0;
static const double DUTY_MAX     = 99.0;
static const double SWEEP_T_MIN  = 0.1;
static const double SWEEP_T_MAX  = 3600.0;

// ===========================================================================
// Types
// ===========================================================================
enum Wave : uint8_t { W_SINE, W_SQUARE, W_TRIANGLE, W_SAWTOOTH, W_PULSE };
static const char* const WAVE_NAMES[] = { "SINE", "SQUARE", "TRIANGLE", "SAWTOOTH", "PULSE" };
static const int WAVE_COUNT = 5;

enum RunState : uint8_t { ST_STOPPED, ST_RUNNING, ST_PAUSED };
static const char* const STATE_NAMES[] = { "STOPPED", "RUNNING", "PAUSED" };

enum Err : uint8_t {
  E_NONE, E_INVALID_COMMAND, E_INVALID_PARAM, E_FREQ_RANGE, E_VPP_RANGE,
  E_OFFSET_RANGE, E_PHASE_RANGE, E_DUTY_RANGE, E_NOT_RUNNING, E_NOT_PAUSED
};
static const char* const ERR_NAMES[] = {
  "NONE", "INVALID_COMMAND", "INVALID_PARAM", "FREQ_RANGE", "VPP_RANGE",
  "OFFSET_RANGE", "PHASE_RANGE", "DUTY_RANGE", "NOT_RUNNING", "NOT_PAUSED"
};

struct Settings {
  Wave   wave;
  double freq, vpp, offset, phase, duty;
};

struct SweepCfg {
  double f1, f2, seconds;
  bool   logarithmic;
  bool   active;
  uint32_t elapsedMs;
};

// ===========================================================================
// State shared with the timer ISR
// ===========================================================================
static uint8_t g_tables[2][TABLE_SIZE];                 // double buffered wavetable
static volatile uint8_t*  g_table = g_tables[0];
static volatile uint32_t  g_acc = 0;                    // phase accumulator
static volatile uint32_t  g_inc = 0;                    // phase increment per sample
static volatile uint32_t  g_phaseOff = 0;               // phase offset (32-bit fraction of a cycle)
static volatile uint8_t   g_state = ST_STOPPED;
static volatile uint8_t   g_lastDac = 0;
static volatile uint32_t  g_isrCount = 0;

// ===========================================================================
// State used only by the main loop
// ===========================================================================
static Settings g_set;
static SweepCfg g_sweep;
static double   g_curFreq = 1000.0;                     // instantaneous frequency (sweep!)
static bool     g_clipped = false;                      // last table had to be clipped
static int      g_activeTable = 0;

static hw_timer_t* g_timer = nullptr;

// ===========================================================================
// DAC access
// ===========================================================================
// One register write, safe to call from the ISR. The channel is enabled once
// in setup() through dacWrite(), which also switches the cosine generator off.
static inline void IRAM_ATTR dacFast(uint8_t v) {
  SET_PERI_REG_BITS(RTC_IO_PAD_DAC1_REG, RTC_IO_PDAC1_DAC, v, RTC_IO_PDAC1_DAC_S);
}

// Timer interrupt: output one sample and advance the phase.
void IRAM_ATTR onTimer() {
  g_isrCount++;
  if (g_state != ST_RUNNING) return;                    // STOPPED: idle level, PAUSED: hold
  uint32_t a = g_acc;
  uint8_t code = g_table[(uint8_t)((a + g_phaseOff) >> 24)];
  dacFast(code);
  g_lastDac = code;
  g_acc = a + g_inc;
}

// ===========================================================================
// Waveform / voltage helpers
// ===========================================================================
static uint8_t voltsToCode(double v, bool& clipped) {
  double t = (v - OUT_MIN_V) / (OUT_MAX_V - OUT_MIN_V);
  if (t < -1e-9)     { t = 0.0; clipped = true; }
  else if (t > 1.0 + 1e-9) { t = 1.0; clipped = true; }
  else if (t < 0.0)  t = 0.0;
  else if (t > 1.0)  t = 1.0;
  return (uint8_t)lround(t * 255.0);
}

static uint8_t idleCode() {                             // output level while STOPPED (0 V if possible)
  bool dummy = false;
  return voltsToCode(0.0, dummy);
}

// Same shapes as the preview in the GUI (waveform.py). Returns true if any
// sample had to be clipped to the DAC range.
static bool buildTable(uint8_t* t, const Settings& s) {
  bool clipped = false;
  const double duty = s.duty / 100.0;
  for (int i = 0; i < TABLE_SIZE; i++) {
    double p = (double)i / TABLE_SIZE;                  // phase in cycles, 0 ... <1
    double shape;
    switch (s.wave) {
      case W_SINE:     shape = sin(2.0 * M_PI * p); break;
      case W_SQUARE:
      case W_PULSE:    shape = (p < duty) ? 1.0 : -1.0; break;
      case W_TRIANGLE: shape = 1.0 - 4.0 * fabs(fmod(p + 0.25, 1.0) - 0.5); break;
      default:         shape = 2.0 * fmod(p + 0.5, 1.0) - 1.0; break;   // sawtooth
    }
    t[i] = voltsToCode(s.offset + 0.5 * s.vpp * shape, clipped);
  }
  return clipped;
}

static uint32_t incFor(double freq) {
  return (uint32_t)(freq * 4294967296.0 / (double)FS_HZ + 0.5);
}

static void setFrequency(double f) {
  g_curFreq = f;
  g_inc = incFor(f);                                    // 32-bit store is atomic
}

// Rebuild the wavetable in the idle buffer and swap it in.
static void applySettings() {
  int next = 1 - g_activeTable;
  g_clipped = buildTable(g_tables[next], g_set);
  g_table = g_tables[next];
  g_activeTable = next;
  g_phaseOff = (uint32_t)(fmod(g_set.phase, 360.0) / 360.0 * 4294967296.0);
  if (!g_sweep.active) setFrequency(g_set.freq);
}

// ===========================================================================
// Output state
// ===========================================================================
static void startOutput() {
  g_acc = 0;
  g_state = ST_RUNNING;
  digitalWrite(LED_PIN, HIGH);
}

static void stopOutput() {
  g_state = ST_STOPPED;
  g_sweep.active = false;
  setFrequency(g_set.freq);
  uint8_t idle = idleCode();
  dacFast(idle);
  g_lastDac = idle;
  digitalWrite(LED_PIN, LOW);
}

static void resetDefaults() {
  g_set = { W_SINE, 1000.0, 2.0, 1.0, 0.0, 50.0 };
  g_sweep = { 100.0, 10000.0, 5.0, false, false, 0 };
  stopOutput();
  applySettings();
}

// ===========================================================================
// Replies
// ===========================================================================
static void reply(const char* text) { Serial.println(text); }
static void replyErr(Err e)         { Serial.print("ERROR,"); Serial.println(ERR_NAMES[e]); }

static void replyOkClip() { reply(g_clipped ? "OK,CLIPPED" : "OK"); }

static void sendStatus() {
  Serial.printf("STATUS,WAVE=%s,FREQ=%.3f,VPP=%.3f,OFFSET=%.3f,PHASE=%.2f,DUTY=%.2f,"
                "STATE=%s,FS=%lu,SAMPLES=%d,FW=%s,SWEEP=%s,CLIP=%d\n",
                WAVE_NAMES[g_set.wave], g_curFreq, g_set.vpp, g_set.offset,
                g_set.phase, g_set.duty, STATE_NAMES[g_state],
                (unsigned long)FS_HZ, TABLE_SIZE, FW_VERSION,
                g_sweep.active ? "ON" : "OFF", g_clipped ? 1 : 0);
}

// FREQ is CALCULATED from the phase increment and the actually measured
// timer rate (not from an external frequency counter). DAC is the last raw
// 8-bit code written.
static void sendMeas() {
  static uint32_t lastCount = 0, lastUs = 0;
  uint32_t count = g_isrCount, us = micros();
  uint32_t dn = count - lastCount, dt = us - lastUs;
  lastCount = count;
  lastUs = us;
  if (dt == 0) return;
  double fsMeas = (double)dn * 1e6 / (double)dt;
  double f = (double)g_inc * fsMeas / 4294967296.0;
  Serial.printf("MEAS,FREQ=%.2f,DAC=%u,FS=%.0f\n", f, (unsigned)g_lastDac, fsMeas);
}

// ===========================================================================
// Parameter parsing / validation
// ===========================================================================
static bool parseNum(const char* text, double& out) {
  if (!text || !*text) return false;
  char* end = nullptr;
  out = strtod(text, &end);
  return end != text && *end == '\0' && isfinite(out);
}

// Applies one KEY/VALUE to `s`. Nothing is changed unless the value is valid.
static Err setParam(Settings& s, const char* key, const char* val) {
  if (!strcmp(key, "WAVE")) {
    for (int i = 0; i < WAVE_COUNT; i++)
      if (!strcmp(val, WAVE_NAMES[i])) { s.wave = (Wave)i; return E_NONE; }
    return E_INVALID_PARAM;
  }
  double v;
  if (!parseNum(val, v)) return E_INVALID_PARAM;
  if (!strcmp(key, "FREQ")) {
    if (v < FREQ_MIN_HZ || v > FREQ_MAX_HZ) return E_FREQ_RANGE;
    s.freq = v;
  } else if (!strcmp(key, "VPP")) {
    if (v < 0.0 || v > VPP_MAX) return E_VPP_RANGE;
    s.vpp = v;
  } else if (!strcmp(key, "OFFSET")) {
    if (v < OFFSET_MIN_V || v > OFFSET_MAX_V) return E_OFFSET_RANGE;
    s.offset = v;
  } else if (!strcmp(key, "PHASE")) {
    if (v < 0.0 || v > 360.0) return E_PHASE_RANGE;
    s.phase = v;
  } else if (!strcmp(key, "DUTY")) {
    if (v < DUTY_MIN || v > DUTY_MAX) return E_DUTY_RANGE;
    s.duty = v;
  } else {
    return E_INVALID_PARAM;
  }
  return E_NONE;
}

// ===========================================================================
// Command handlers
// ===========================================================================
static void cmdConfig(char** tok, int n) {
  Settings tmp = g_set;                                 // all-or-nothing update
  for (int i = 1; i < n; i++) {
    char* eq = strchr(tok[i], '=');
    if (!eq) { replyErr(E_INVALID_PARAM); return; }
    *eq = '\0';
    Err e = setParam(tmp, tok[i], eq + 1);
    if (e != E_NONE) { replyErr(e); return; }
  }
  g_set = tmp;
  applySettings();
  replyOkClip();
}

static void cmdSet(char** tok, int n) {
  if (n < 3) { replyErr(E_INVALID_COMMAND); return; }
  Settings tmp = g_set;
  Err e = setParam(tmp, tok[1], tok[2]);
  if (e != E_NONE) { replyErr(e); return; }
  g_set = tmp;
  applySettings();
  replyOkClip();
}

static void cmdSweep(char** tok, int n) {
  if (n < 2) { replyErr(E_INVALID_COMMAND); return; }
  if (!strcmp(tok[1], "CONFIG")) {
    SweepCfg tmp = g_sweep;
    for (int i = 2; i < n; i++) {
      char* eq = strchr(tok[i], '=');
      if (!eq) { replyErr(E_INVALID_PARAM); return; }
      *eq = '\0';
      const char* key = tok[i];
      const char* val = eq + 1;
      double v;
      if (!strcmp(key, "MODE")) {
        if (!strcmp(val, "LOG"))      tmp.logarithmic = true;
        else if (!strcmp(val, "LIN")) tmp.logarithmic = false;
        else { replyErr(E_INVALID_PARAM); return; }
      } else if (!strcmp(key, "F1") || !strcmp(key, "F2")) {
        if (!parseNum(val, v)) { replyErr(E_INVALID_PARAM); return; }
        if (v < FREQ_MIN_HZ || v > FREQ_MAX_HZ) { replyErr(E_FREQ_RANGE); return; }
        if (key[1] == '1') tmp.f1 = v; else tmp.f2 = v;
      } else if (!strcmp(key, "T")) {
        if (!parseNum(val, v) || v < SWEEP_T_MIN || v > SWEEP_T_MAX) { replyErr(E_INVALID_PARAM); return; }
        tmp.seconds = v;
      } else {
        replyErr(E_INVALID_PARAM);
        return;
      }
    }
    tmp.active = g_sweep.active;
    tmp.elapsedMs = g_sweep.elapsedMs;
    g_sweep = tmp;
    reply("OK");
  } else if (!strcmp(tok[1], "START")) {
    g_sweep.elapsedMs = 0;
    g_sweep.active = true;
    setFrequency(g_sweep.f1);
    bool wasStopped = (g_state == ST_STOPPED);
    if (wasStopped) startOutput();                      // a sweep implies a running output
    reply("OK");
    if (wasStopped) reply("RUNNING");
  } else if (!strcmp(tok[1], "STOP")) {
    g_sweep.active = false;
    setFrequency(g_set.freq);
    reply("OK");
  } else {
    replyErr(E_INVALID_COMMAND);
  }
}

static void handleLine(char* line) {
  char* tok[12];
  int n = 0;
  char* p = line;
  while (n < 12) {                                      // split at commas in place
    tok[n++] = p;
    char* comma = strchr(p, ',');
    if (!comma) break;
    *comma = '\0';
    p = comma + 1;
  }
  const char* cmd = tok[0];

  if      (!strcmp(cmd, "CONFIG")) cmdConfig(tok, n);
  else if (!strcmp(cmd, "SET"))    cmdSet(tok, n);
  else if (!strcmp(cmd, "SWEEP"))  cmdSweep(tok, n);
  else if (!strcmp(cmd, "START")) { startOutput(); reply("RUNNING"); }
  else if (!strcmp(cmd, "STOP"))  { stopOutput();  reply("STOPPED"); }
  else if (!strcmp(cmd, "PAUSE")) {
    if (g_state != ST_RUNNING) replyErr(E_NOT_RUNNING);
    else { g_state = ST_PAUSED; reply("PAUSED"); }
  }
  else if (!strcmp(cmd, "RESUME")) {
    if (g_state != ST_PAUSED) replyErr(E_NOT_PAUSED);
    else { g_state = ST_RUNNING; reply("RUNNING"); }
  }
  else if (!strcmp(cmd, "RESET"))  { resetDefaults(); reply("READY"); }
  else if (!strcmp(cmd, "STATUS")) sendStatus();
  else replyErr(E_INVALID_COMMAND);
}

// ===========================================================================
// Serial line reader (non-blocking)
// ===========================================================================
static char   rxBuf[160];
static size_t rxLen = 0;
static bool   rxOverflow = false;

static void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (rxOverflow)      replyErr(E_INVALID_COMMAND);
      else if (rxLen > 0)  { rxBuf[rxLen] = '\0'; handleLine(rxBuf); }
      rxLen = 0;
      rxOverflow = false;
    } else if (c == '\r') {
      // ignore
    } else if (rxLen < sizeof(rxBuf) - 1) {
      rxBuf[rxLen++] = (char)toupper((unsigned char)c);  // protocol is case-insensitive
    } else {
      rxOverflow = true;
    }
  }
}

// ===========================================================================
// Frequency sweep (repeats until SWEEP,STOP)
// ===========================================================================
static void updateSweep(uint32_t dtMs) {
  g_sweep.elapsedMs += dtMs;
  uint32_t total = (uint32_t)(g_sweep.seconds * 1000.0);
  if (total == 0) total = 1;
  g_sweep.elapsedMs %= total;
  double x = (double)g_sweep.elapsedMs / (double)total;
  double f = g_sweep.logarithmic ? g_sweep.f1 * pow(g_sweep.f2 / g_sweep.f1, x)
                                 : g_sweep.f1 + (g_sweep.f2 - g_sweep.f1) * x;
  setFrequency(f);
}

// ===========================================================================
// Arduino entry points
// ===========================================================================
void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  dacWrite(DAC_PIN, idleCode());        // enables DAC1, disables the cosine generator
  resetDefaults();

#if ESP_ARDUINO_VERSION_MAJOR >= 3
  g_timer = timerBegin(1000000);                                    // 1 MHz tick
  timerAttachInterrupt(g_timer, &onTimer);
  timerAlarm(g_timer, 1000000UL / FS_HZ, true, 0);
#else
  g_timer = timerBegin(0, 80, true);                                // 80 MHz / 80 = 1 MHz tick
  timerAttachInterrupt(g_timer, &onTimer, true);
  timerAlarmWrite(g_timer, 1000000UL / FS_HZ, true);
  timerAlarmEnable(g_timer);
#endif

  reply("READY");
}

void loop() {
  static uint32_t lastTick = 0, lastMeas = 0;
  readSerial();

  uint32_t now = millis();
  if (now - lastTick >= 10) {
    uint32_t dt = now - lastTick;
    lastTick = now;
    if (g_state == ST_RUNNING && g_sweep.active) updateSweep(dt);
  }
  if (now - lastMeas >= 1000) {
    lastMeas = now;
    if (g_state == ST_RUNNING) sendMeas();
  }
}
