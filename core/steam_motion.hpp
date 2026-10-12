// ISteamInput motion through steam_api64's flat C exports (no Steamworks SDK needed).
// In the game the DLL is already loaded and initialised by the game; the diagnostic tool loads
// the game's own copy and initialises it as Borderlands 4 (app 1285190) so Steam applies BL4's
// Steam Input configuration.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace steam {

// Layout of InputMotionData_t (Steamworks docs): quaternion, positional accel, angular velocity.
struct MotionData {
    float rot_quat[4];
    float pos_accel[3];
    float rot_vel[3];
};

using Handle = std::uint64_t;

class Input {
public:
    // dll_path is only used when steam_api64.dll is not loaded yet; init_api calls SteamAPI_Init.
    bool open(const wchar_t* dll_path, bool init_api, std::string& error);
    void close();
    bool is_open() const { return input_ != nullptr; }
    std::vector<Handle> controllers(); // also pumps Steam Input (RunFrame)
    int type(Handle h) const;          // ESteamInputType
    MotionData motion(Handle h) const;

private:
    void* input_ = nullptr;
    bool owns_api_ = false;
    bool (*init_)(void*, bool) = nullptr;
    bool (*shutdown_)(void*) = nullptr;
    void (*run_frame_)(void*, bool) = nullptr;
    int (*connected_)(void*, Handle*) = nullptr;
    int (*type_)(void*, Handle) = nullptr;
    MotionData (*motion_)(void*, Handle) = nullptr;
    void (*api_shutdown_)() = nullptr;
};

const char* type_name(int steam_input_type);

} // namespace steam
