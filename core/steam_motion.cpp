#include "steam_motion.hpp"

#include <windows.h>

namespace steam {

namespace {
constexpr int kMaxControllers = 16; // STEAM_INPUT_MAX_COUNT

template <typename T> bool resolve(HMODULE module, const char* name, T& out, std::string& missing)
{
    out = reinterpret_cast<T>(GetProcAddress(module, name));
    if (!out) missing += std::string(missing.empty() ? "" : ", ") + name;
    return out != nullptr;
}
} // namespace

bool Input::open(const wchar_t* dll_path, bool init_api, std::string& error)
{
    HMODULE module = GetModuleHandleW(L"steam_api64.dll");
    if (!module && dll_path) module = LoadLibraryW(dll_path);
    if (!module) {
        error = "steam_api64.dll not loaded and could not be loaded (error " + std::to_string(GetLastError()) + ")";
        return false;
    }

    void* (*accessor)() = nullptr;
    bool (*api_init)() = nullptr;
    std::string missing;
    resolve(module, "SteamAPI_SteamInput_v006", accessor, missing);
    resolve(module, "SteamAPI_ISteamInput_Init", init_, missing);
    resolve(module, "SteamAPI_ISteamInput_Shutdown", shutdown_, missing);
    resolve(module, "SteamAPI_ISteamInput_RunFrame", run_frame_, missing);
    resolve(module, "SteamAPI_ISteamInput_GetConnectedControllers", connected_, missing);
    resolve(module, "SteamAPI_ISteamInput_GetInputTypeForHandle", type_, missing);
    resolve(module, "SteamAPI_ISteamInput_GetMotionData", motion_, missing);
    origin_from_xbox_ = reinterpret_cast<decltype(origin_from_xbox_)>(
        GetProcAddress(module, "SteamAPI_ISteamInput_GetActionOriginFromXboxOrigin"));
    if (init_api) {
        resolve(module, "SteamAPI_Init", api_init, missing);
        resolve(module, "SteamAPI_Shutdown", api_shutdown_, missing);
        resolve(module, "SteamAPI_RunCallbacks", run_callbacks_, missing);
    }
    if (!missing.empty()) {
        error = "steam_api64.dll lacks exports: " + missing;
        return false;
    }

    if (init_api) {
        SetEnvironmentVariableW(L"SteamAppId", L"1285190");
        SetEnvironmentVariableW(L"SteamGameId", L"1285190");
        if (!api_init()) {
            error = "SteamAPI_Init failed (Steam not running, or Borderlands 4 not owned by the logged-in user)";
            return false;
        }
        owns_api_ = true;
    }
    input_ = accessor();
    if (!input_) {
        error = "SteamAPI_SteamInput_v006 returned null (Steam API not initialised in this process)";
        close();
        return false;
    }
    init_(input_, true); // we call RunFrame ourselves
    return true;
}

void Input::close()
{
    if (input_) shutdown_(input_);
    input_ = nullptr;
    if (owns_api_) api_shutdown_();
    owns_api_ = false;
}

std::vector<Handle> Input::controllers()
{
    Handle handles[kMaxControllers] = {};
    if (owns_api_) run_callbacks_();
    run_frame_(input_, false);
    const int count = connected_(input_, handles);
    return {handles, handles + (count > 0 ? count : 0)};
}

int Input::type(Handle h) const { return type_(input_, h); }

int Input::origin_for_xbox(Handle h, int xbox_origin) const
{
    return origin_from_xbox_ ? origin_from_xbox_(input_, h, xbox_origin) : -1;
}

MotionData Input::motion(Handle h) const { return motion_(input_, h); }

const char* type_name(int t)
{
    static const char* const names[] = {"Unknown",          "SteamController", "XBox360",   "XBoxOne",
                                        "GenericGamepad",   "PS4",             "AppleMFi",  "AndroidController",
                                        "SwitchJoyConPair", "SwitchJoyConSingle", "SwitchProController",
                                        "MobileTouch",      "PS3",             "PS5",       "SteamDeckController"};
    return t >= 0 && t < static_cast<int>(std::size(names)) ? names[t] : "?";
}

const char* origin_label(int origin)
{
    // EInputActionOrigin is append-only; each controller lists A/B/X/Y (PlayStation: X/O/Triangle/Square), then
    // left/right bumper. Values from Steamworks' isteaminput.h.
    struct Run {
        int first;
        const char* labels[6];
    };
    static const Run runs[] = {
        {1, {"A", "B", "X", "Y", "LB", "RB"}},                // Steam Controller
        {50, {"X", "O", "Triangle", "Square", "L1", "R1"}},   // PS4
        {114, {"A", "B", "X", "Y", "LB", "RB"}},              // Xbox One
        {153, {"A", "B", "X", "Y", "LB", "RB"}},              // Xbox 360
        {192, {"A", "B", "X", "Y", "L", "R"}},                // Switch Pro / Joy-Cons
        {258, {"X", "O", "Triangle", "Square", "L1", "R1"}},  // PS5
        {333, {"A", "B", "X", "Y", "L1", "R1"}},              // Steam Deck
        {495, {"A", "B", "X", "Y", "L", "R"}},                // Switch 2
        {542, {"A", "B", "X", "Y", "L1", "R1"}},              // Steam Controller (2026)
    };
    for (const Run& r : runs)
        if (origin >= r.first && origin < r.first + 6) return r.labels[origin - r.first];
    return nullptr;
}

} // namespace steam
