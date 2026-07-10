cmake_minimum_required(VERSION 3.16)
project(NeehPackageConsumer LANGUAGES CXX)

find_package(NeehSDK 0.1 CONFIG REQUIRED)

add_executable(neeh_package_consumer main.cpp)
target_link_libraries(neeh_package_consumer PRIVATE Neeh::Core)
target_compile_features(neeh_package_consumer PRIVATE cxx_std_17)
