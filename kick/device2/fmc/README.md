----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for device FMC,
which will first get access (Telnet, SSH, etc)
to the FMC console, execute/configure FMC commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Fmc(BasicDevice): A class that extends BasicDevice and also provides various methods such as logs check
* FmcLine(BasicLine): A class that extends BasicDevice and also provides various advanced methods to expert execute
            and sudo execute commands
* FmcStatemachine: Initializer of FtdStateMachine; creates and adds states and paths to different states
* FmcStatements: Creates statements for login password, enable password, sudo password
* FmcPatterns: Initializer of FMC connection
* FmcDialog: Initializer of FMC Dialogs
