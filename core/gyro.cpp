#include "gyro.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <utility>

namespace gyro {

namespace {
constexpr float kRadToDeg = 180.0f / std::numbers::pi_v<float>;
constexpr float kStandardGravity = 9.80665f;
constexpr float kSteamDpsPerUnit = 2000.0f / 32768.0f;
constexpr float kSteamGPerUnit = 2.0f / 32768.0f;
constexpr double kMaxGapS = 0.1;       // longer gaps (stall, reconnect) are not integrated
constexpr float kYawRelaxFactor = 1.41f; // GyroWiki default for Player Space
constexpr double kSmoothTimeS = 0.1;     // time constant of the smoothed tier
} // namespace

Sample from_sdl(std::uint64_t sensor_ns, const float gyro_rad[3], const float accel_ms2[3])
{
    Sample s;
    s.t_s = static_cast<double>(sensor_ns) * 1e-9;
    for (int i = 0; i < 3; ++i) {
        s.gyro_dps[i] = gyro_rad[i] * kRadToDeg;
        s.accel_g[i] = accel_ms2[i] / kStandardGravity;
    }
    return s;
}

Sample from_steam(double host_s, const float rot_vel[3], const float pos_accel[3])
{
    Sample s;
    s.t_s = host_s;
    s.gyro_dps[0] = rot_vel[0] * kSteamDpsPerUnit;
    s.gyro_dps[1] = rot_vel[2] * kSteamDpsPerUnit;
    s.gyro_dps[2] = rot_vel[1] * kSteamDpsPerUnit; // measured on TT Max: Steam roll already matches SDL's sign
    s.accel_g[0] = pos_accel[0] * kSteamGPerUnit;
    s.accel_g[1] = pos_accel[2] * kSteamGPerUnit;
    s.accel_g[2] = -pos_accel[1] * kSteamGPerUnit;
    return s;
}

Processor::Processor(const Settings& settings) { configure(settings); }

void Processor::configure(const Settings& settings)
{
    settings_ = settings;
    if (!calibrating()) apply_calibration_mode();
}

void Processor::apply_calibration_mode()
{
    using namespace GamepadMotionHelpers;
    // Stillness only: SensorFusion corrects pitch/roll bias from the accelerometer, which hand motion and the
    // TT Max's ~9% accel scale error can skew (in-game symptom: aim slowly creeping up).
    motion_.SetCalibrationMode(settings_.auto_calibrate ? Stillness : Manual);
}

void Processor::calibrate(double seconds)
{
    calibration_left_s_ = seconds;
    motion_.SetCalibrationMode(GamepadMotionHelpers::Manual);
    motion_.ResetContinuousCalibration();
    motion_.StartContinuousCalibration();
}

Delta Processor::process(const Sample& s)
{
    const double dt = s.t_s - prev_t_;
    const bool valid = has_prev_ && dt > 0 && dt <= kMaxGapS;
    prev_t_ = s.t_s;
    has_prev_ = true;
    rate_ = {};
    if (!valid) return {};

    motion_.ProcessMotion(s.gyro_dps[0], s.gyro_dps[1], s.gyro_dps[2], s.accel_g[0], s.accel_g[1],
                          s.accel_g[2], static_cast<float>(dt));
    if (calibrating()) {
        calibration_left_s_ -= dt;
        if (!calibrating()) {
            motion_.PauseContinuousCalibration();
            apply_calibration_mode();
        }
        return {};
    }
    float pitch = 0, yaw = 0, roll = 0; // counter-clockwise positive, dps
    if (settings_.space == Space::Player)
        motion_.GetPlayerSpaceGyro(pitch, yaw, kYawRelaxFactor);
    else
        motion_.GetCalibratedGyro(pitch, yaw, roll);

    const float speed = std::hypot(pitch, yaw);
    if (settings_.smooth_dps > 0) { // GyroWiki tiered smoothing, time-based so it is rate independent
        const float alpha = static_cast<float>(-std::expm1(-dt / kSmoothTimeS));
        smoothed_[0] += (pitch - smoothed_[0]) * alpha;
        smoothed_[1] += (yaw - smoothed_[1]) * alpha;
        const float low = settings_.smooth_dps / 2;
        const float direct = std::clamp((speed - low) / (settings_.smooth_dps - low), 0.f, 1.f);
        pitch = pitch * direct + smoothed_[0] * (1 - direct);
        yaw = yaw * direct + smoothed_[1] * (1 - direct);
    }
    if (settings_.tighten_dps > 0 && speed < settings_.tighten_dps) {
        const float scale = speed / settings_.tighten_dps;
        pitch *= scale;
        yaw *= scale;
    }
    rate_ = {-yaw, pitch};
    return {rate_.yaw_deg * dt, rate_.pitch_deg * dt};
}

void Processor::reset()
{
    has_prev_ = false;
    rate_ = {};
    smoothed_[0] = smoothed_[1] = 0;
    motion_.ResetMotion();
}

void RateHold::advance(double t_s)
{
    const double until = std::min(t_s, t_rate_ + kHoldS);
    if (until > t_mark_) {
        pending_.yaw_deg += rate_.yaw_deg * (until - t_mark_);
        pending_.pitch_deg += rate_.pitch_deg * (until - t_mark_);
    }
    t_mark_ = std::max(t_mark_, t_s);
}

void RateHold::set(const Delta& rate_dps, double t_s)
{
    std::lock_guard lock(mutex_);
    advance(t_s); // never moves t_mark_ back: a late-stamped update must not re-count time already taken
    rate_ = rate_dps;
    t_rate_ = t_s;
}

Delta RateHold::take(double now_s)
{
    std::lock_guard lock(mutex_);
    advance(now_s);
    return std::exchange(pending_, Delta{});
}

Delta to_camera(const Delta& controller, const Camera& camera, bool ads)
{
    const double scale = ads ? camera.ads_multiplier : 1.0;
    return {controller.yaw_deg * camera.sens_x * scale * (camera.invert_x ? -1 : 1),
            controller.pitch_deg * camera.sens_y * scale * (camera.invert_y ? -1 : 1)};
}

} // namespace gyro
