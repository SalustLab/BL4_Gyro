// bl4gyro.dll - runs inside Borderlands 4. A sensor thread reads the controller's motion through the game's
// own Steam Input (Steam only delivers it while the game window has focus), turns it into calibrated controller
// rotation (gyro::Processor) and accumulates it. The NativeGyro sdkmod drains it once per camera update through
// this C ABI (ctypes) and feeds it to AddYawInput/AddPitchInput on the game thread.
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

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
    if (g_cfg_dirty.exchange(false)) proc.configure(config().motion);
    const double seconds = g_calibrate.exchange(0);
    if (seconds > 0) {
        proc.calibrate(seconds);
        log("manual calibration started (%.1f s) - keep the controller still", seconds);
    }
}

// Replays a ttmax-diag CSV in real time (for repeatable in-game tests, e.g. the same motion at 30/60/144 fps).
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

void steam_loop()
{
    steam::Input input;
    gyro::Processor proc;
    Ticker ticker;
    steam::Handle active = 0;
    steam::MotionData prev{};
    double next_open = 0, window_start = now_s(), next_log = now_s() + 10;
    int packets = 0, type = 0, loops = 0;
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
            }
            if (!active && !handles.empty()) {
                active = handles.front();
                type = input.type(active);
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
                    trace("P,%.6f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.7f,%.7f,%.7f,%.7f\n", now, m.rot_vel[0], m.rot_vel[1],
                          m.rot_vel[2], m.pos_accel[0], m.pos_accel[1], m.pos_accel[2], m.rot_quat[0], m.rot_quat[1],
                          m.rot_quat[2], m.rot_quat[3]);
                }
            }
        }
        if (now - window_start >= 2) {
            char status[160];
            std::snprintf(status, sizeof status, "%s | %.0f motion packets/s | %.0f loops/s%s",
                          active ? steam::type_name(type) : (input.is_open() ? "no controller" : "Steam Input unavailable"),
                          packets / (now - window_start), loops / (now - window_start),
                          proc.calibrating() ? " | calibrating" : "");
            set_status(status);
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
    input.close();
}

void sensor_thread()
{
    log("sensor thread started");
    if (g_replay_csv.empty()) steam_loop();
    else replay_loop(g_replay_csv);
    log("sensor thread stopped");
}

} // namespace

#define BL4GYRO_API extern "C" __declspec(dllexport)

// Starts the sensor thread. replay_csv: optional ttmax-diag CSV to play instead of the controller.
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

BL4GYRO_API int bl4gyro_status(char* buf, int size)
{
    std::lock_guard lock(g_status_mutex);
    if (!buf || size <= 0) return 0;
    std::snprintf(buf, static_cast<size_t>(size), "%s", g_status.c_str());
    return 1;
}
