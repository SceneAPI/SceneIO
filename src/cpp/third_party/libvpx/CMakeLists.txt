cmake_minimum_required(VERSION 3.18)

# Chromium's checked source manifest is the single source of truth for this
# compact portable libvpx build. Keep only the generic C implementation here;
# libvpx still provides its upstream multithreaded VP8/VP9 algorithms, while
# the wheel build does not acquire NASM, MSYS, or a system codec package.
file(GLOB_RECURSE _sceneio_libvpx_sources CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/vp8/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/vp9/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/vpx/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/vpx_dsp/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/vpx_mem/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/vpx_scale/*.c"
     "${CMAKE_CURRENT_SOURCE_DIR}/vpx_util/*.c")

list(LENGTH _sceneio_libvpx_sources _sceneio_libvpx_source_count)
if(NOT _sceneio_libvpx_source_count EQUAL 155)
  message(FATAL_ERROR
          "Pinned libvpx generic manifest must contain exactly 155 C sources; "
          "found ${_sceneio_libvpx_source_count}")
endif()

add_library(sceneio_vpx STATIC ${_sceneio_libvpx_sources})
set_target_properties(sceneio_vpx PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(
  sceneio_vpx
  PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}"
  PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/config")
target_compile_definitions(
  sceneio_vpx
  PRIVATE CHROMIUM
          "VPX_MAX_ALLOCABLE_MEMORY=((1ULL << 31) - (1 << 21))")

if(MSVC)
  target_compile_options(sceneio_vpx PRIVATE /w)
else()
  target_compile_options(sceneio_vpx PRIVATE -w)
  find_package(Threads REQUIRED)
  target_link_libraries(sceneio_vpx PRIVATE Threads::Threads)
endif()
