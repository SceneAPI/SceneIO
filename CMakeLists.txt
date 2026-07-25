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
option(SCENEIO_BUILD_NATIVE_TEST_HOOKS
  "Build the separate, sanitizer-only native control extension" OFF)
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
if(SCENEIO_BUILD_NATIVE_TEST_HOOKS AND NOT SCENEIO_ENABLE_SANITIZERS)
  message(FATAL_ERROR
    "SCENEIO_BUILD_NATIVE_TEST_HOOKS requires SCENEIO_ENABLE_SANITIZERS=ON")
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

# LAZperf 3.4.0 (Apache-2.0/BSD-3-Clause/BSD-2-Clause) —
# LASzip-compatible LAZ
# compression/decompression. Fetch the immutable audited commit, but
# deliberately skip upstream's CMake tree: it also builds a shared library,
# tools, tests, and install rules. SceneIO compiles only the 15 library
# translation units into one hidden static archive.
FetchContent_Declare(lazperf
  URL https://github.com/hobuinc/laz-perf/archive/b7bbe26109dc986f42d4fc80b8de3d2b6ca634ce.tar.gz
  URL_HASH SHA256=17df34ca64cc60e107f0c214db4729c54a514df4e32de5bc1b8b7b7c5a805a56
  SOURCE_SUBDIR sceneio-no-upstream-cmake)
FetchContent_MakeAvailable(lazperf)

# LAZperf's format-1.4 decoders first copy each bounded arithmetic layer into
# MemoryStream, whose upstream getByte() indexes the vector without checking
# exhaustion. Apply a narrow, fail-closed patch so malformed layers produce a
# codec exception instead of an out-of-bounds read. COMMIT.txt documents it.
set(_sceneio_lazperf_streams "${lazperf_SOURCE_DIR}/cpp/lazperf/streams.hpp")
file(READ "${_sceneio_lazperf_streams}" _sceneio_lazperf_streams_text)
set(_sceneio_lazperf_getbyte_old [=[
    unsigned char getByte()
    {
        return buf[idx++];
    }
]=])
set(_sceneio_lazperf_getbyte_new [=[
    unsigned char getByte()
    {
        if (idx >= buf.size())
            throw error("LAZperf input stream exhausted");
        return buf[idx++];
    }
]=])
string(FIND "${_sceneio_lazperf_streams_text}"
  "${_sceneio_lazperf_getbyte_new}" _sceneio_lazperf_patch_applied)
if(_sceneio_lazperf_patch_applied EQUAL -1)
  string(FIND "${_sceneio_lazperf_streams_text}"
    "${_sceneio_lazperf_getbyte_old}" _sceneio_lazperf_patch_target)
  if(_sceneio_lazperf_patch_target EQUAL -1)
    message(FATAL_ERROR
      "Pinned LAZperf MemoryStream::getByte() no longer matches the documented "
      "SceneIO local patch target")
  endif()
  string(REPLACE "${_sceneio_lazperf_getbyte_old}"
    "${_sceneio_lazperf_getbyte_new}" _sceneio_lazperf_streams_text
    "${_sceneio_lazperf_streams_text}")
  file(WRITE "${_sceneio_lazperf_streams}" "${_sceneio_lazperf_streams_text}")
endif()
unset(_sceneio_lazperf_streams)
unset(_sceneio_lazperf_streams_text)
unset(_sceneio_lazperf_getbyte_old)
unset(_sceneio_lazperf_getbyte_new)
unset(_sceneio_lazperf_patch_applied)
unset(_sceneio_lazperf_patch_target)

# LAZperf's integer decompressor performs predictor addition and k=31
# corrector translation in signed int32 arithmetic. Valid streams stay within
# the intended domain, but malformed layered streams can overflow before the
# wrapper can normalize the codec error. Use defined full-range wrapping,
# wider bounded intermediates, and reject an unrepresentable corrector.
set(_sceneio_lazperf_decompressor
  "${lazperf_SOURCE_DIR}/cpp/lazperf/decompressor.hpp")
file(READ "${_sceneio_lazperf_decompressor}"
  _sceneio_lazperf_decompressor_text)
set(_sceneio_lazperf_decompressor_original
  "${_sceneio_lazperf_decompressor_text}")

set(_sceneio_lazperf_include_old [=[
#include "model.hpp"
]=])
set(_sceneio_lazperf_include_intermediate [=[
#include "excepts.hpp"
#include "model.hpp"

#include <cstdint>
]=])
set(_sceneio_lazperf_include_new [=[
#include "excepts.hpp"
#include "model.hpp"

#include <cstdint>
#include <limits>
]=])
string(FIND "${_sceneio_lazperf_decompressor_text}"
  "${_sceneio_lazperf_include_new}" _sceneio_lazperf_patch_applied)
