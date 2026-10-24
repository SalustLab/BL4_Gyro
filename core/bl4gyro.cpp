// bl4gyro.dll - runs inside Borderlands 4. A sensor thread reads the controller's motion through the game's
// own Steam Input (Steam only delivers it while the game window has focus) or, when Steam Input hands the game
// no controller, straight from the pad's HID through SDL; it turns it into calibrated controller
// rotation (gyro::Processor) and accumulates it. The BL4Gyro sdkmod drains it once per camera update through
// this C ABI (ctypes) and feeds it to AddYawInput/AddPitchInput on the game thread.
#include <windows.h>
#include <xinput.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <SDL3/SDL.h>

#include "gyro.hpp"
#include "steam_motion.hpp"

namespace {

std::mutex g_log_mutex;
FILE* g_log = nullptr;

void log(const char* fmt, ...)
{
    std::lock_guard lock(g_log_mutex);
    if (!g_log) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    std::fprintf(g_log, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list args;
    va_start(args, fmt);
    std::vfprintf(g_log, fmt, args);
    va_end(args);
    std::fputc('\n', g_log);
    std::fflush(g_log);
}

// Optional diagnosis trace (Debug trace option): every motion packet (P), every camera drain (T) and the sensor
// loop rate (L), so in-game behaviour can be analysed offline. Off by default.
std::mutex g_trace_mutex;
FILE* g_trace = nullptr;
std::wstring g_dir;

void trace(const char* fmt, ...)
{
    std::lock_guard lock(g_trace_mutex);
    if (!g_trace) return;
    va_list args;
    va_start(args, fmt);
    std::vfprintf(g_trace, fmt, args);
    va_end(args);
}

void set_trace(bool on)
{
    std::lock_guard lock(g_trace_mutex);
    if (on && !g_trace) {
        g_trace = _wfopen((g_dir + L"trace.csv").c_str(), L"w");
        if (g_trace) std::fprintf(g_trace, "kind,t,a,b,c,d,e,f,g,h,i,j\n");
    } else if (!on && g_trace) {
        std::fclose(g_trace);
        g_trace = nullptr;
    }
}

double now_s()
{
    static const double freq = [] {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        return static_cast<double>(f.QuadPart);
    }();
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    return static_cast<double>(c.QuadPart) / freq;
}

struct Config {
    gyro::Settings motion;
    gyro::Camera camera;
};

std::mutex g_cfg_mutex;
Config g_cfg;
std::atomic<bool> g_cfg_dirty{true};
gyro::RateHold g_hold;
std::atomic<bool> g_run{false};
std::atomic<double> g_calibrate{0};
std::thread g_thread;
std::mutex g_status_mutex;
std::string g_status = "stopped";
std::string g_replay_csv;

// Structured status for the panel (bl4gyro_info); the sensor thread writes it, the game thread reads it.
enum class Source { None, Steam, Hid, Replay, SteamUnavailable };
struct Info {
    Source source = Source::None;
    double packets_per_s = 0;
    double last_packet_s = -1; // now_s() of the last motion packet, -1 if none yet
    double calibration_progress = 0;
    gyro::Calibration calibration = gyro::Calibration::None;
    double calibration_deadline_s = 0; // calibration without data past this reports "no data"
    float offset[3] = {};             // gyro bias being subtracted (deg/s, SDL axes)
};
std::mutex g_info_mutex;
Info g_info;

template <class F> void update_info(F&& f)
{
    std::lock_guard lock(g_info_mutex);
    f(g_info);
}

// Calibration state for bl4gyro_info, and a log line whenever the result or the subtracted offset changes (a wrong
// offset turns into a steady camera drift, so it must be visible).
void publish_calibration(gyro::Processor& proc)
{
    static gyro::Calibration logged_result = gyro::Calibration::None;
    static float logged[3] = {};
    float offset[3];
    proc.calibration_offset(offset);
    const gyro::Calibration result = proc.calibration();
    update_info([&](Info& i) {
        i.calibration = result;
        i.calibration_progress = proc.calibration_progress();
        std::copy_n(offset, 3, i.offset);
    });
    const bool moved_offset = std::fabs(offset[0] - logged[0]) + std::fabs(offset[1] - logged[1]) +
                              std::fabs(offset[2] - logged[2]) > 0.05f;
    if (result != logged_result && result != gyro::Calibration::Running) {
        static const char* names[] = {"none", "running", "ok", "moved (previous offset kept)"};
        log("manual calibration: %s", names[static_cast<int>(result)]);
    }
    if (result != gyro::Calibration::Running && (moved_offset || result != logged_result)) {
        log("gyro offset now %+.3f %+.3f %+.3f deg/s (pitch yaw roll)", offset[0], offset[1], offset[2]);
        std::copy_n(offset, 3, logged);
    }
    logged_result = result;
}

void set_status(std::string s)
{
    std::lock_guard lock(g_status_mutex);
    g_status = std::move(s);
}

Config config()
{
    std::lock_guard lock(g_cfg_mutex);
    return g_cfg;
}

// Sleeps ~1 ms without changing the process-wide timer resolution.
struct Ticker {
    HANDLE timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    ~Ticker() { if (timer) CloseHandle(timer); }
    void wait_ms(double ms)
    {
        LARGE_INTEGER due;
        due.QuadPart = -static_cast<LONGLONG>(ms * 10000);
        if (timer && SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE))
            WaitForSingleObject(timer, 100);
        else
            Sleep(1);
    }
};

void apply_pending(gyro::Processor& proc)
{
    if (g_cfg_dirty.exchange(false)) {
        const bool before = proc.auto_calibrating();
        proc.configure(config().motion);
        if (proc.auto_calibrating() != before) log("automatic calibration %s", before ? "off" : "on");
    }
    const double seconds = g_calibrate.exchange(0);
    if (seconds > 0) {
        proc.calibrate(seconds);
        update_info([&](Info& i) { i.calibration_deadline_s = now_s() + seconds + 2; });
        log("manual calibration started (%.1f s) - keep the controller still", seconds);
    }
}

// Replays a recorded motion CSV (elapsed_s,segment,sample_t_s,gyro dps x3,accel g x3) in real time (for repeatable in-game tests, e.g. the same motion at 30/60/144 fps).
void replay_loop(const std::string& path)
{
    std::vector<gyro::Sample> samples;
    if (FILE* f = std::fopen(path.c_str(), "r")) {
        char line[512];
        while (std::fgets(line, sizeof line, f)) {
            double elapsed, t;
            char seg[32];
            gyro::Sample s;
            if (std::sscanf(line, "%lf,%31[^,],%lf,%f,%f,%f,%f,%f,%f", &elapsed, seg, &t, &s.gyro_dps[0], &s.gyro_dps[1],
                            &s.gyro_dps[2], &s.accel_g[0], &s.accel_g[1], &s.accel_g[2]) == 9) {
                s.t_s = t;
                samples.push_back(s);
            }
        }
        std::fclose(f);
    }
    log("replay: %zu samples from %s", samples.size(), path.c_str());
    if (samples.empty()) return;
    gyro::Processor proc;
    Ticker ticker;
    gyro::Delta total;
    const double wall0 = now_s(), t0 = samples.front().t_s;
    size_t i = 0;
    set_status("replaying " + path);
    while (g_run && i < samples.size()) {
        apply_pending(proc);
        update_info([&](Info& info) {
            info.source = Source::Replay;
            info.last_packet_s = now_s();
        });
        publish_calibration(proc);
        while (i < samples.size() && samples[i].t_s - t0 <= now_s() - wall0) {
            const gyro::Delta d = proc.process(samples[i++]);
            total.yaw_deg += d.yaw_deg;
            total.pitch_deg += d.pitch_deg;
            g_hold.set(proc.rate(), wall0 + (samples[i - 1].t_s - t0));
        }
        ticker.wait_ms(1);
    }
    if (i == samples.size() && samples.size() > 1) // stream ends one sample period after the last sample
        g_hold.set({}, wall0 + 2 * samples.back().t_s - samples[samples.size() - 2].t_s - t0);
    log("replay done: controller yaw %+.4f pitch %+.4f deg", total.yaw_deg, total.pitch_deg);
    set_status("replay done");
}

// Fallback source when Steam Input hands the game no controller, e.g. a DualSense with Steam Input off (BL4
// supports PlayStation pads natively). Only SDL's HIDAPI drivers are enabled: SDL must not register RawInput or
// open the XInput/WGI/GameInput devices the game itself reads, and must not change the pad's LEDs.
struct HidPad {
    bool ready = false;
    SDL_Gamepad* pad = nullptr;
    float accel[3] = {0, 9.80665f, 0};
    std::uint64_t last_ns = 0;

