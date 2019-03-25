----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for Elektra device,
which will first get access (Telnet, SSH, etc)
to the Elektra console, execute/configure Elektra commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Elektra: A class that provides methods such as check logs
* ElektraLine: A class that provides various advanced methods such as multi-context support, change to system context,
                find matched line or substring from returned data, execute a command to verify the output,
                set the config if the output is not expected, retry execute command for a counted number of times,
                configure terminal settings, download boot image and set module to downloaded image,
                configure boot parameters, install FTD, configure FTD, baseline Elektra and check version
* ElektraStatemachine: Initializer of SspStateMachine; creates and adds states and paths to different states
* ElektraStatements: Creates statements for login password, enable password, sudo password
* ElektraPatterns: Initializer of Elektra connection
* ElektraDialog: Initializer of Elektra Dialogs
