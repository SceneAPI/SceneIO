cmake_minimum_required(VERSION 3.15...3.31)
project(sceneio_core LANGUAGES CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Python (scikit-build-core provides the hints for the target interpreter).
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module)

# Locate the pip-installed nanobind and load its CMake package.
execute_process(
  COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_STRIP_TRAILING_WHITESPACE
  OUTPUT_VARIABLE nanobind_ROOT)
find_package(nanobind CONFIG REQUIRED)

# STABLE_ABI -> a single abi3 wheel across CPython >= 3.12 (D1/D4 in
# docs/io_implementation_plan.md); NB_STATIC links nanobind statically so the
# wheel has no extra runtime .so/.dll to ship.
nanobind_add_module(_core STABLE_ABI NB_STATIC
  src/cpp/module.cpp
  src/cpp/pfm.cpp
  src/cpp/colmap.cpp
  src/cpp/ply_gaussian.cpp)
target_include_directories(_core PRIVATE src/cpp)

# Land the extension inside the importable `sceneio` package as sceneio._core.
install(TARGETS _core LIBRARY DESTINATION sceneio)
