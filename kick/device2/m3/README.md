----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for device FMC M3,
which will first get access (Telnet, SSH, etc)
to the FMC console, execute/configure FMC M3 commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* M3: A class that provides various methods such as ssh to FMC M3 via CIMC Interface
* M3Line: A class that provides various advanced methods to find matched line or substring from return_data,
            execute a command and verify the output and baseline process for FMC M3
* M3Statemachine: Initializer of M3Statemachine; creates and adds states and paths to different states
* M3Statements: Creates statements for login password
* M3Patterns: Initializer of M3 connection
* M3Dialog: Initializer of M3 Dialogs