    void init()
    {
        for (const char* hint : {SDL_HINT_JOYSTICK_RAWINPUT, SDL_HINT_JOYSTICK_WGI, SDL_HINT_JOYSTICK_GAMEINPUT,
                                 SDL_HINT_XINPUT_ENABLED, SDL_HINT_JOYSTICK_DIRECTINPUT,
                                 SDL_HINT_JOYSTICK_HIDAPI_PS5_PLAYER_LED, SDL_HINT_JOYSTICK_HIDAPI_SWITCH_PLAYER_LED,
                                 SDL_HINT_JOYSTICK_HIDAPI_SWITCH_HOME_LED})
            SDL_SetHint(hint, "0");
        SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1"); // the game window is not SDL's
        ready = SDL_Init(SDL_INIT_GAMEPAD);
        if (ready) log("HID (SDL %d.%d.%d) ready", SDL_MAJOR_VERSION, SDL_MINOR_VERSION, SDL_MICRO_VERSION);
        else log("HID unavailable: SDL_Init failed: %s", SDL_GetError());
    }

    const char* name() const { return SDL_GetGamepadStringForType(SDL_GetGamepadType(pad)); }

    // Opens the first gamepad that has a gyro.
    bool open_first()
    {
        int count = 0;
        SDL_JoystickID* ids = SDL_GetGamepads(&count);
        for (int i = 0; ids && i < count && !pad; ++i) {
            pad = SDL_OpenGamepad(ids[i]);
            if (pad && !SDL_GamepadHasSensor(pad, SDL_SENSOR_GYRO)) {
                SDL_CloseGamepad(pad);
                pad = nullptr;
            }
        }
        SDL_free(ids);
        if (!pad) return false;
        SDL_SetGamepadSensorEnabled(pad, SDL_SENSOR_GYRO, true);
        if (SDL_GamepadHasSensor(pad, SDL_SENSOR_ACCEL)) SDL_SetGamepadSensorEnabled(pad, SDL_SENSOR_ACCEL, true);
        return true;
    }

