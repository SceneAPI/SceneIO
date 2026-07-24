cmake_minimum_required(VERSION 3.15...3.31)
project(sceneio_core LANGUAGES C CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Opt-in sanitizer build used by .github/workflows/sanitizers.yml. Defining the
# flags globally instruments both _core and the vendored C/C++ codec libraries;
# ASan includes LSan on Linux, while UBSan covers undefined behavior.
option(SCENEIO_ENABLE_SANITIZERS "Build SceneIO and vendored codecs with ASan/UBSan/LSan" OFF)
if(SCENEIO_ENABLE_SANITIZERS)
  if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer
                        -fno-sanitize-recover=all)
    add_link_options(-fsanitize=address,undefined)
  else()
    message(FATAL_ERROR
      "SCENEIO_ENABLE_SANITIZERS supports Linux GCC/Clang (ASan includes LSan)")
  endif()
endif()

# Python (scikit-build-core provides the hints for the target interpreter).
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(Threads REQUIRED)

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

# lodepng (zlib license) — PNG codec. Vendored in-repo at
# src/cpp/third_party/lodepng (COMMIT.txt pins the source); it has its own
# self-contained inflate/deflate (lodepng_*-prefixed, no miniz interaction), so
# it builds as a tiny static lib with no external deps. LODEPNG_NO_COMPILE_DISK
# drops the fopen paths (bytes-only API); hidden visibility keeps its symbols out
# of _core's export table.
add_library(lodepng_static STATIC src/cpp/third_party/lodepng/lodepng.cpp)
target_include_directories(lodepng_static PUBLIC src/cpp/third_party/lodepng)
target_compile_definitions(lodepng_static PUBLIC LODEPNG_NO_COMPILE_DISK)
set_property(TARGET lodepng_static PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET lodepng_static PROPERTY CXX_VISIBILITY_PRESET hidden)

# libwebp (BSD) — WebP codec, built from source (all its command-line tools OFF so
# only the core encode/decode static libs compile). Link the in-tree `webp` target
# (NOT `WebP::webp`, which only exists via find_package — the fast_float alias
# lesson); it pulls in `sharpyuv` itself.
foreach(_wopt WEBP_BUILD_ANIM_UTILS WEBP_BUILD_CWEBP WEBP_BUILD_DWEBP WEBP_BUILD_GIF2WEBP
        WEBP_BUILD_IMG2WEBP WEBP_BUILD_VWEBP WEBP_BUILD_WEBPINFO WEBP_BUILD_WEBPMUX
        WEBP_BUILD_LIBWEBPMUX WEBP_BUILD_EXTRAS WEBP_BUILD_FUZZTEST)
  set(${_wopt} OFF CACHE BOOL "" FORCE)
endforeach()
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)  # static webp linked into _core
FetchContent_Declare(libwebp
  URL https://github.com/webmproject/libwebp/archive/refs/tags/v1.5.0.tar.gz)
FetchContent_MakeAvailable(libwebp)
set_property(TARGET webp PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET sharpyuv PROPERTY POSITION_INDEPENDENT_CODE ON)

nanobind_add_module(_core STABLE_ABI NB_STATIC
  src/cpp/module.cpp
  src/cpp/records/reconstruction.cpp
  src/cpp/records/gaussian_cloud.cpp
  src/cpp/records/posed_view_set.cpp
  src/cpp/records/tensor_dict.cpp
  src/cpp/records/image.cpp
  src/cpp/records/point_cloud.cpp
  src/cpp/records/depth_map.cpp
  src/cpp/records/flow_field.cpp
  src/cpp/records/state_trajectory.cpp
  src/cpp/records/camera_rig.cpp
  src/cpp/codecs/pfm.cpp
  src/cpp/codecs/colmap.cpp
  src/cpp/codecs/ply_gaussian.cpp
  src/cpp/codecs/ply_point.cpp
  src/cpp/codecs/pcd.cpp
  src/cpp/codecs/spz.cpp
  src/cpp/codecs/transforms_json.cpp
  src/cpp/codecs/pose_text.cpp
  src/cpp/codecs/npy_npz.cpp
  src/cpp/codecs/netpbm.cpp
  src/cpp/codecs/colmap_txt.cpp
  src/cpp/codecs/xyz.cpp
  src/cpp/codecs/flo.cpp
  src/cpp/codecs/bundler.cpp
  src/cpp/codecs/bal.cpp
  src/cpp/codecs/nvm.cpp
  src/cpp/codecs/openmvg.cpp
  src/cpp/codecs/splat.cpp
  src/cpp/codecs/png.cpp
  src/cpp/codecs/jpeg.cpp
  src/cpp/codecs/hdr.cpp
  src/cpp/codecs/bmp_tga.cpp
  src/cpp/codecs/exr.cpp
  src/cpp/codecs/las.cpp
  src/cpp/codecs/webp.cpp
  src/cpp/codecs/safetensors.cpp
  src/cpp/codecs/dmb.cpp
  src/cpp/codecs/euroc_state.cpp
  src/cpp/codecs/camera_calibration.cpp
  src/cpp/third_party/stb/stb_impl.cpp
  src/cpp/third_party/tinyexr/tinyexr_impl.cpp)
target_include_directories(_core PRIVATE src/cpp ${zstd_SOURCE_DIR}/lib ${fast_float_SOURCE_DIR}/include
  src/cpp/third_party/stb src/cpp/third_party/tinyexr ${libwebp_SOURCE_DIR}
  ${libwebp_SOURCE_DIR}/src)
target_link_libraries(_core PRIVATE miniz_static nlohmann_json::nlohmann_json
  libzstd_static lodepng_static webp Threads::Threads)

# Land the extension inside the importable `sceneio` package as sceneio._core.
install(TARGETS _core LIBRARY DESTINATION sceneio)
