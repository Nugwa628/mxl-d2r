# Unit tests for the pure parts of mxl-core (not in the plugin DLL). Included by ../CMakeLists.txt
# (cmake --build build/plugin --config Release --target mxl_tests craft_tests goblin_tests), and buildable on its own
# without Windows headers or a resource compiler, as CI does on Linux: cmake -S plugin/tests -B build/tests.
cmake_minimum_required(VERSION 3.20)
project(mxl_core_tests LANGUAGES CXX)

set(src ${CMAKE_CURRENT_SOURCE_DIR}/../src)
add_executable(mxl_tests EXCLUDE_FROM_ALL requirements_test.cpp item_text_test.cpp quests_test.cpp dungeon_test.cpp npc_actions_test.cpp npc_services_test.cpp requirement_gates_test.cpp hirelings_test.cpp combat_test.cpp items_ext_test.cpp item_gen_test.cpp waypoints_test.cpp monster_ai_test.cpp item_events_test.cpp monster_looks_test.cpp stat_columns_test.cpp info_panels_test.cpp skill_restrict_test.cpp heat_test.cpp trophy_timer_test.cpp travel_test.cpp skill_damage_test.cpp item_rules_test.cpp gamble_test.cpp vendor_stock_test.cpp unique_limits_test.cpp unique_carry_test.cpp town_rules_test.cpp stat_rules_test.cpp monster_rules_test.cpp collide_types_test.cpp skill_starts_test.cpp buff_icons_test.cpp
               ${src}/requirements.cpp)
add_executable(craft_tests EXCLUDE_FROM_ALL craft_test.cpp)
add_executable(goblin_tests EXCLUDE_FROM_ALL goblins_test.cpp)
add_executable(nocorpse_tests EXCLUDE_FROM_ALL no_corpse_test.cpp)
add_executable(cooldown_tests EXCLUDE_FROM_ALL cooldowns_test.cpp)
add_executable(harness_tests EXCLUDE_FROM_ALL harness_cmds_test.cpp)
add_executable(clientmsg_tests EXCLUDE_FROM_ALL client_messages_test.cpp)
add_executable(mapmem_tests EXCLUDE_FROM_ALL map_memory_test.cpp)
add_executable(strings_tests EXCLUDE_FROM_ALL strings_test.cpp)
add_executable(buildguard_tests EXCLUDE_FROM_ALL build_guard_test.cpp)
add_executable(otherplugins_tests EXCLUDE_FROM_ALL other_plugins_test.cpp)
add_executable(envguard_tests EXCLUDE_FROM_ALL env_guard_test.cpp)
add_executable(renderpool_tests EXCLUDE_FROM_ALL render_pool_test.cpp)
add_custom_target(tests DEPENDS mxl_tests craft_tests goblin_tests nocorpse_tests cooldown_tests harness_tests clientmsg_tests strings_tests mapmem_tests buildguard_tests otherplugins_tests envguard_tests renderpool_tests)

foreach(t mxl_tests craft_tests goblin_tests nocorpse_tests cooldown_tests harness_tests clientmsg_tests strings_tests mapmem_tests buildguard_tests otherplugins_tests envguard_tests renderpool_tests)
	target_compile_features(${t} PRIVATE cxx_std_20)
	if(MSVC)
		target_compile_options(${t} PRIVATE /W4 /permissive- /EHsc /utf-8)
	else()
		target_compile_options(${t} PRIVATE -Wall -Wextra)
	endif()
	if(NOT PROJECT_IS_TOP_LEVEL)
		# keep the old place next to mxl-core.dll: build/plugin/<config>/mxl_tests.exe
		set_target_properties(${t} PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
	endif()
endforeach()