    void close()
    {
        if (pad) SDL_CloseGamepad(pad);
        pad = nullptr;
    }

    void quit()
    {
        close();
        if (ready) SDL_Quit();
        ready = false;
    }
};

// Controller buttons for the panel, the combo and the gyro button. BL4 reads the pad through a path the mod's
// input hook never sees, so the DLL reads it itself: SDL when the HID pad is open, otherwise XInput, which is how
// the game sees a Steam Input controller (Steam's virtual pad). Bits: 0 A, 1 B, 2 X, 3 Y, 4 View, 5 Menu, 6 L3,
// 7 R3, 8 LB, 9 RB, 10-13 D-pad up/down/left/right, 14 LT, 15 RT (positional names, Xbox layout). 0 while the game
// window is not focused.
std::atomic<unsigned> g_buttons{0};
// Right stick for Flick Stick, -1..1 (x right +, y up +), read with the buttons from the same source; 0 while the game
// window is not focused (g_focused false). Raw: the game's own stick deadzone/sensitivity never applies to it.
std::atomic<float> g_stick_x{0}, g_stick_y{0};
std::atomic<bool> g_focused{false};

struct XInputPads {
    using GetState = DWORD(WINAPI*)(DWORD, XINPUT_STATE*);
    GetState get_state = nullptr;
    bool connected[XUSER_MAX_COUNT] = {};
    double next_scan = 0;

