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

# nlohmann/json (MIT), header-only — for the transforms.json codec.
FetchContent_Declare(nlohmann_json
  URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz)
set(JSON_BuildTests OFF CACHE INTERNAL "")
set(JSON_Install OFF CACHE INTERNAL "")
FetchContent_MakeAvailable(nlohmann_json)

# zstd (BSD) — for the SPZ v4 (NGSP) container. Build only the static lib.
set(ZSTD_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(ZSTD_BUILD_STATIC ON CACHE BOOL "" FORCE)
set(ZSTD_BUILD_PROGRAMS OFF CACHE BOOL "" FORCE)
set(ZSTD_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ZSTD_BUILD_CONTRIB OFF CACHE BOOL "" FORCE)
set(ZSTD_LEGACY_SUPPORT OFF CACHE BOOL "" FORCE)
FetchContent_Declare(zstd
  URL https://github.com/facebook/zstd/releases/download/v1.5.6/zstd-1.5.6.tar.gz
  SOURCE_SUBDIR build/cmake)
FetchContent_MakeAvailable(zstd)
set_property(TARGET libzstd_static PROPERTY POSITION_INDEPENDENT_CODE ON)

# fast_float (Apache-2.0 / MIT / BSL, header-only) — portable + fast float
# parsing for the text codecs. std::from_chars<double> is unavailable on
# manylinux2014 (GCC 10) and older libc++ (macOS), so the wheels would not
# build with it; fast_float::from_chars is a drop-in that works on all three.
FetchContent_Declare(fast_float
  URL https://github.com/fastfloat/fast_float/archive/refs/tags/v6.1.6.tar.gz)
FetchContent_MakeAvailable(fast_float)

nanobind_add_module(_core STABLE_ABI NB_STATIC
  src/cpp/module.cpp
  src/cpp/records/reconstruction.cpp
  src/cpp/records/gaussian_cloud.cpp
  src/cpp/records/posed_view_set.cpp
  src/cpp/records/tensor_dict.cpp
  src/cpp/records/image.cpp
  src/cpp/records/point_cloud.cpp
  src/cpp/records/depth_map.cpp
  src/cpp/codecs/pfm.cpp
  src/cpp/codecs/colmap.cpp
  src/cpp/codecs/ply_gaussian.cpp
  src/cpp/codecs/spz.cpp
  src/cpp/codecs/transforms_json.cpp
  src/cpp/codecs/pose_text.cpp
  src/cpp/codecs/npy_npz.cpp
  src/cpp/codecs/netpbm.cpp
  src/cpp/codecs/colmap_txt.cpp
  src/cpp/codecs/xyz.cpp
  src/cpp/codecs/flo.cpp)
target_include_directories(_core PRIVATE src/cpp ${zstd_SOURCE_DIR}/lib ${fast_float_SOURCE_DIR}/include)
target_link_libraries(_core PRIVATE miniz_static nlohmann_json::nlohmann_json libzstd_static)

# Land the extension inside the importable `sceneio` package as sceneio._core.
install(TARGETS _core LIBRARY DESTINATION sceneio)
