cmake_minimum_required(VERSION 3.14)
project(ReceiptsPlugin LANGUAGES CXX)

if(DEFINED ENV{LOGOS_MODULE_BUILDER_ROOT})
    include($ENV{LOGOS_MODULE_BUILDER_ROOT}/cmake/LogosModule.cmake)
elseif(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/cmake/LogosModule.cmake")
    include(cmake/LogosModule.cmake)
else()
    message(FATAL_ERROR "LogosModule.cmake not found")
endif()

find_package(Qt6 REQUIRED COMPONENTS Sql Network)

logos_module(
    NAME receipts
    SOURCES
        src/receipts_interface.h
        src/receipts_plugin.h
        src/receipts_plugin.cpp
)

target_link_libraries(receipts_module_plugin PRIVATE Qt6::Sql Qt6::Network)