    void init()
    {
        for (const wchar_t* dll : {L"xinput1_4.dll", L"xinput9_1_0.dll"}) {
            if (HMODULE m = LoadLibraryW(dll)) {
                get_state = reinterpret_cast<GetState>(GetProcAddress(m, "XInputGetState"));
                if (get_state) return;
            }
        }
        log("XInput unavailable: controller buttons only through HID");
    }

    unsigned read(double now, float stick[2])
    {
        stick[0] = stick[1] = 0;
        if (!get_state) return 0;
        const bool scan = now >= next_scan; // probing empty slots is slow: only once a second
        if (scan) next_scan = now + 1;
        unsigned bits = 0;
        for (DWORD i = 0; i < XUSER_MAX_COUNT; ++i) {
            if (!connected[i] && !scan) continue;
            XINPUT_STATE st{};
            connected[i] = get_state(i, &st) == ERROR_SUCCESS;
            if (!connected[i]) continue;
            const WORD b = st.Gamepad.wButtons;
            const struct { WORD x; unsigned bit; } map[] = {
                {XINPUT_GAMEPAD_A, 0}, {XINPUT_GAMEPAD_B, 1}, {XINPUT_GAMEPAD_X, 2}, {XINPUT_GAMEPAD_Y, 3},
                {XINPUT_GAMEPAD_BACK, 4}, {XINPUT_GAMEPAD_START, 5}, {XINPUT_GAMEPAD_LEFT_THUMB, 6},
                {XINPUT_GAMEPAD_RIGHT_THUMB, 7}, {XINPUT_GAMEPAD_LEFT_SHOULDER, 8}, {XINPUT_GAMEPAD_RIGHT_SHOULDER, 9},
                {XINPUT_GAMEPAD_DPAD_UP, 10}, {XINPUT_GAMEPAD_DPAD_DOWN, 11}, {XINPUT_GAMEPAD_DPAD_LEFT, 12},
                {XINPUT_GAMEPAD_DPAD_RIGHT, 13}};
            for (const auto& m : map)
                if (b & m.x) bits |= 1u << m.bit;
            if (st.Gamepad.bLeftTrigger > 128) bits |= 1u << 14;
            if (st.Gamepad.bRightTrigger > 128) bits |= 1u << 15;
            const float x = std::max(st.Gamepad.sThumbRX / 32767.0f, -1.0f);
            const float y = std::max(st.Gamepad.sThumbRY / 32767.0f, -1.0f);
            if (x * x + y * y > stick[0] * stick[0] + stick[1] * stick[1]) { // several pads: the one being used
                stick[0] = x;
                stick[1] = y;
            }
        }
        return bits;
    }
};

unsigned sdl_buttons(SDL_Gamepad* pad, float stick[2])
{
    stick[0] = std::max(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_RIGHTX) / 32767.0f, -1.0f);
    stick[1] = -std::max(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_RIGHTY) / 32767.0f, -1.0f); // SDL: down +
    const SDL_GamepadButton map[] = {SDL_GAMEPAD_BUTTON_SOUTH, SDL_GAMEPAD_BUTTON_EAST, SDL_GAMEPAD_BUTTON_WEST,
                                     SDL_GAMEPAD_BUTTON_NORTH, SDL_GAMEPAD_BUTTON_BACK, SDL_GAMEPAD_BUTTON_START,
                                     SDL_GAMEPAD_BUTTON_LEFT_STICK, SDL_GAMEPAD_BUTTON_RIGHT_STICK,
                                     SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,
                                     SDL_GAMEPAD_BUTTON_DPAD_UP, SDL_GAMEPAD_BUTTON_DPAD_DOWN,
                                     SDL_GAMEPAD_BUTTON_DPAD_LEFT, SDL_GAMEPAD_BUTTON_DPAD_RIGHT};
    unsigned bits = 0;
    for (unsigned i = 0; i < std::size(map); ++i)
        if (SDL_GetGamepadButton(pad, map[i])) bits |= 1u << i;
    if (SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) > 16000) bits |= 1u << 14;
    if (SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) > 16000) bits |= 1u << 15;
    return bits;
}