if(_sceneio_lazperf_patch_applied EQUAL -1)
  string(FIND "${_sceneio_lazperf_decompressor_text}"
    "${_sceneio_lazperf_include_intermediate}"
    _sceneio_lazperf_patch_target)
  if(_sceneio_lazperf_patch_target EQUAL -1)
    string(FIND "${_sceneio_lazperf_decompressor_text}"
      "${_sceneio_lazperf_include_old}" _sceneio_lazperf_patch_target)
    if(_sceneio_lazperf_patch_target EQUAL -1)
      message(FATAL_ERROR
        "Pinned LAZperf decompressor includes no longer match the documented "
        "SceneIO local patch target")
    endif()
    string(REPLACE "${_sceneio_lazperf_include_old}"
      "${_sceneio_lazperf_include_new}" _sceneio_lazperf_decompressor_text
      "${_sceneio_lazperf_decompressor_text}")
  else()
    string(REPLACE "${_sceneio_lazperf_include_intermediate}"
      "${_sceneio_lazperf_include_new}" _sceneio_lazperf_decompressor_text
      "${_sceneio_lazperf_decompressor_text}")
  endif()
endif()

set(_sceneio_lazperf_predictor_old [=[
				int32_t real = pred + readCorrector(dec, mBits[context]);
				if (real < 0) real += corr_range;
				else if ((uint32_t)(real) >= corr_range) real -= corr_range;

				return real;
]=])
set(_sceneio_lazperf_predictor_new [=[
				const int32_t corrector = readCorrector(dec, mBits[context]);
				if (corr_range == 0)
				{
					const uint32_t wrapped =
						static_cast<uint32_t>(pred) +
						static_cast<uint32_t>(corrector);
					const uint32_t i32_max =
						static_cast<uint32_t>((std::numeric_limits<int32_t>::max)());
					return wrapped <= i32_max ?
						static_cast<int32_t>(wrapped) :
						-1 - static_cast<int32_t>(
							(std::numeric_limits<uint32_t>::max)() - wrapped);
				}

				int64_t real =
					static_cast<int64_t>(pred) +
					static_cast<int64_t>(corrector);
				if (real < 0) real += corr_range;
				else if (static_cast<uint64_t>(real) >= corr_range)
					real -= corr_range;
				return static_cast<int32_t>(real);
]=])
string(FIND "${_sceneio_lazperf_decompressor_text}"
  "${_sceneio_lazperf_predictor_new}" _sceneio_lazperf_patch_applied)
if(_sceneio_lazperf_patch_applied EQUAL -1)
  string(FIND "${_sceneio_lazperf_decompressor_text}"
    "${_sceneio_lazperf_predictor_old}" _sceneio_lazperf_patch_target)
  if(_sceneio_lazperf_patch_target EQUAL -1)
    message(FATAL_ERROR
      "Pinned LAZperf predictor arithmetic no longer matches the documented "
      "SceneIO local patch target")
  endif()
  string(REPLACE "${_sceneio_lazperf_predictor_old}"
    "${_sceneio_lazperf_predictor_new}" _sceneio_lazperf_decompressor_text
    "${_sceneio_lazperf_decompressor_text}")
endif()

# Normalize one upstream comment's trailing space so the exact patch target can
# remain whitespace-clean in SceneIO's tracked CMake source.
string(REPLACE "by adding 1 \n" "by adding 1\n"
  _sceneio_lazperf_decompressor_text
  "${_sceneio_lazperf_decompressor_text}")
set(_sceneio_lazperf_compact_corrector_old [=[
						if (c >= (1<<(k-1))) // if c is in the interval [ 2^(k-1)  ...  + 2^k - 1 ]
						{
							// so we translate c back into the interval [ 2^(k-1) + 1  ...  2^k ] by adding 1
							c += 1;
						}
						else // otherwise c is in the interval [ 0 ...  + 2^(k-1) - 1 ]
						{
							// so we translate c back into the interval [ - (2^k - 1)  ...  - (2^(k-1)) ] by subtracting (2^k - 1)
							c -= ((1<<k) - 1);
						}
]=])
set(_sceneio_lazperf_compact_corrector_new [=[
						// Translate in int64 so the optional compact decoder
						// has the same defined malformed-input behavior.
						const int64_t threshold = int64_t{1} << (k - 1);
						int64_t translated = c;
						if (translated >= threshold)
							translated += 1;
						else
							translated -= (int64_t{1} << k) - 1;
						if (translated < (std::numeric_limits<int32_t>::min)() ||
							translated > (std::numeric_limits<int32_t>::max)())
							throw error("LAZperf integer corrector is out of range");
						c = static_cast<int32_t>(translated);
]=])
string(LENGTH "${_sceneio_lazperf_decompressor_text}"
  _sceneio_lazperf_corrector_source_length)
