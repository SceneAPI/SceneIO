cmake_minimum_required(VERSION 3.18...3.31)
project(sceneio_core LANGUAGES C CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(cmake/SceneIOInstrumentation.cmake)
include(cmake/SceneIOSources.cmake)
include(cmake/SceneIODependencies.cmake)
include(cmake/SceneIOCameraModels.cmake)
include(cmake/SceneIOBackendQualification.cmake)
include(cmake/SceneIOTargets.cmake)