// Printed names of the buttons the panel uses, "confirm|back|left shoulder|right shoulder" (bottom face, right face,
// LB, RB by position), so hints read "X / O" on a DualSense and follow Steam's Nintendo-layout setting. Empty when
// unknown: the mod then names them by controller family.
std::mutex g_names_mutex;
std::string g_button_names;

std::string steam_button_names(const steam::Input& input, steam::Handle h)
{
    std::string names;
    for (int xbox : {0, 1, 4, 5}) { // EXboxOrigin A, B, LeftBumper, RightBumper
        const char* label = steam::origin_label(input.origin_for_xbox(h, xbox));
        if (!label) return {};
        names += (names.empty() ? "" : "|") + std::string(label);
    }
    return names;
}

std::string sdl_button_names(SDL_Gamepad* pad)
{
    static const char* face[] = {nullptr, "A", "B", "X", "Y", "X", "O", "Square", "Triangle"}; // SDL_GamepadButtonLabel
    const int ok = SDL_GetGamepadButtonLabel(pad, SDL_GAMEPAD_BUTTON_SOUTH);
    const int back = SDL_GetGamepadButtonLabel(pad, SDL_GAMEPAD_BUTTON_EAST);
    if (ok <= 0 || ok >= 9 || back <= 0 || back >= 9) return {};
    const SDL_GamepadType type = SDL_GetGamepadType(pad);
    const bool ps = type == SDL_GAMEPAD_TYPE_PS3 || type == SDL_GAMEPAD_TYPE_PS4 || type == SDL_GAMEPAD_TYPE_PS5;
    const bool nintendo = type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_PRO ||
                          type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT ||
                          type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT ||
                          type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_PAIR;
    return std::string(face[ok]) + "|" + face[back] + (ps ? "|L1|R1" : nintendo ? "|L|R" : "|LB|RB");
}

// SDL keeps reporting while the game is in the background; Steam sends nothing then, so match it.
bool game_has_focus()
{
    DWORD pid = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &pid);
    return pid == GetCurrentProcessId();
}

// Steam can list a pad it doesn't drive (Steam Input off for it) and never send a new motion packet, even with the
// game focused. After this long without motion in focus, that handle is skipped so the HID fallback can take the pad.
constexpr double kSteamSilentS = 3;

