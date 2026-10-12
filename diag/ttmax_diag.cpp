// ttmax-diag: shows what motion data a controller really exposes on this PC.
//
//   ttmax-diag hid                         list HID interfaces (VID/PID, usages, bus, descriptor size)
//   ttmax-diag sdl   [options]             SDL3 gamepad + sensors, guided protocol
//   ttmax-diag steam [options]             Steam Input GetMotionData as Borderlands 4, guided protocol
// options: --seconds N (timeout, default 300) | --rest N (rest-only drift run) | --label NAME (writes
//          evidence/A-NAME.csv and .txt) | --steam-dll PATH
#include <SDL3/SDL.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include <windows.h>
#include <timeapi.h>

#include "gyro.hpp"
#include "steam_motion.hpp"

namespace {

const wchar_t* kGameSteamDll =
    L"F:\\SteamLibrary\\steamapps\\common\\Borderlands 4\\Engine\\Binaries\\ThirdParty\\Steamworks\\Steamv157\\Win64\\steam_api64.dll";

double host_now()
{
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

std::string narrow(const wchar_t* w)
{
    if (!w) return {};
    const int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    std::string s(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, w, -1, s.data(), n, nullptr, nullptr);
    return s;
}

struct Options {
    double seconds = 300;
    double rest_only = 0;
    std::string label;
    std::wstring steam_dll = kGameSteamDll;
};

// evidence/live.log: append-only, flushed per line, so a test can be watched while it runs.
FILE* g_live = nullptr;

void live(const std::string& s)
{
    if (!g_live) return;
    std::fprintf(g_live, "%s\n", s.c_str());
    std::fflush(g_live);
}

// Report goes to stdout, the live log and, with --label, to evidence/A-<label>.txt.
struct Report {
    FILE* txt = nullptr;
    void line(const std::string& s)
    {
        std::printf("%s\n", s.c_str());
        live(s);
        if (txt) std::fprintf(txt, "%s\n", s.c_str());
    }
};

std::string fmt(const char* f, ...)
{
    char buf[1024];
    va_list args;
    va_start(args, f);
    std::vsnprintf(buf, sizeof buf, f, args);
    va_end(args);
    return buf;
}

// ---------------------------------------------------------------- guided protocol

// Steps advance on Enter (the console), except the first rest step which is timed.
// Full turns are used because "back to the starting alignment" is precise enough to measure scale.
struct Step {
    const char* id;
    const char* prompt;
};

const Step kSteps[] = {
    {"rest", "REST: leave the controller still on the desk (8 s, advances by itself)"},
    {"yaw", "YAW: controller flat on the desk, turn it ONE FULL TURN (360) CLOCKWISE seen from above, back to the starting "
            "alignment. Then press Enter"},
    {"pitch", "PITCH: lay it flat again, then raise the FRONT until it stands upright (90 deg, front to the ceiling). "
              "Hold and press Enter"},
    {"trigger", "TRIGGER: press ZR/RT slowly all the way down twice. Then press Enter"},
    {"free", "FREE: optional - disconnect and reconnect the controller. Press Enter to finish"},
};
constexpr int kStepCount = static_cast<int>(std::size(kSteps));
constexpr double kRestSeconds = 8;

double percentile(std::vector<double> v, double p)
{
    if (v.empty()) return 0;
    std::sort(v.begin(), v.end());
    return v[static_cast<size_t>(p * (v.size() - 1))];
}

class Recorder {
public:
    Recorder(FILE* csv, const Options& opt) : csv_(csv), opt_(opt) {}

    void start(double host) { t0_ = host; }
    bool started() const { return t0_ > 0; }
    double elapsed(double host) const { return started() ? host - t0_ : 0; }
    bool done(double host) const
    {
        if (!started()) return false;
        if (opt_.rest_only > 0) return elapsed(host) >= opt_.rest_only;
        return step_ >= kStepCount || elapsed(host) >= opt_.seconds;
    }

    void next_step() { ++step_; } // called from the console thread on Enter

    const char* segment(double) const
    {
        if (opt_.rest_only > 0) return "rest";
        return kSteps[std::min(step_.load(), kStepCount - 1)].id;
    }

    void prompt(double host)
    {
        if (opt_.rest_only == 0 && step_ == 0 && elapsed(host) >= kRestSeconds) step_ = 1;
        const int step = step_;
        if (step == prompted_step_ || step >= kStepCount) return;
        prompted_step_ = step;
        const char* text = opt_.rest_only > 0 ? "REST: drift run, do not touch the controller" : kSteps[step].prompt;
        std::printf("\n>>> [%5.1fs] %s\n", elapsed(host), text);
        live(fmt(">>> [%5.1fs] %s", elapsed(host), text));
    }

    // One live-log line every few seconds: what the sensor is doing right now.
    void status(double host)
    {
        if (!started() || host - last_status_ < 3.0) return;
        const double window = last_status_ > 0 ? host - last_status_ : elapsed(host);
        last_status_ = host;
        const double n = win_n_ ? win_n_ : 1;
        live(fmt("[%5.1fs] %-7s %4d samples (%.0f/s host) gyro p/y/r %+7.2f %+7.2f %+7.2f dps |a| %.3f g  "
                 "turned yaw %+6.1f pitch %+6.1f  stickR %6d  trigR %6d",
                 elapsed(host), segment(host), win_n_, win_n_ / window, win_gyro_[0] / n, win_gyro_[1] / n,
                 win_gyro_[2] / n, last_accel_, total_.yaw_deg, total_.pitch_deg, win_stick_, last_trigger_));
        win_n_ = 0;
        win_gyro_[0] = win_gyro_[1] = win_gyro_[2] = 0;
        win_stick_ = 0;
    }

    // One gyro+accel sample (sensor or host clock in s.t_s), arrival time in host seconds.
    void sample(const gyro::Sample& s, double host)
    {
        if (!started()) start(host);
        const char* seg = segment(host);
        if (csv_)
            std::fprintf(csv_, "%.6f,%s,%.6f,%.4f,%.4f,%.4f,%.5f,%.5f,%.5f\n", elapsed(host), seg, s.t_s, s.gyro_dps[0],
                         s.gyro_dps[1], s.gyro_dps[2], s.accel_g[0], s.accel_g[1], s.accel_g[2]);
        if (prev_sensor_ > 0) {
            sensor_dt_.push_back((s.t_s - prev_sensor_) * 1000);
            host_dt_.push_back((host - prev_host_) * 1000);
        }
        prev_sensor_ = s.t_s;
        prev_host_ = host;
        ++samples_;
        ++win_n_;
        for (int i = 0; i < 3; ++i) win_gyro_[i] += s.gyro_dps[i];
        last_accel_ = std::sqrt(s.accel_g[0] * s.accel_g[0] + s.accel_g[1] * s.accel_g[1] + s.accel_g[2] * s.accel_g[2]);
        if (first_sensor_ == 0) first_sensor_ = s.t_s;
        last_sensor_ = s.t_s;

        const bool still = std::fabs(s.gyro_dps[0]) < 2 && std::fabs(s.gyro_dps[1]) < 2 && std::fabs(s.gyro_dps[2]) < 2;
        if (std::strcmp(seg, "rest") == 0) {
            if (!still) return; // picking up / setting down the controller must not pollute the bias
            for (int i = 0; i < 3; ++i) {
                rest_sum_[i] += s.gyro_dps[i];
                rest_sq_[i] += s.gyro_dps[i] * s.gyro_dps[i];
            }
            rest_accel_ += std::sqrt(s.accel_g[0] * s.accel_g[0] + s.accel_g[1] * s.accel_g[1] +
                                     s.accel_g[2] * s.accel_g[2]);
            ++rest_n_;
        } else if (rest_n_ > 0) {
            // Bias-corrected local-space integration (rest mean removed).
            gyro::Sample c = s;
            for (int i = 0; i < 3; ++i) c.gyro_dps[i] -= static_cast<float>(rest_sum_[i] / rest_n_);
            const gyro::Delta d = integrator_.process(c);
            angle_[seg].yaw_deg += d.yaw_deg;
            angle_[seg].pitch_deg += d.pitch_deg;
            total_.yaw_deg += d.yaw_deg;
            total_.pitch_deg += d.pitch_deg;
            return;
        }
        integrator_.process(s);
    }

    void axis(const char* name, int value, double host)
    {
        if (!started()) start(host);
        const char* seg = segment(host);
        if (csv_) std::fprintf(csv_, "%.6f,%s,axis:%s,%d\n", elapsed(host), seg, name, value);
        if (std::strstr(name, "trigger")) trigger_values_[name].insert(value);
        if (std::strcmp(name, "right_trigger") == 0) last_trigger_ = value;
        if (std::strcmp(name, "right_x") == 0 || std::strcmp(name, "right_y") == 0)
            win_stick_ = std::max(win_stick_, std::abs(value));
        if (std::strstr(name, "right")&& (std::strcmp(seg, "yaw") == 0 || std::strcmp(seg, "pitch") == 0))
            stick_during_rotation_ = std::max(stick_during_rotation_, std::abs(value));
    }

    void event(const std::string& text, double host)
    {
        events_.push_back(fmt("[%6.2fs] ", elapsed(host)) + text);
        std::printf("%s\n", events_.back().c_str());
        live(events_.back());
    }

    void summarize(Report& r, bool guided_axes)
    {
        r.line("--- samples");
        const double span = last_sensor_ - first_sensor_;
        r.line(fmt("gyro samples: %d over %.2f s (sample clock) -> %.1f Hz", samples_, span,
                   span > 0 ? (samples_ - 1) / span : 0.0));
        r.line(fmt("sample dt ms: min %.2f  p50 %.2f  p99 %.2f  max %.2f  (non-positive: %lld)", percentile(sensor_dt_, 0),
                   percentile(sensor_dt_, .5), percentile(sensor_dt_, .99), percentile(sensor_dt_, 1),
                   static_cast<long long>(std::count_if(sensor_dt_.begin(), sensor_dt_.end(), [](double d) { return d <= 0; }))));
        r.line(fmt("arrival dt ms: p50 %.2f  p99 %.2f  max %.2f (batching shows as 0 ms arrivals)",
                   percentile(host_dt_, .5), percentile(host_dt_, .99), percentile(host_dt_, 1)));
        if (rest_n_ > 0) {
            double mean[3], sd[3];
            for (int i = 0; i < 3; ++i) {
                mean[i] = rest_sum_[i] / rest_n_;
                sd[i] = std::sqrt(std::max(0.0, rest_sq_[i] / rest_n_ - mean[i] * mean[i]));
            }
            r.line("--- rest (bias / noise / units)");
            r.line(fmt("gyro mean dps: pitch %+.3f  yaw %+.3f  roll %+.3f", mean[0], mean[1], mean[2]));
            r.line(fmt("gyro sigma dps: pitch %.3f  yaw %.3f  roll %.3f", sd[0], sd[1], sd[2]));
            r.line(fmt("accel |g| mean: %.4f (expect ~1.000)", rest_accel_ / rest_n_));
            r.line(fmt("drift if uncalibrated: %.1f deg/min yaw", std::fabs(mean[1]) * 60));
        }
        if (opt_.rest_only == 0) {
            r.line("--- sign / scale checks (bias-corrected, camera convention: yaw right +, pitch up +)");
            const gyro::Delta yaw = angle_["yaw"], pitch = angle_["pitch"];
            r.line(fmt("yaw step (expect +360): yaw %+.1f deg, pitch %+.1f deg -> %s, scale %.3f", yaw.yaw_deg,
                       yaw.pitch_deg, samples_ == 0 ? "no sensor" : yaw.yaw_deg > 0 ? "YAW SIGN OK" : "YAW SIGN WRONG",
                       yaw.yaw_deg / 360));
            r.line(fmt("pitch step (expect +90): pitch %+.1f deg, yaw %+.1f deg -> %s, scale %.3f", pitch.pitch_deg,
                       pitch.yaw_deg, samples_ == 0 ? "no sensor" : pitch.pitch_deg > 0 ? "PITCH SIGN OK" : "PITCH SIGN WRONG",
                       pitch.pitch_deg / 90));
        }
        if (guided_axes) {
            r.line("--- triggers / stick");
            for (const auto& [name, values] : trigger_values_)
                r.line(fmt("%s: %zu distinct values -> %s", name.c_str(), values.size(),
                           values.size() > 3 ? "ANALOG" : "DIGITAL"));
            r.line(fmt("right stick max |value| during yaw/pitch: %d -> %s", stick_during_rotation_,
                       samples_ == 0 && stick_during_rotation_ > 8000
                           ? "stick moves with rotation but no IMU: controller-side motion-to-stick (Motion Aim Assist)"
                           : "no motion-to-stick emulation seen"));
        }
        r.line("--- events");
        for (const std::string& e : events_) r.line(e);
    }

private:
    FILE* csv_;
    const Options& opt_;
    double t0_ = 0;
    std::atomic<int> step_{0};
    int prompted_step_ = -1;
    double prev_sensor_ = 0, prev_host_ = 0, first_sensor_ = 0, last_sensor_ = 0;
    int samples_ = 0;
    std::vector<double> sensor_dt_, host_dt_;
    double rest_sum_[3] = {}, rest_sq_[3] = {}, rest_accel_ = 0;
    int rest_n_ = 0;
    gyro::Processor integrator_{[] {
        gyro::Settings s;
        s.space = gyro::Space::Local;
        s.auto_calibrate = false;
        return s;
    }()};
    std::map<std::string, gyro::Delta> angle_;
    std::map<std::string, std::set<int>> trigger_values_;
    int stick_during_rotation_ = 0;
    double last_status_ = 0, win_gyro_[3] = {}, last_accel_ = 0;
    int win_n_ = 0, win_stick_ = 0, last_trigger_ = 0;
    gyro::Delta total_;
    std::vector<std::string> events_;
};

// ---------------------------------------------------------------- hid

int run_hid(Report& r)
{
    SDL_SetHint(SDL_HINT_HIDAPI_ENUMERATE_ONLY_CONTROLLERS, "0"); // vendor-defined interfaces matter here
    if (SDL_hid_init() != 0) {
        r.line(std::string("SDL_hid_init failed: ") + SDL_GetError());
        return 1;
    }
    SDL_hid_device_info* list = SDL_hid_enumerate(0, 0);
    int count = 0;
    for (SDL_hid_device_info* d = list; d; d = d->next, ++count) {
        const char* bus = d->bus_type == SDL_HID_API_BUS_USB         ? "USB"
                          : d->bus_type == SDL_HID_API_BUS_BLUETOOTH ? "BT"
                          : d->bus_type == SDL_HID_API_BUS_I2C       ? "I2C"
                          : d->bus_type == SDL_HID_API_BUS_SPI       ? "SPI"
                                                                     : "?";
        r.line(fmt("%04x:%04x usage %04x:%04x if %d bus %s  \"%s\" / \"%s\"", d->vendor_id, d->product_id, d->usage_page,
                   d->usage, d->interface_number, bus, narrow(d->manufacturer_string).c_str(),
                   narrow(d->product_string).c_str()));
        r.line(std::string("    ") + d->path);
        const bool gamepad = d->usage_page == 0x01 && (d->usage == 0x04 || d->usage == 0x05);
        if (gamepad || d->vendor_id == 0x057e) {
            if (SDL_hid_device* dev = SDL_hid_open_path(d->path)) {
                unsigned char desc[4096];
                const int n = SDL_hid_get_report_descriptor(dev, desc, sizeof desc);
                std::string hex;
                for (int i = 0; i < std::min(n, 24); ++i) hex += fmt("%02x ", desc[i]);
                r.line(fmt("    report descriptor: %d bytes: %s...", n, hex.c_str()));
                SDL_hid_close(dev);
            } else {
                r.line(std::string("    open failed: ") + SDL_GetError());
            }
        }
    }
    SDL_hid_free_enumeration(list);
    SDL_hid_exit();
    r.line(fmt("%d HID interfaces", count));
    return 0;
}

// ---------------------------------------------------------------- sdl

const char* axis_name(int axis)
{
    switch (axis) {
    case SDL_GAMEPAD_AXIS_LEFT_TRIGGER: return "left_trigger";
    case SDL_GAMEPAD_AXIS_RIGHT_TRIGGER: return "right_trigger";
    case SDL_GAMEPAD_AXIS_RIGHTX: return "right_x";
    case SDL_GAMEPAD_AXIS_RIGHTY: return "right_y";
    case SDL_GAMEPAD_AXIS_LEFTX: return "left_x";
    default: return "left_y";
    }
}

void describe(Report& r, SDL_Gamepad* pad)
{
    const SDL_JoystickConnectionState conn = SDL_GetGamepadConnectionState(pad);
    r.line(fmt("gamepad: \"%s\" type %s  %04x:%04x  %s  steam_handle %llu", SDL_GetGamepadName(pad),
               SDL_GetGamepadStringForType(SDL_GetGamepadType(pad)), SDL_GetGamepadVendor(pad),
               SDL_GetGamepadProduct(pad),
               conn == SDL_JOYSTICK_CONNECTION_WIRED      ? "wired"
               : conn == SDL_JOYSTICK_CONNECTION_WIRELESS ? "wireless"
                                                          : "connection unknown",
               static_cast<unsigned long long>(SDL_GetGamepadSteamHandle(pad))));
    if (const char* path = SDL_GetGamepadPath(pad)) r.line(std::string("    path ") + path);
    for (SDL_SensorType type : {SDL_SENSOR_GYRO, SDL_SENSOR_ACCEL}) {
        const bool has = SDL_GamepadHasSensor(pad, type);
        if (has) SDL_SetGamepadSensorEnabled(pad, type, true);
        r.line(fmt("    %s: %s  rate %.1f Hz", type == SDL_SENSOR_GYRO ? "gyro" : "accel", has ? "YES" : "no",
                   has ? SDL_GetGamepadSensorDataRate(pad, type) : 0.f));
    }
}

int run_sdl(Report& r, Recorder& rec)
{
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    SDL_SetHint("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD", "1"); // show Steam's virtual pad too
    if (!SDL_Init(SDL_INIT_GAMEPAD)) {
        r.line(std::string("SDL_Init failed: ") + SDL_GetError());
        return 1;
    }
    std::map<SDL_JoystickID, SDL_Gamepad*> pads;
    float last_accel[3] = {0, 9.80665f, 0};
    const double waiting_since = host_now();
    std::printf("Aguardando controle... (conecte agora)\n");
    live("waiting for an SDL gamepad...");
    while (!rec.done(host_now())) {
        if (!rec.started() && host_now() - waiting_since > 60) {
            r.line("no gamepad within 60 s");
            break;
        }
        if (rec.started()) {
            rec.prompt(host_now());
            rec.status(host_now());
        }
        SDL_Event ev;
        if (!SDL_WaitEventTimeout(&ev, 20)) continue;
        const double host = host_now();
        switch (ev.type) {
        case SDL_EVENT_GAMEPAD_ADDED:
            if (SDL_Gamepad* pad = SDL_OpenGamepad(ev.gdevice.which)) {
                pads[ev.gdevice.which] = pad;
                describe(r, pad);
                rec.event(fmt("ADDED id %u \"%s\"", ev.gdevice.which, SDL_GetGamepadName(pad)), host);
            }
            break;
        case SDL_EVENT_GAMEPAD_REMOVED:
            rec.event(fmt("REMOVED id %u", ev.gdevice.which), host);
            if (pads.count(ev.gdevice.which)) SDL_CloseGamepad(pads[ev.gdevice.which]);
            pads.erase(ev.gdevice.which);
            break;
        case SDL_EVENT_GAMEPAD_AXIS_MOTION:
            rec.axis(axis_name(ev.gaxis.axis), ev.gaxis.value, host);
            break;
        case SDL_EVENT_GAMEPAD_SENSOR_UPDATE:
            if (ev.gsensor.sensor == SDL_SENSOR_ACCEL) {
                std::memcpy(last_accel, ev.gsensor.data, sizeof last_accel);
            } else if (ev.gsensor.sensor == SDL_SENSOR_GYRO) {
                rec.sample(gyro::from_sdl(ev.gsensor.sensor_timestamp, ev.gsensor.data, last_accel), host);
            }
            break;
        default:
            break;
        }
    }
    rec.summarize(r, true);
    for (auto& [id, pad] : pads) SDL_CloseGamepad(pad);
    SDL_Quit();
    return 0;
}

// ---------------------------------------------------------------- steam

// Steam routes a controller to the app whose window has focus, so the Steam pass needs a real
// foreground window of its own (a console window belongs to conhost/Terminal, not to us).
Recorder* g_focus_rec = nullptr;

LRESULT CALLBACK focus_wnd_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_KEYDOWN && wp == VK_RETURN && g_focus_rec) {
        g_focus_rec->next_step();
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

HWND make_focus_window(Recorder& rec)
{
    g_focus_rec = &rec;
    WNDCLASSW wc{};
    wc.lpfnWndProc = focus_wnd_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"ttmax-diag-focus";
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    RegisterClassW(&wc);
    HWND hwnd = CreateWindowExW(0, wc.lpszClassName,
                                L"ttmax-diag  |  Steam Input as Borderlands 4  |  KEEP THIS WINDOW FOCUSED - Enter = next step",
                                WS_OVERLAPPEDWINDOW | WS_VISIBLE, CW_USEDEFAULT, CW_USEDEFAULT, 1000, 160, nullptr, nullptr,
                                wc.hInstance, nullptr);
    SetForegroundWindow(hwnd);
    return hwnd;
}

void pump_messages()
{
    MSG msg;
    while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
}

int run_steam(Report& r, Recorder& rec, const Options& opt)
{
    steam::Input input;
    std::string error;
    if (!input.open(opt.steam_dll.c_str(), true, error)) {
        r.line("steam: " + error);
        return 1;
    }
    timeBeginPeriod(1);
    const HWND focus = make_focus_window(rec);
    std::printf("Steam Input aberto como Borderlands 4. Clique na janela ttmax-diag e mantenha-a em foco.\n");
    live("Steam Input opened as Borderlands 4, waiting for a controller (focus window created)...");
    steam::Handle active = 0;
    steam::MotionData prev{};
    const double waiting_since = host_now();
    double last_wait_log = 0;
    int polls = 0;
    while (!rec.done(host_now())) {
        if (!rec.started() && host_now() - waiting_since > 120) {
            r.line("no Steam Input controller within 120 s");
            break;
        }
        pump_messages();
        const std::vector<steam::Handle> handles = input.controllers();
        ++polls;
        const double host = host_now();
        if (!active && host - last_wait_log >= 5) {
            live(fmt("steam: %zu controllers connected after %d polls, focus window %s", handles.size(), polls,
                     GetForegroundWindow() == focus ? "FOREGROUND" : "not foreground"));
            last_wait_log = host;
        }
        const bool still_there = std::find(handles.begin(), handles.end(), active) != handles.end();
        if (active && !still_there) {
            rec.event(fmt("REMOVED handle %llu", static_cast<unsigned long long>(active)), host);
            active = 0;
        }
        if (!active && !handles.empty()) {
            active = handles.front();
            r.line(fmt("steam controller: handle %llu type %d (%s), %zu connected",
                       static_cast<unsigned long long>(active), input.type(active), steam::type_name(input.type(active)),
                       handles.size()));
            if (!rec.started()) rec.start(host);
            rec.event(fmt("ADDED handle %llu", static_cast<unsigned long long>(active)), host);
        }
        if (active) {
            rec.prompt(host);
            rec.status(host);
            const steam::MotionData m = input.motion(active);
            if (steam::has_data(m) && std::memcmp(&m, &prev, sizeof m) != 0) { // a new hardware packet
                prev = m;
                rec.sample(gyro::from_steam(host, m.rot_vel, m.pos_accel), host);
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    timeEndPeriod(1);
    DestroyWindow(focus);
    r.line(fmt("steam polls: %d", polls));
    rec.summarize(r, false);
    input.close();
    return 0;
}

} // namespace

int main(int argc, char** argv)
{
    SetConsoleOutputCP(CP_UTF8);
    if (argc < 2) {
        std::printf("usage: ttmax-diag hid|sdl|steam [--seconds N] [--rest N] [--label NAME] [--steam-dll PATH]\n");
        return 2;
    }
    const std::string cmd = argv[1];
    Options opt;
    for (int i = 2; i + 1 < argc; i += 2) {
        const std::string key = argv[i];
        if (key == "--seconds") opt.seconds = std::atof(argv[i + 1]);
        else if (key == "--rest") opt.rest_only = std::atof(argv[i + 1]);
        else if (key == "--label") opt.label = argv[i + 1];
        else if (key == "--steam-dll") {
            const std::string s = argv[i + 1];
            opt.steam_dll.assign(s.begin(), s.end());
        }
    }

    Report report;
    FILE* csv = nullptr;
    CreateDirectoryW(L"evidence", nullptr);
    if (cmd != "hid") g_live = std::fopen("evidence/live.log", "a");
    if (!opt.label.empty()) {
        report.txt = std::fopen(("evidence/A-" + opt.label + ".txt").c_str(), "w");
        if (cmd != "hid") {
            csv = std::fopen(("evidence/A-" + opt.label + ".csv").c_str(), "w");
            if (csv) std::fprintf(csv, "elapsed_s,segment,sample_t_s,gyro_pitch_dps,gyro_yaw_dps,gyro_roll_dps,accel_x_g,accel_y_g,accel_z_g\n");
        }
    }
    const auto stamp = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    char when[64];
    std::strftime(when, sizeof when, "%Y-%m-%d %H:%M:%S", std::localtime(&stamp));
    report.line(fmt("=== ttmax-diag %s  label %s  %s  SDL %d.%d.%d", cmd.c_str(),
                    opt.label.empty() ? "-" : opt.label.c_str(), when, SDL_VERSIONNUM_MAJOR(SDL_GetVersion()),
                    SDL_VERSIONNUM_MINOR(SDL_GetVersion()), SDL_VERSIONNUM_MICRO(SDL_GetVersion())));

    Recorder rec(csv, opt);
    if (cmd != "hid" && opt.rest_only == 0) // Enter advances the guided steps
        std::thread([&rec] {
            for (std::string line; std::getline(std::cin, line);) rec.next_step();
        }).detach();
    int rc = 2;
    if (cmd == "hid") rc = run_hid(report);
    else if (cmd == "sdl") rc = run_sdl(report, rec);
    else if (cmd == "steam") rc = run_steam(report, rec, opt);
    else std::printf("unknown command %s\n", cmd.c_str());

    live(fmt("--- ttmax-diag %s finished (rc %d)", cmd.c_str(), rc));
    if (csv) std::fclose(csv);
    if (report.txt) std::fclose(report.txt);
    if (g_live) std::fclose(g_live);
    return rc;
}
