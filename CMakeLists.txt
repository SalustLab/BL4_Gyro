cmake_minimum_required(VERSION 3.24)
project(bl4_native_gyro LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Static CRT: the DLL lives inside the game process and must not depend on a VC redist version.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
add_compile_options(/W4 /permissive- /utf-8 /EHsc)
add_compile_definitions(NOMINMAX WIN32_LEAN_AND_MEAN _CRT_SECURE_NO_WARNINGS)

add_library(gyro_core STATIC core/gyro.cpp core/steam_motion.cpp)
target_include_directories(gyro_core PUBLIC core)
target_include_directories(gyro_core SYSTEM PUBLIC third_party/GamepadMotionHelpers)

enable_testing()
add_executable(core_tests tests/core_tests.cpp)
target_link_libraries(core_tests PRIVATE gyro_core)
add_test(NAME core_tests COMMAND core_tests)

# SDL3 official VC build, pinned by hash. Only the diagnostic tool uses it.
include(FetchContent)
FetchContent_Declare(sdl3
    URL https://github.com/libsdl-org/SDL/releases/download/release-3.4.16/SDL3-devel-3.4.16-VC.zip
    URL_HASH SHA256=1a784cb2a5c64d56fe7a62090fe9d242d9865f235e4ea9678f1a6ba4e693e7de
    SOURCE_SUBDIR none) # download only; the package ships its own CMake config
FetchContent_MakeAvailable(sdl3)
find_package(SDL3 REQUIRED CONFIG PATHS "${sdl3_SOURCE_DIR}/cmake" NO_DEFAULT_PATH)

add_executable(ttmax-diag diag/ttmax_diag.cpp)
target_link_libraries(ttmax-diag PRIVATE gyro_core SDL3::SDL3 winmm)
add_custom_command(TARGET ttmax-diag POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:SDL3::SDL3> $<TARGET_FILE_DIR:ttmax-diag>)

# The in-game half: loaded by the NativeGyro sdkmod through ctypes.
add_library(bl4gyro SHARED core/bl4gyro.cpp)
target_link_libraries(bl4gyro PRIVATE gyro_core)

find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
    add_test(NAME dll_replay COMMAND Python3::Interpreter -I ${CMAKE_SOURCE_DIR}/tests/dll_replay_check.py $<TARGET_FILE:bl4gyro>)
endif()
add_test(NAME scripts COMMAND powershell -NoProfile -ExecutionPolicy Bypass -File ${CMAKE_SOURCE_DIR}/tests/scripts_check.ps1)
