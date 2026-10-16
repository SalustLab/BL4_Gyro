@echo off
rem Opens the Native Gyro installer window (no admin rights needed).
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0installer.ps1"
