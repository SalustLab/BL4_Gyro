// Gyro core: sensor samples -> calibrated controller rotation -> camera deltas.
// Axis convention is SDL's: X right, Y up, Z toward the player; rotation counter-clockwise positive.
#pragma once

#include <cstdint>
#include <mutex>

#include "GamepadMotion.hpp"

namespace gyro {

struct Sample {
    double t_s = 0;              // sample time in seconds (sensor clock, or host clock for Steam)
    float gyro_dps[3] = {};      // pitch (X), yaw (Y), roll (Z) in degrees/second
    float accel_g[3] = {};       // acceleration including gravity, in g
};

// SDL3 gamepad sensors: gyro in rad/s, accel in m/s^2, timestamp in ns.
Sample from_sdl(std::uint64_t sensor_ns, const float gyro_rad[3], const float accel_ms2[3]);

// Steam Input InputMotionData_t: rotVel{X pitch, Y roll, Z yaw} and posAccel{X right, Y forward, Z up},
// both int16-scaled (+-2000 dps, +-2 g). Steam has no sensor clock, so the caller passes host time.
// Axis signs were checked against SDL on the same controller (evidence/A-switch-steam-api.*).
Sample from_steam(double host_s, const float rot_vel[3], const float pos_accel[3]);

enum class Space { Local, Player };

struct Settings {
    Space space = Space::Player;
    bool auto_calibrate = true; // GamepadMotionHelpers Stillness; the mod enables it only while the game gate is closed
    float tighten_dps = 0;      // below this speed output is scaled down linearly (0 = off)
    float smooth_dps = 0;       // tiered smoothing: fully smoothed below half of this, direct above (0 = off)
};

// Controller rotation in degrees, camera convention: yaw right positive, pitch up positive.
struct Delta {
    double yaw_deg = 0;
    double pitch_deg = 0;
};

// Outcome of the last manual calibration. Moved / NotFlat keep the previous offset: a calibration only counts when
// the controller lies flat and still (in the hand, slow drift looks like bias and becomes camera drift).
enum class Calibration { None, Running, Ok, Moved, NotFlat };

// One per controller. Integrates each sample over its own interval (sensor time), so the
// result does not depend on how often the game consumes it.
class Processor {
public:
    explicit Processor(const Settings& settings = {});
    void configure(const Settings& settings);
    Delta process(const Sample& s); // rotation since the previous sample; zero across gaps
    Delta rate() const { return rate_; } // angular velocity of the last processed sample (deg/s, camera convention)
    void reset();
    // Manual calibration: the controller must be still; output is muted while it runs. If it moved, the previous
    // offset is kept and the result is Moved.
    void calibrate(double seconds);
    bool calibrating() const { return calibration_left_s_ > 0; }
    bool auto_calibrating() const { return settings_.auto_calibrate && !calibrating(); }
    Calibration calibration() const { return calibration_; }
    void calibration_offset(float out[3]); // gyro bias being subtracted, deg/s (SDL axes)
    double calibration_progress() const; // 0..1 of sensor time collected; 1 once finished

private:
    void apply_calibration_mode();

    GamepadMotion motion_;
    Settings settings_;
    double calibration_left_s_ = 0, calibration_total_s_ = 0;
    Calibration calibration_ = Calibration::None;
    float previous_offset_[3] = {};
    float raw_min_[3] = {}, raw_max_[3] = {};
    double accel_sum_[3] = {};
    float smoothed_[2] = {};
    Delta rate_;
    double prev_t_ = 0;
    bool has_prev_ = false;
};

// Hand-off from the sensor thread to the game thread: the latest calibrated angular velocity (deg/s, camera
// convention), integrated forward in time whenever the game takes. In game Steam updates motion ~48 times/s with
// a 40-60 ms gap about twice a second while frames run at ~49-53/s; integrating the held rate at frame time keeps
// every frame moving (no empty frames, no catch-up bursts) and adds no latency. A rate is held for at most
// kHoldS after its update, so a stalled or unfocused controller stops the camera.
class RateHold {
public:
    static constexpr double kHoldS = 0.1;
    void set(const Delta& rate_dps, double t_s); // sensor thread, at packet arrival
    Delta take(double now_s);                   // game thread: rotation since the previous take
private:
    void advance(double t_s);
    std::mutex mutex_;
    Delta rate_, pending_;
    double t_rate_ = 0, t_mark_ = 0;
};

struct Camera {
    double sens_x = 2.0;          // camera degrees per controller degree
    double sens_y = 2.0;
    double ads_multiplier = 1.0;
    bool invert_x = false;
    bool invert_y = false;
};

Delta to_camera(const Delta& controller, const Camera& camera, bool ads);

} // namespace gyro