string(LENGTH "${_sceneio_lazperf_compact_corrector_old}"
  _sceneio_lazperf_corrector_old_length)
string(REPLACE "${_sceneio_lazperf_compact_corrector_old}" ""
  _sceneio_lazperf_corrector_without_old
  "${_sceneio_lazperf_decompressor_text}")
string(LENGTH "${_sceneio_lazperf_corrector_without_old}"
  _sceneio_lazperf_corrector_without_old_length)
math(EXPR _sceneio_lazperf_corrector_old_count
  "(${_sceneio_lazperf_corrector_source_length} - ${_sceneio_lazperf_corrector_without_old_length}) / ${_sceneio_lazperf_corrector_old_length}")

string(LENGTH "${_sceneio_lazperf_compact_corrector_new}"
  _sceneio_lazperf_corrector_new_length)
string(REPLACE "${_sceneio_lazperf_compact_corrector_new}" ""
  _sceneio_lazperf_corrector_without_new
  "${_sceneio_lazperf_decompressor_text}")
string(LENGTH "${_sceneio_lazperf_corrector_without_new}"
  _sceneio_lazperf_corrector_without_new_length)
math(EXPR _sceneio_lazperf_corrector_new_count
  "(${_sceneio_lazperf_corrector_source_length} - ${_sceneio_lazperf_corrector_without_new_length}) / ${_sceneio_lazperf_corrector_new_length}")

if(_sceneio_lazperf_corrector_old_count EQUAL 2 AND
   _sceneio_lazperf_corrector_new_count EQUAL 0)
  string(REPLACE "${_sceneio_lazperf_compact_corrector_old}"
    "${_sceneio_lazperf_compact_corrector_new}"
    _sceneio_lazperf_decompressor_text
    "${_sceneio_lazperf_decompressor_text}")
elseif(_sceneio_lazperf_corrector_old_count EQUAL 0 AND
       _sceneio_lazperf_corrector_new_count EQUAL 2)
  # Already patched.
else()
  message(FATAL_ERROR
    "Pinned LAZperf corrector patch expected exactly two original or two "
    "patched decoder branches; found "
    "${_sceneio_lazperf_corrector_old_count} original and "
    "${_sceneio_lazperf_corrector_new_count} patched")
endif()
if(NOT _sceneio_lazperf_decompressor_text STREQUAL
    _sceneio_lazperf_decompressor_original)
  file(WRITE "${_sceneio_lazperf_decompressor}"
    "${_sceneio_lazperf_decompressor_text}")
endif()

unset(_sceneio_lazperf_decompressor)
unset(_sceneio_lazperf_decompressor_text)
unset(_sceneio_lazperf_decompressor_original)
unset(_sceneio_lazperf_include_old)
unset(_sceneio_lazperf_include_intermediate)
unset(_sceneio_lazperf_include_new)
unset(_sceneio_lazperf_predictor_old)
unset(_sceneio_lazperf_predictor_new)
unset(_sceneio_lazperf_compact_corrector_old)
unset(_sceneio_lazperf_compact_corrector_new)
unset(_sceneio_lazperf_corrector_source_length)
unset(_sceneio_lazperf_corrector_old_length)
unset(_sceneio_lazperf_corrector_without_old)
unset(_sceneio_lazperf_corrector_without_old_length)
unset(_sceneio_lazperf_corrector_old_count)
unset(_sceneio_lazperf_corrector_new_length)
unset(_sceneio_lazperf_corrector_without_new)
unset(_sceneio_lazperf_corrector_without_new_length)
unset(_sceneio_lazperf_corrector_new_count)
unset(_sceneio_lazperf_patch_applied)
unset(_sceneio_lazperf_patch_target)

file(GLOB LAZPERF_SOURCES CONFIGURE_DEPENDS
  "${lazperf_SOURCE_DIR}/cpp/lazperf/*.cpp"
  "${lazperf_SOURCE_DIR}/cpp/lazperf/detail/*.cpp")
add_library(lazperf_static STATIC ${LAZPERF_SOURCES})
target_include_directories(lazperf_static PUBLIC "${lazperf_SOURCE_DIR}/cpp")
target_compile_definitions(lazperf_static PRIVATE
  $<$<PLATFORM_ID:Windows>:WIN32_LEAN_AND_MEAN>
  $<$<CXX_COMPILER_ID:MSVC>:_CRT_SECURE_NO_WARNINGS>)
set_property(TARGET lazperf_static PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET lazperf_static PROPERTY CXX_VISIBILITY_PRESET hidden)
if(WIN32)
  target_link_libraries(lazperf_static PUBLIC ws2_32)
endif()

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