void sensor_loop()
{
    steam::Input input;
    HidPad hid;
    gyro::Processor proc;
    Ticker ticker;
    steam::Handle active = 0, silent = 0;
    double quiet_since = 0;
    steam::MotionData prev{};
    double next_open = 0, window_start = now_s(), next_log = now_s() + 10;
    int packets = 0, type = 0, loops = 0;
    bool rescan = true; // pads already plugged in at start send no ADDED event we could miss
    XInputPads xinput;
    double next_buttons = 0;
    hid.init();
    xinput.init();
    double last_packet = -1;
    while (g_run) {
        ++loops;
        apply_pending(proc);
        const double now = now_s();
        if (!input.is_open()) {
            if (now >= next_open) {
                std::string error;
                if (input.open(nullptr, false, error)) log("Steam Input opened");
                else log("Steam Input unavailable: %s", error.c_str());
                next_open = now + 5;
            }
        } else {
            const std::vector<steam::Handle> handles = input.controllers();
            if (active && std::find(handles.begin(), handles.end(), active) == handles.end()) {
                log("controller %llu disconnected", static_cast<unsigned long long>(active));
                active = 0;
                proc.reset();
                rescan = true;
            }
            if (silent && std::find(handles.begin(), handles.end(), silent) == handles.end()) silent = 0;
            const auto pick = std::find_if(handles.begin(), handles.end(), [&](steam::Handle h) { return h != silent; });
            if (!active && pick != handles.end()) {
                if (hid.pad) {
                    log("HID %s released: Steam Input has a controller", hid.name());
                    hid.close();
                }
                active = *pick;
                type = input.type(active);
                quiet_since = now;
                proc.reset();
                log("controller %llu connected: %s (%d)", static_cast<unsigned long long>(active), steam::type_name(type), type);
            }
            if (active) {
                const steam::MotionData m = input.motion(active);
                if (steam::has_data(m) && std::memcmp(&m, &prev, sizeof m) != 0) {
                    prev = m;
                    proc.process(gyro::from_steam(now, m.rot_vel, m.pos_accel));
                    g_hold.set(proc.rate(), now);
                    ++packets;
                    last_packet = now;
                    trace("P,%.6f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.7f,%.7f,%.7f,%.7f\n", now, m.rot_vel[0], m.rot_vel[1],
                          m.rot_vel[2], m.pos_accel[0], m.pos_accel[1], m.pos_accel[2], m.rot_quat[0], m.rot_quat[1],
                          m.rot_quat[2], m.rot_quat[3]);
                }
                if (last_packet >= quiet_since || !game_has_focus()) {
                    quiet_since = now;
                } else if (now - quiet_since > kSteamSilentS) {
                    log("controller %llu sends no motion: trying HID", static_cast<unsigned long long>(active));
                    silent = active;
                    active = 0;
                    proc.reset();
                    rescan = true;
                }
            }
        }
        if (hid.ready) {
            SDL_Event ev;
            while (SDL_PollEvent(&ev)) {
                if (ev.type == SDL_EVENT_GAMEPAD_ADDED) {
                    rescan = true;
                } else if (ev.type == SDL_EVENT_GAMEPAD_REMOVED && hid.pad && ev.gdevice.which == SDL_GetGamepadID(hid.pad)) {
                    log("HID %s disconnected", hid.name());
                    hid.close();
                    proc.reset();
                    rescan = true;
                } else if (ev.type == SDL_EVENT_GAMEPAD_SENSOR_UPDATE && hid.pad && ev.gsensor.which == SDL_GetGamepadID(hid.pad)) {
                    if (ev.gsensor.sensor == SDL_SENSOR_ACCEL) {
                        std::memcpy(hid.accel, ev.gsensor.data, sizeof hid.accel);
                    } else if (ev.gsensor.sensor == SDL_SENSOR_GYRO && ev.gsensor.sensor_timestamp != hid.last_ns &&
                               game_has_focus()) {
                        // Pads can repeat one IMU reading over several reports (Switch2Connect's DualSense: 1 kHz
                        // reports, ~65 Hz IMU); a repeat has dt 0 and would zero the held rate.
                        hid.last_ns = ev.gsensor.sensor_timestamp;
                        const gyro::Sample s = gyro::from_sdl(ev.gsensor.sensor_timestamp, ev.gsensor.data, hid.accel);
                        proc.process(s);
                        g_hold.set(proc.rate(), now);
                        ++packets;
                        last_packet = now;
                        // HID rows carry the converted sample (deg/s, g, SDL axes) and no quaternion.
                        trace("P,%.6f,%.2f,%.2f,%.2f,%.4f,%.4f,%.4f,0,0,0,0\n", now, s.gyro_dps[0], s.gyro_dps[1],
                              s.gyro_dps[2], s.accel_g[0], s.accel_g[1], s.accel_g[2]);
                    }
                }
            }
            if (rescan && !active && !hid.pad) {
                rescan = false;
                if (hid.open_first()) {
                    proc.reset();
                    log("HID %s connected: %s", hid.name(), SDL_GetGamepadName(hid.pad));
                }
            }
        }
        if (now >= next_buttons) { // ~125 Hz is plenty for menu input
            next_buttons = now + 0.008;
            const bool focused = game_has_focus();
            float stick[2] = {};
            g_buttons = !focused ? 0 : hid.pad ? sdl_buttons(hid.pad, stick) : xinput.read(now, stick);
            g_stick_x = stick[0];
            g_stick_y = stick[1];
            g_focused = focused;
        }
        update_info([&](Info& i) {
            i.source = active ? Source::Steam : hid.pad ? Source::Hid : input.is_open() || hid.ready ? Source::None
                                                                                                  : Source::SteamUnavailable;
            i.last_packet_s = last_packet;
        });
        publish_calibration(proc);
        if (now - window_start >= 2) {
            char status[160];
            const std::string source = active    ? steam::type_name(type)
                                       : hid.pad ? std::string(hid.name()) + " (HID)"
                                       : input.is_open() || hid.ready ? "no controller"
                                                                      : "Steam Input unavailable";
            std::snprintf(status, sizeof status, "%s | %.0f motion packets/s | %.0f loops/s%s", source.c_str(),
                          packets / (now - window_start), loops / (now - window_start),
                          proc.calibrating() ? " | calibrating" : "");
            set_status(status);
            update_info([&](Info& i) { i.packets_per_s = packets / (now - window_start); });
            {
                std::string names = active ? steam_button_names(input, active) : hid.pad ? sdl_button_names(hid.pad) : "";
                std::lock_guard lock(g_names_mutex);
                g_button_names = std::move(names); // refreshed every 2 s: follows reconnects and layout changes
            }
            trace("L,%.6f,%d,%d\n", now, loops, packets);
            loops = 0;
            if (now >= next_log) {
                log("status: %s", status);
                next_log = now + 30;
            }
            packets = 0;
            window_start = now;
        }
        ticker.wait_ms(1);
    }
    hid.quit();
    input.close();
}

