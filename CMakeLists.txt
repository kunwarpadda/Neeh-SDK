cmake_minimum_required(VERSION 3.16)

project(
  NeehSDK
  VERSION 0.1.0
  DESCRIPTION "Portable structured digital ink core"
  LANGUAGES C CXX
)

option(NEEH_BUILD_TESTS "Build the portable core test suite" ON)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

add_library(neeh_core
  cpp/src/c_api.cpp
  cpp/src/core.cpp
  cpp/src/render.cpp
)
add_library(Neeh::Core ALIAS neeh_core)

target_compile_features(neeh_core PUBLIC cxx_std_17)
target_compile_definitions(neeh_core PRIVATE NEEH_CORE_BUILD)
if(BUILD_SHARED_LIBS)
  target_compile_definitions(neeh_core PUBLIC NEEH_CORE_SHARED)
endif()
target_include_directories(neeh_core
  PUBLIC
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/cpp/include>"
    "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
set_target_properties(neeh_core PROPERTIES
  CXX_EXTENSIONS OFF
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  OUTPUT_NAME neeh_core
  VERSION "${PROJECT_VERSION}"
  SOVERSION "1"
  EXPORT_NAME Core
)

if(MSVC)
  target_compile_options(neeh_core PRIVATE /W4 /permissive-)
else()
  target_compile_options(neeh_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

install(
  TARGETS neeh_core
  EXPORT NeehSDKTargets
  ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
  LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
  RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
  INCLUDES DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
)
install(
  DIRECTORY cpp/include/
  DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
  FILES_MATCHING PATTERN "*.h" PATTERN "*.hpp"
)
install(
  FILES LICENSE
  DESTINATION "${CMAKE_INSTALL_DATAROOTDIR}/licenses/NeehSDK"
)

configure_package_config_file(
  cpp/cmake/NeehSDKConfig.cmake.in
  "${CMAKE_CURRENT_BINARY_DIR}/NeehSDKConfig.cmake"
  INSTALL_DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/NeehSDK"
)
write_basic_package_version_file(
  "${CMAKE_CURRENT_BINARY_DIR}/NeehSDKConfigVersion.cmake"
  VERSION "${PROJECT_VERSION}"
  COMPATIBILITY SameMajorVersion
)
install(
  EXPORT NeehSDKTargets
  FILE NeehSDKTargets.cmake
  NAMESPACE Neeh::
  DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/NeehSDK"
)
install(
  FILES
    "${CMAKE_CURRENT_BINARY_DIR}/NeehSDKConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/NeehSDKConfigVersion.cmake"
  DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/NeehSDK"
)

if(NEEH_BUILD_TESTS)
  include(CTest)
  enable_testing()
  add_subdirectory(cpp/tests)
endif()
