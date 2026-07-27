# Opt-in compiler instrumentation used by the dedicated native CI lane.
# Defining the flags globally instruments both _core and the linked C/C++
# codec libraries.

option(
  SCENEIO_ENABLE_SANITIZERS
  "Build SceneIO and vendored codecs with ASan/UBSan/LSan"
  OFF)
option(
  SCENEIO_BUILD_NATIVE_TEST_HOOKS
  "Build the separate, sanitizer-only native control extension"
  OFF)

if(SCENEIO_ENABLE_SANITIZERS)
  if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND
     CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(
      -fsanitize=address,undefined
      -fno-omit-frame-pointer
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
