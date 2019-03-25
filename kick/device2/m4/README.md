----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for device FMC M4,
which will first get access (Telnet, SSH, etc)
to the FMC console, execute/configure FMC M4 commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* M4: A class that provides various methods such as ssh to FMC M4 via CIMC Interface
* M4Line: A class that provides various advanced methods to find matched line or substring from return_data,
            execute a command and verify the output and baseline process for FMC M4
* M4Statemachine: Initializer of M4Statemachine; creates and adds states and paths to different states
* M4Statements: Creates statements for login password
* M4Patterns: Initializer of M4 connection
* M4Dialog: Initializer of M4 Dialogs