void sensor_thread()
{
    log("sensor thread started");
    if (g_replay_csv.empty()) sensor_loop();
    else replay_loop(g_replay_csv);
    log("sensor thread stopped");
}

} // namespace

#define BL4GYRO_API extern "C" __declspec(dllexport)

// Starts the sensor thread. replay_csv: optional motion CSV to play instead of the controller.
BL4GYRO_API int bl4gyro_start(const wchar_t* log_path, const char* replay_csv)
{
    if (g_run) return 1;
    {
        std::lock_guard lock(g_log_mutex);
        if (!g_log && log_path) g_log = _wfopen(log_path, L"w");
    }
    if (log_path) {
        g_dir = log_path;
        g_dir.erase(g_dir.find_last_of(L"\\/") + 1);
    }
    g_replay_csv = replay_csv ? replay_csv : "";
    g_hold.set({}, now_s()); // drop anything left from a previous run
    g_hold.take(now_s());
    g_cfg_dirty = true;
    update_info([](Info& i) { i = Info{}; });
    g_run = true;
    g_thread = std::thread(sensor_thread);
    log("bl4gyro started%s", g_replay_csv.empty() ? "" : " (replay)");
    return 1;
}

BL4GYRO_API void bl4gyro_stop()
{
    g_run = false;
    if (g_thread.joinable()) g_thread.join();
    set_trace(false);
    g_buttons = 0;
    g_stick_x = g_stick_y = 0;
    g_focused = false;
    set_status("stopped");
    log("bl4gyro stopped");
    std::lock_guard lock(g_log_mutex);
    if (g_log) std::fclose(g_log);
    g_log = nullptr;
}

// Settings by name so the Python side does not depend on a struct layout. Returns 0 for unknown keys.
BL4GYRO_API int bl4gyro_set(const char* key, double value)
{
    const std::string k = key ? key : "";
    if (k == "trace") {
        set_trace(value != 0);
        return 1;
    }
    std::lock_guard lock(g_cfg_mutex);
    gyro::Settings& m = g_cfg.motion;
    gyro::Camera& c = g_cfg.camera;
    if (k == "sens_x") c.sens_x = value;
    else if (k == "sens_y") c.sens_y = value;
    else if (k == "ads_multiplier") c.ads_multiplier = value;
    else if (k == "invert_x") c.invert_x = value != 0;
    else if (k == "invert_y") c.invert_y = value != 0;
    else if (k == "player_space") m.space = value != 0 ? gyro::Space::Player : gyro::Space::Local;
    else if (k == "auto_calibrate") m.auto_calibrate = value != 0;
    else if (k == "tighten_dps") m.tighten_dps = static_cast<float>(value);
    else if (k == "smooth_dps") m.smooth_dps = static_cast<float>(value);
    else return 0;
    g_cfg_dirty = true;
    return 1;
}

