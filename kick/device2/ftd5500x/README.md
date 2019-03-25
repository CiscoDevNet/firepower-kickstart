----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for device FTD 5500x,
which will first get access (Telnet, SSH, etc)
to the FTD console, execute/configure FTD commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Ftd5500x(BasicDevice): A class that extends BasicDevice and also provides various methods such as clear line,
                check version, check logs
* Ftd5500xLine(BasicLine): A class that extends BasicDevice and also provides various advanced methods to expert
                execute commands, sudo execute, wait for device to be on, perform power cycle, send actions one by one,
                go to rommon mode, boot and configure rommon, configure firepower boot parameters,
                install firepower and check version
* Ftd5500xStatemachine: Initializer of FtdStateMachine; creates and adds states and paths to different states
* Ftd5500xStatements: Creates statements for login password, enable password, sudo password
* Ftd5500xPatterns: Initializer of Ftd5500x connection
* Ftd5500xDialog: Initializer of Ftd5500x Dialogs