# SQLite (public domain) -- the in-repo 3.53.4 amalgamation is pinned in
# third_party/sqlite/COMMIT.txt. Keep the database engine private and omit
# surfaces SceneIO does not use; COLMAP reads still retain normal locking and
# read-only enforcement, while writes use rollback-capable transactions.
add_library(sqlite_static STATIC src/cpp/third_party/sqlite/sqlite3.c)
target_include_directories(sqlite_static PUBLIC src/cpp/third_party/sqlite)
target_compile_definitions(sqlite_static PRIVATE
  SQLITE_DQS=0
  SQLITE_DEFAULT_MEMSTATUS=0
  SQLITE_OMIT_DEPRECATED
  SQLITE_OMIT_LOAD_EXTENSION)
set_property(TARGET sqlite_static PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET sqlite_static PROPERTY C_VISIBILITY_PRESET hidden)

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
  src/cpp/records/image_sequence.cpp
  src/cpp/records/point_cloud.cpp
  src/cpp/records/depth_map.cpp
  src/cpp/records/flow_field.cpp
  src/cpp/records/state_trajectory.cpp
  src/cpp/records/camera_rig.cpp
  src/cpp/records/pose_graph.cpp
  src/cpp/records/feature_match.cpp
  src/cpp/records/material_set.cpp
  src/cpp/records/mesh.cpp
  src/cpp/records/mesh_scene.cpp
  src/cpp/codecs/pfm.cpp
  src/cpp/codecs/colmap.cpp
  src/cpp/codecs/ply_gaussian.cpp
  src/cpp/codecs/compressed_ply.cpp
  src/cpp/codecs/sog.cpp
  src/cpp/codecs/ksplat.cpp
  src/cpp/codecs/ply_point.cpp
  src/cpp/codecs/ply_mesh.cpp
  src/cpp/codecs/obj_mtl.cpp
  src/cpp/codecs/stl_off.cpp
  src/cpp/codecs/gltf.cpp
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
  src/cpp/codecs/laz.cpp
  src/cpp/codecs/y4m.cpp
  src/cpp/codecs/webp.cpp
  src/cpp/codecs/safetensors.cpp
  src/cpp/codecs/dmb.cpp
  src/cpp/codecs/euroc_state.cpp
  src/cpp/codecs/camera_calibration.cpp
  src/cpp/codecs/g2o.cpp
  src/cpp/codecs/colmap_db.cpp
  src/cpp/third_party/stb/stb_impl.cpp
  src/cpp/third_party/tinyexr/tinyexr_impl.cpp)
target_include_directories(_core PRIVATE src/cpp ${zstd_SOURCE_DIR}/lib ${fast_float_SOURCE_DIR}/include
  src/cpp/third_party/stb src/cpp/third_party/tinyexr
  src/cpp/third_party/tinyobjloader src/cpp/third_party/cgltf
  ${libwebp_SOURCE_DIR}
  ${libwebp_SOURCE_DIR}/src)
target_link_libraries(_core PRIVATE miniz_static nlohmann_json::nlohmann_json
  libzstd_static lazperf_static lodepng_static sqlite_static webp Threads::Threads)

# Land the extension inside the importable `sceneio` package as sceneio._core.
install(TARGETS _core LIBRARY DESTINATION sceneio)

# A separate, off-by-default extension supplies LSan controls and controlled
# LAZperf arithmetic decoders for the focused native workflow. These hooks
# must never be linked into _core or a normal wheel.
if(SCENEIO_BUILD_NATIVE_TEST_HOOKS)
  add_executable(sceneio_native_arithmetic_default_check
    src/cpp/testing/lazperf_default_main.cpp
    src/cpp/testing/lazperf_default_test.cpp)
  target_compile_options(
    sceneio_native_arithmetic_default_check PRIVATE -g)
  target_link_libraries(
    sceneio_native_arithmetic_default_check PRIVATE lazperf_static)

  # Keep the COMPRESS_ONLY_K header instantiation in a separate binary. The
  # macro changes LAZperf's integer class definition, so linking both variants
  # into one program would violate the C++ one-definition rule.
  add_executable(sceneio_native_arithmetic_compact_check
    src/cpp/testing/lazperf_compact_main.cpp
    src/cpp/testing/lazperf_compact_test.cpp)
  target_compile_options(
    sceneio_native_arithmetic_compact_check PRIVATE -g)
  target_link_libraries(
    sceneio_native_arithmetic_compact_check PRIVATE lazperf_static)

  nanobind_add_module(_native_test STABLE_ABI NB_STATIC
    src/cpp/testing/native_test.cpp
    src/cpp/testing/lazperf_default_test.cpp)
  target_compile_options(_native_test PRIVATE -g)
  target_link_libraries(_native_test PRIVATE lazperf_static)
  install(TARGETS _native_test LIBRARY DESTINATION sceneio)
endif()