BL4GYRO_API void bl4gyro_calibrate(double seconds) { g_calibrate = seconds; }

// Camera delta in degrees (yaw right +, pitch up +) accumulated since the last call.
BL4GYRO_API void bl4gyro_take(int ads, double* yaw_deg, double* pitch_deg)
{
    const gyro::Delta d = gyro::to_camera(g_hold.take(now_s()), config().camera, ads != 0);
    *yaw_deg = d.yaw_deg;
    *pitch_deg = d.pitch_deg;
    trace("T,%.6f,%d,%.5f,%.5f\n", now_s(), ads, d.yaw_deg, d.pitch_deg);
}

// Lets the sdkmod add game-side rows (e.g. ControlRotation per frame) to the same timeline as the packets.
BL4GYRO_API void bl4gyro_trace_line(const char* text)
{
    if (text) trace("%s,%.6f,%s\n", "R", now_s(), text);
}

// Printed button names (see g_button_names), "" when unknown. Returns 1 when a name list was written.
BL4GYRO_API int bl4gyro_button_names(char* buf, int size)
{
    if (!buf || size <= 0) return 0;
    std::lock_guard lock(g_names_mutex);
    std::snprintf(buf, static_cast<size_t>(size), "%s", g_button_names.c_str());
    return g_button_names.empty() ? 0 : 1;
}

// Controller buttons as a bit mask (see g_buttons). Read by the mod once per camera update.
BL4GYRO_API unsigned bl4gyro_buttons() { return g_buttons; }

// Right stick (see g_stick_x). Returns 1 while the game window is focused, 0 otherwise (stick reads 0 then).
BL4GYRO_API int bl4gyro_stick(double* x, double* y)
{
    if (x) *x = g_stick_x;
    if (y) *y = g_stick_y;
    return g_focused ? 1 : 0;
}

// Panel status as numbers: [0] source (0 none, 1 Steam, 2 HID, 3 replay, 4 Steam Input unavailable),
// [1] motion packets/s (2 s window), [2] seconds since the last packet (-1 none yet), [3] calibration progress 0..1,
// [4] calibration (0 none, 1 running, 2 ok, 3 moved: previous offset kept, 4 unused (was "not lying flat"),
// 5 running without data past its deadline), [5..7] gyro offset being subtracted (deg/s, pitch yaw roll).
// Returns how many values were written.
BL4GYRO_API int bl4gyro_info(double* out, int n)
{
    if (!out || n <= 0) return 0;
    std::lock_guard lock(g_info_mutex);
    const Info& i = g_info;
    const double now = now_s();
    int calibration = static_cast<int>(i.calibration);
    if (i.calibration == gyro::Calibration::Running && now > i.calibration_deadline_s) calibration = 5;
    const double values[] = {static_cast<double>(i.source), i.packets_per_s,
                             i.last_packet_s < 0 ? -1 : now - i.last_packet_s, i.calibration_progress,
                             static_cast<double>(calibration), i.offset[0], i.offset[1], i.offset[2]};
    const int count = std::min(n, static_cast<int>(std::size(values)));
    std::copy_n(values, count, out);
    return count;
}

BL4GYRO_API int bl4gyro_status(char* buf, int size)
{
    std::lock_guard lock(g_status_mutex);
    if (!buf || size <= 0) return 0;
    std::snprintf(buf, static_cast<size_t>(size), "%s", g_status.c_str());
    return 1;
}
