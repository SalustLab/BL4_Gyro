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
Sample from_steam(double host_s, const float rot_vel[3], const float pos_accel[3]);

enum class Space { Local, Player };

struct Settings {
    Space space = Space::Player;
    bool auto_calibrate = true; // GamepadMotionHelpers Stillness|SensorFusion
    float tighten_dps = 0;      // below this speed output is scaled down linearly (0 = off)
    float smooth_dps = 0;       // tiered smoothing: fully smoothed below half of this, direct above (0 = off)
};

// Controller rotation in degrees, camera convention: yaw right positive, pitch up positive.
struct Delta {
    double yaw_deg = 0;
    double pitch_deg = 0;
};

// One per controller. Integrates each sample over its own interval (sensor time), so the
// result does not depend on how often the game consumes it.
class Processor {
public:
    explicit Processor(const Settings& settings = {});
    void configure(const Settings& settings);
    Delta process(const Sample& s); // rotation since the previous sample; zero across gaps
    void reset();
    // Manual calibration: the controller must be still; output is muted while it runs.
    void calibrate(double seconds);
    bool calibrating() const { return calibration_left_s_ > 0; }

private:
    void apply_calibration_mode();

    GamepadMotion motion_;
    Settings settings_;
    double calibration_left_s_ = 0;
    float smoothed_[2] = {};
    double prev_t_ = 0;
    bool has_prev_ = false;
};

// Sensor thread adds, game thread takes once per frame.
class Accumulator {
public:
    void add(const Delta& d);
    Delta take(); // returns everything added since the last take
private:
    std::mutex mutex_;
    Delta sum_;
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
