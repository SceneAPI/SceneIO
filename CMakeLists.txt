cmake_minimum_required(VERSION 3.15...3.31)
project(sceneio_core LANGUAGES C CXX)

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
# miniz (MIT) — gzip inflate/deflate for the SPZ codec. The amalgamated
# release is just miniz.c + miniz.h; build it as a small static library.
include(FetchContent)
FetchContent_Declare(miniz
  URL https://github.com/richgel999/miniz/releases/download/3.0.2/miniz-3.0.2.zip)
FetchContent_MakeAvailable(miniz)
add_library(miniz_static STATIC ${miniz_SOURCE_DIR}/miniz.c)
target_include_directories(miniz_static PUBLIC ${miniz_SOURCE_DIR})
set_property(TARGET miniz_static PROPERTY POSITION_INDEPENDENT_CODE ON)

nanobind_add_module(_core STABLE_ABI NB_STATIC
  src/cpp/module.cpp
  src/cpp/pfm.cpp
  src/cpp/colmap.cpp
  src/cpp/ply_gaussian.cpp
  src/cpp/spz.cpp)
target_include_directories(_core PRIVATE src/cpp)
target_link_libraries(_core PRIVATE miniz_static)

# Land the extension inside the importable `sceneio` package as sceneio._core.
install(TARGETS _core LIBRARY DESTINATION sceneio)
