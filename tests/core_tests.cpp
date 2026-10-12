// Behaviour tests for the gyro core. Plain asserts; run by CTest.
#include "gyro.hpp"

#include <cmath>
#include <cstdio>
#include <thread>
#include <vector>

static int failures = 0;
#define CHECK(cond)                                                                 \
    do {                                                                            \
        if (!(cond)) {                                                              \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);             \
            ++failures;                                                             \
        }                                                                           \
    } while (0)

static bool near(double a, double b, double eps = 1e-4) { return std::fabs(a - b) <= eps; }

static void sdl_sample_is_converted_to_degrees_and_g()
{
    const float gyro_rad[3] = {0.5f, 3.14159265f, -1.0f};
    const float accel_ms2[3] = {0.f, 9.80665f, 0.f};
    const gyro::Sample s = gyro::from_sdl(2'000'000'000ull, gyro_rad, accel_ms2);
    CHECK(near(s.t_s, 2.0));
    CHECK(near(s.gyro_dps[0], 28.6479, 1e-3));
    CHECK(near(s.gyro_dps[1], 180.0, 1e-3));
    CHECK(near(s.gyro_dps[2], -57.2958, 1e-3));
    CHECK(near(s.accel_g[1], 1.0));
}

static void steam_sample_is_scaled_and_remapped_to_sdl_axes()
{
    // Steam: X right, Y forward, Z up (sticks to the sky); int16 range = +-2000 dps / +-2 g.
    const float rot_vel[3] = {16384.f, 8192.f, -32768.f}; // pitch, roll, yaw
    const float pos_accel[3] = {0.f, 0.f, 16384.f};        // lying flat: gravity reaction on +Z
    const gyro::Sample s = gyro::from_steam(1.5, rot_vel, pos_accel);
    CHECK(near(s.t_s, 1.5));
    CHECK(near(s.gyro_dps[0], 1000.0));  // pitch
    CHECK(near(s.gyro_dps[1], -2000.0)); // yaw = Steam Z
    CHECK(near(s.gyro_dps[2], 500.0));   // roll: same sign as SDL, measured (rest bias -0.38 SDL vs +0.41 Steam before fix)
    CHECK(near(s.accel_g[0], 0.0));
    CHECK(near(s.accel_g[1], 1.0));      // SDL up = Steam Z
    CHECK(near(s.accel_g[2], 0.0));
}

// Controller lying flat (gravity reaction on +Y), turning at a constant rate.
static gyro::Sample flat_sample(double t, float pitch_dps, float yaw_dps)
{
    gyro::Sample s;
    s.t_s = t;
    s.gyro_dps[0] = pitch_dps;
    s.gyro_dps[1] = yaw_dps;
    s.accel_g[1] = 1.f;
    return s;
}

// Local space, no auto-calibration: pure integration, no gravity estimate involved.
static gyro::Settings plain_settings()
{
    gyro::Settings settings;
    settings.space = gyro::Space::Local;
    settings.auto_calibrate = false;
    return settings;
}

static void constant_rate_over_irregular_samples_integrates_exactly()
{
    gyro::Processor p(plain_settings());
    const double steps[] = {0.003, 0.005, 0.007, 0.0045};
    double t = 10.0, yaw = 0, pitch = 0;
    p.process(flat_sample(t, 30.f, -90.f)); // first sample has no interval
    for (int i = 0; t < 11.0 - 1e-9; ++i) {
        t += steps[i % 4];
        const gyro::Delta d = p.process(flat_sample(t, 30.f, -90.f)); // clockwise from above = turn right
        yaw += d.yaw_deg;
        pitch += d.pitch_deg;
    }
    const double elapsed = t - 10.0;
    CHECK(near(yaw, 90.0 * elapsed, 1e-3));   // yaw right positive
    CHECK(near(pitch, 30.0 * elapsed, 1e-3)); // pitch up positive
}

static void player_space_recovers_world_turn_with_tilted_controller()
{
    // Controller pitched 45 deg up, turning right around the world vertical at 90 dps.
    const float c = 0.70710678f;
    auto tilted = [&](double t, float world_yaw_dps) {
        gyro::Sample s;
        s.t_s = t;
        s.gyro_dps[1] = world_yaw_dps * c;  // world up in local frame is (0, cos, -sin)
        s.gyro_dps[2] = -world_yaw_dps * c;
        s.accel_g[1] = c;
        s.accel_g[2] = -c;
        return s;
    };
    gyro::Settings settings;
    settings.auto_calibrate = false; // Player space is the default
    gyro::Processor player(settings);
    gyro::Processor local(plain_settings());
    double t = 0;
    for (; t < 5.0; t += 0.005) { player.process(tilted(t, 0.f)); local.process(tilted(t, 0.f)); }
    double yaw_player = 0, yaw_local = 0;
    for (int i = 0; i < 200; ++i, t += 0.005) {
        yaw_player += player.process(tilted(t, -90.f)).yaw_deg;
        yaw_local += local.process(tilted(t, -90.f)).yaw_deg;
    }
    CHECK(near(yaw_player, 90.0, 0.9));        // full world turn (1 s at 90 dps)
    CHECK(near(yaw_local, 90.0 * c, 0.9));     // local yaw axis only sees cos(45)
}

static void gaps_and_out_of_order_samples_are_not_integrated()
{
    gyro::Processor p(plain_settings());
    p.process(flat_sample(0.000, 0.f, -100.f));
    CHECK(near(p.process(flat_sample(0.010, 0.f, -100.f)).yaw_deg, 1.0));
    CHECK(near(p.process(flat_sample(0.500, 0.f, -100.f)).yaw_deg, 0.0)); // 490 ms stall
    CHECK(near(p.process(flat_sample(0.490, 0.f, -100.f)).yaw_deg, 0.0)); // clock went backwards
    CHECK(near(p.process(flat_sample(0.495, 0.f, -100.f)).yaw_deg, 0.5)); // resumes normally
}

static double consume_two_seconds_at(double frame_hz)
{
    // 200 Hz sensor at 45 dps for 2 s, drained by a game running at frame_hz.
    gyro::Processor p(plain_settings());
    gyro::Pacer pacer;
    double total = 0, next_frame = 1.0 / frame_hz;
    p.process(flat_sample(0.0, 0.f, -45.f));
    for (int i = 1; i <= 400; ++i) {
        const double t = i * 0.005;
        pacer.add(p.process(flat_sample(t, 0.f, -45.f)), t);
        while (next_frame <= t) { total += pacer.take(next_frame).yaw_deg; next_frame += 1.0 / frame_hz; }
    }
    return total + pacer.take(100.0).yaw_deg;
}

static void total_rotation_does_not_depend_on_frame_rate()
{
    CHECK(near(consume_two_seconds_at(30), 90.0, 1e-6));
    CHECK(near(consume_two_seconds_at(60), 90.0, 1e-6));
    CHECK(near(consume_two_seconds_at(144), 90.0, 1e-6));
}

static void pacer_is_safe_across_threads()
{
    gyro::Pacer pacer;
    double taken = 0;
    std::thread producer([&] { for (int i = 0; i < 100000; ++i) pacer.add({0.001, -0.002}, i * 1e-4); });
    for (int i = 0; i < 1000; ++i) taken += pacer.take(i * 0.01).yaw_deg;
    producer.join();
    taken += pacer.take(1e9).yaw_deg;
    CHECK(near(taken, 100.0, 1e-6));
}

// In game, Steam updates motion once per game frame (~48 Hz, evidence/C-trace-1.csv) while frames run at ~53 Hz:
// handing each packet to the next frame leaves ~40% of frames with no rotation (judder). Pacing spreads each
// packet over the packet interval.
static void paced_delivery_is_smooth_when_packets_and_frames_beat()
{
    gyro::Pacer pacer;
    const double rate = 90.0;
    double t_packet = 0, t_frame = 0, last_packet = 0;
    int n = 0;
    std::vector<double> frame_deltas;
    double total = 0;
    while (t_frame < 3.0) {
        if (t_packet <= t_frame) {
            pacer.add({rate * (t_packet - last_packet), 0}, t_packet);
            last_packet = t_packet;
            t_packet += 0.0206 + 0.001 * std::sin(1.7 * ++n); // +-1 ms arrival jitter
        } else {
            const double d = pacer.take(t_frame).yaw_deg;
            total += d;
            if (t_frame > 0.5) frame_deltas.push_back(d);
            t_frame += 1.0 / 53;
        }
    }
    total += pacer.take(10.0).yaw_deg; // everything is released eventually
    double mean = 0, var = 0;
    for (double d : frame_deltas) mean += d / frame_deltas.size();
    for (double d : frame_deltas) var += (d - mean) * (d - mean) / frame_deltas.size();
    const double cv = std::sqrt(var) / mean;
    std::printf("info: paced per-frame delta mean %.3f deg, coefficient of variation %.3f\n", mean, cv);
    CHECK(cv < 0.15);                              // unpaced: ~0.8 (40% empty frames)
    CHECK(near(total, rate * last_packet, 1e-6));  // nothing lost or duplicated
}

static void paced_delivery_releases_a_packet_within_one_interval()
{
    gyro::Pacer pacer;
    for (int i = 0; i <= 10; ++i) pacer.add({1.0, -0.5}, i * 0.02); // learns a ~20 ms packet interval
    pacer.take(0.2 + 1.0);                                            // drain
    pacer.add({4.0, 2.0}, 2.0);
    CHECK(near(pacer.take(2.0).yaw_deg, 0.0));
    const gyro::Delta half = pacer.take(2.01);
    CHECK(near(half.yaw_deg, 2.0, 1e-6) && near(half.pitch_deg, 1.0, 1e-6));
    const gyro::Delta rest = pacer.take(2.03);
    CHECK(near(rest.yaw_deg, 2.0, 1e-6) && near(rest.pitch_deg, 1.0, 1e-6));
}

static void camera_delta_applies_sensitivity_ads_and_inversion()
{
    gyro::Camera cam;
    cam.sens_x = 2.0;
    cam.sens_y = 1.5;
    cam.ads_multiplier = 0.5;
    const gyro::Delta hip = gyro::to_camera({1.0, 2.0}, cam, false);
    CHECK(near(hip.yaw_deg, 2.0) && near(hip.pitch_deg, 3.0));
    const gyro::Delta ads = gyro::to_camera({1.0, 2.0}, cam, true);
    CHECK(near(ads.yaw_deg, 1.0) && near(ads.pitch_deg, 1.5));
    cam.invert_y = true;
    const gyro::Delta inv = gyro::to_camera({1.0, 2.0}, cam, false);
    CHECK(near(inv.yaw_deg, 2.0) && near(inv.pitch_deg, -3.0));
}

// Still controller with a constant gyro bias plus deterministic noise (+-0.2 dps, +-0.005 g).
struct BiasedSensor {
    unsigned state = 12345;
    float noise(float amplitude)
    {
        state = state * 1664525u + 1013904223u;
        return amplitude * (static_cast<float>(state >> 8) / 8388608.f - 1.f);
    }
    gyro::Sample at(double t, float yaw_dps = 0.f)
    {
        gyro::Sample s;
        s.t_s = t;
        s.gyro_dps[0] = 1.5f + noise(0.2f);
        s.gyro_dps[1] = -2.0f + yaw_dps + noise(0.2f);
        s.gyro_dps[2] = 0.7f + noise(0.2f);
        s.accel_g[0] = noise(0.005f);
        s.accel_g[1] = 1.f + noise(0.005f);
        s.accel_g[2] = noise(0.005f);
        return s;
    }
};

static gyro::Delta run(gyro::Processor& p, BiasedSensor& sensor, double& t, double seconds, float yaw_dps = 0.f)
{
    gyro::Delta sum;
    for (const double end = t + seconds; t < end; t += 0.005) {
        const gyro::Delta d = p.process(sensor.at(t, yaw_dps));
        sum.yaw_deg += d.yaw_deg;
        sum.pitch_deg += d.pitch_deg;
    }
    return sum;
}

static void auto_calibration_removes_bias_at_rest_but_keeps_real_turns()
{
    gyro::Processor p; // defaults: Player space + auto calibration
    BiasedSensor sensor;
    double t = 0;
    run(p, sensor, t, 6.0); // left on the table
    const gyro::Delta rest = run(p, sensor, t, 2.0);
    CHECK(std::fabs(rest.yaw_deg) < 0.2 && std::fabs(rest.pitch_deg) < 0.2);
    const gyro::Delta turn = run(p, sensor, t, 1.0, -60.f); // turn right 60 deg
    CHECK(near(turn.yaw_deg, 60.0, 1.2));
}

// In-game symptom "slow rotation feels stuck": auto-calibration must not run while the player is aiming.
static void slow_pan_is_kept_while_auto_calibration_is_suspended()
{
    gyro::Settings gameplay;
    gameplay.auto_calibrate = false; // what the mod sets while the gate is open (gameplay)
    gyro::Processor p(gameplay);
    BiasedSensor sensor;
    double t = 0;
    p.calibrate(2.0);
    run(p, sensor, t, 2.1); // calibrated on the desk first
    const gyro::Delta pan = run(p, sensor, t, 8.0, -3.f); // 3 dps slow pan right for 8 s
    CHECK(near(pan.yaw_deg, 24.0, 0.5));

    gyro::Processor always_auto; // auto-calibration left running during gameplay (the bug)
    BiasedSensor sensor2;
    double t2 = 0;
    run(always_auto, sensor2, t2, 6.0);
    const gyro::Delta eaten = run(always_auto, sensor2, t2, 8.0, -3.f);
    std::printf("info: slow 24 deg pan with auto-calibration always on -> %.1f deg\n", eaten.yaw_deg);
}

static void manual_calibration_measures_bias_and_mutes_output_meanwhile()
{
    gyro::Processor p(plain_settings());
    BiasedSensor sensor;
    double t = 0;
    const gyro::Delta drifting = run(p, sensor, t, 1.0);
    CHECK(near(drifting.yaw_deg, 2.0, 0.1)); // uncalibrated: -2 dps bias -> drifts right
    p.calibrate(2.0);
    CHECK(p.calibrating());
    const gyro::Delta during = run(p, sensor, t, 2.0);
    CHECK(near(during.yaw_deg, 0.0) && near(during.pitch_deg, 0.0));
    run(p, sensor, t, 0.05);
    CHECK(!p.calibrating());
    const gyro::Delta after = run(p, sensor, t, 2.0);
    CHECK(std::fabs(after.yaw_deg) < 0.1 && std::fabs(after.pitch_deg) < 0.1);
}

static double yaw_over(gyro::Processor& p, double& t, double seconds, float yaw_dps)
{
    double yaw = 0;
    for (const double end = t + seconds; t < end - 1e-9;) {
        t += 0.005;
        yaw += p.process(flat_sample(t, 0.f, yaw_dps)).yaw_deg;
    }
    return yaw;
}

static void tightening_slows_tiny_motion_and_leaves_big_motion_alone()
{
    gyro::Settings settings = plain_settings();
    settings.tighten_dps = 4.f;
    gyro::Processor p(settings);
    double t = 0;
    p.process(flat_sample(t, 0.f, 0.f));
    CHECK(near(yaw_over(p, t, 1.0, -2.f), 1.0, 1e-3));   // 2 dps * (2/4)
    CHECK(near(yaw_over(p, t, 1.0, -10.f), 10.0, 1e-3)); // above threshold: untouched
}

static void tiered_smoothing_keeps_big_motion_and_calms_jitter()
{
    gyro::Settings settings = plain_settings();
    settings.smooth_dps = 5.f;
    gyro::Processor smooth(settings);
    double t = 0;
    smooth.process(flat_sample(t, 0.f, 0.f));
    CHECK(near(yaw_over(smooth, t, 1.0, -20.f), 20.0, 1e-3)); // above threshold: direct
    yaw_over(smooth, t, 1.0, -1.f);                            // settle on a slow pan
    CHECK(near(yaw_over(smooth, t, 1.0, -1.f), 1.0, 1e-3));   // steady slow motion is not lost

    gyro::Processor calm(settings), raw(plain_settings());
    double peak_raw = 0, peak_smooth = 0, t2 = t;
    calm.process(flat_sample(t, 0.f, 0.f));
    raw.process(flat_sample(t2, 0.f, 0.f));
    for (int i = 0; i < 200; ++i) { // hand tremor: +-2 dps flipping every sample
        t += 0.005;
        t2 += 0.005;
        const float jitter = (i % 2) ? 2.f : -2.f;
        peak_smooth = std::fmax(peak_smooth, std::fabs(calm.process(flat_sample(t, 0.f, jitter)).yaw_deg));
        peak_raw = std::fmax(peak_raw, std::fabs(raw.process(flat_sample(t2, 0.f, jitter)).yaw_deg));
    }
    CHECK(peak_smooth < peak_raw / 4);
}

int main()
{
    sdl_sample_is_converted_to_degrees_and_g();
    steam_sample_is_scaled_and_remapped_to_sdl_axes();
    constant_rate_over_irregular_samples_integrates_exactly();
    player_space_recovers_world_turn_with_tilted_controller();
    gaps_and_out_of_order_samples_are_not_integrated();
    total_rotation_does_not_depend_on_frame_rate();
    pacer_is_safe_across_threads();
    camera_delta_applies_sensitivity_ads_and_inversion();
    paced_delivery_is_smooth_when_packets_and_frames_beat();
    paced_delivery_releases_a_packet_within_one_interval();
    auto_calibration_removes_bias_at_rest_but_keeps_real_turns();
    manual_calibration_measures_bias_and_mutes_output_meanwhile();
    slow_pan_is_kept_while_auto_calibration_is_suspended();
    tightening_slows_tiny_motion_and_leaves_big_motion_alone();
    tiered_smoothing_keeps_big_motion_and_calms_jitter();
    if (failures) return 1;
    std::puts("all core tests passed");
    return 0;
}
