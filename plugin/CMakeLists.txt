# mxl-core D2RLoader plugin. Build: cmake -S plugin -B build/plugin -A x64 && cmake --build build/plugin --config Release
# (or tools/build_plugin.ps1). tools/install_mod.py copies build/plugin/Release/mxl-core.dll into the mod.
cmake_minimum_required(VERSION 3.29)
project(mxl_core LANGUAGES CXX RC)

set(D2RLPLUGIN_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory(../third_party/PluginSDK PluginSDK EXCLUDE_FROM_ALL)

add_library(mxl_core SHARED src/mxl_core.cpp src/d2r.cpp src/sigma_skills.cpp src/states_fix.cpp src/level_types.cpp src/calc_codes.cpp src/item_spells.cpp src/pet_scaling.cpp src/auras.cpp src/area_damage.cpp src/teleport.cpp src/stat_list.cpp src/missile_hits.cpp src/mana_costs.cpp src/cooldowns.cpp src/skill_restrict.cpp src/heat.cpp src/trophy_timer.cpp src/state_trace.cpp src/whirlwind.cpp src/cube_conditions.cpp src/craft_flags.cpp src/requirements.cpp src/quests_act1.cpp src/quests_act2_5.cpp src/dungeon_lockout.cpp src/goblins.cpp src/sound_guard.cpp src/monster_ai.cpp src/npc_actions.cpp src/npc_services.cpp src/combat.cpp src/stat_columns.cpp src/properties_ext.cpp src/items_ext.cpp src/item_gen.cpp src/requirement_gates.cpp src/hirelings.cpp src/skill_tree.cpp src/waypoints.cpp src/collide_types.cpp src/skill_starts.cpp src/sigma_data.cpp src/client_messages.cpp src/game_end.cpp src/item_events.cpp src/monster_looks.cpp src/strings.cpp src/mxl_core.rc src/strings_probe.cpp src/no_corpse.cpp src/death_event.cpp src/map_memory.cpp src/info_panels.cpp src/buff_icons.cpp src/stash_pages.cpp src/travel.cpp src/skill_damage.cpp src/item_rules.cpp src/quests_rewards.cpp src/gamble.cpp src/vendor_stock.cpp src/item_type_ids.cpp src/engine_gaps.cpp src/stat_rules.cpp src/item_text.cpp src/tooltip_probe.cpp src/monster_rules.cpp src/unique_limits.cpp src/unique_carry.cpp src/town_rules.cpp
    src/hardcore_death.cpp src/required_level.cpp src/translation_guard.cpp src/build_guard.cpp src/render_pool.cpp)
# MXL_RELEASE (player releases, tools/package_release.py): the test harness is not compiled in; its entry points are no-ops
# (testharness_release.cpp). Off by default: dev builds keep the harness (off unless mxl-testharness.txt exists).
option(MXL_RELEASE "Release build for players: no test harness" OFF)
if(MXL_RELEASE)
	target_sources(mxl_core PRIVATE src/testharness_release.cpp)
	target_compile_definitions(mxl_core PRIVATE MXL_RELEASE=1)
else()
	target_sources(mxl_core PRIVATE src/testharness.cpp src/harness_cmds.cpp)  # test harness and its gameplay commands
endif()
# The DLL's version resource (src/mxl_core.rc) carries PluginVersion of mxl_core.cpp.
file(STRINGS src/mxl_core.cpp plugin_version_line REGEX "PluginVersion = \"[0-9]+[.][0-9]+[.][0-9]+\"")
if(NOT plugin_version_line MATCHES "\"([0-9]+)[.]([0-9]+)[.]([0-9]+)\"")
	message(FATAL_ERROR "PluginVersion not found in src/mxl_core.cpp")
endif()
set_property(SOURCE src/mxl_core.rc APPEND PROPERTY COMPILE_DEFINITIONS
             MXL_PV_STR="${CMAKE_MATCH_1}.${CMAKE_MATCH_2}.${CMAKE_MATCH_3}" MXL_PV_NUM=${CMAKE_MATCH_1},${CMAKE_MATCH_2},${CMAKE_MATCH_3},0)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS src/mxl_core.cpp)
target_link_libraries(mxl_core PRIVATE D2RLPlugin::D2RLPlugin)
set_target_properties(mxl_core PROPERTIES OUTPUT_NAME "mxl-core")
if(MSVC)
	target_compile_options(mxl_core PRIVATE /W4 /permissive- /EHsc /utf-8)
	set_property(TARGET mxl_core PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")  # no VC++ runtime dependency
endif()

# Unit tests for the pure parts (not in the plugin DLL): tests/CMakeLists.txt
add_subdirectory(tests)
