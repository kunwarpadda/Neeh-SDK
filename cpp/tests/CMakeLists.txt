add_executable(neeh_core_cpp_tests core_tests.cpp)
target_link_libraries(neeh_core_cpp_tests PRIVATE Neeh::Core)
target_compile_features(neeh_core_cpp_tests PRIVATE cxx_std_17)
set_target_properties(neeh_core_cpp_tests PROPERTIES CXX_EXTENSIONS OFF)
add_test(NAME neeh_core_cpp COMMAND neeh_core_cpp_tests)

add_executable(neeh_core_c_abi_tests c_api_tests.c)
target_link_libraries(neeh_core_c_abi_tests PRIVATE Neeh::Core)
set_target_properties(neeh_core_c_abi_tests PROPERTIES
  C_STANDARD 99
  C_EXTENSIONS OFF
  LINKER_LANGUAGE CXX
)
add_test(NAME neeh_core_c_abi COMMAND neeh_core_c_abi_tests)

if(MSVC)
  target_compile_options(neeh_core_cpp_tests PRIVATE /W4 /permissive-)
  target_compile_options(neeh_core_c_abi_tests PRIVATE /W4)
else()
  target_compile_options(neeh_core_cpp_tests PRIVATE -Wall -Wextra -Wpedantic)
  target_compile_options(neeh_core_c_abi_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
