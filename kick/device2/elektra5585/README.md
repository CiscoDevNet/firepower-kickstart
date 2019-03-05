Module overview:
----------------------------------------------
This module provides operations for device Elektra 5585 SFR,
which will first get access (Telnet, SSH, etc)
to the console, execute/configure commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Electra5585(BasicDevice): A class that extends BasicDevice and also provides various methods such as clear line,
                check version, check logs
* Elektra5585Line(BasicLine): A class that extends BasicDevice and also provides various advanced methods to expert
                execute commands, sudo execute, wait for device to be on, perform power cycle, send actions one by one,
                go to rommon mode, boot and configure rommon, configure firepower boot parameters,
                install firepower and check version
* Elektra5585Statemachine: Initializer of Elektra5585StateMachine; creates and adds states and paths to different states
* Elektra5585Statements: Creates statements for login password, enable password, sudo password
* Elektra5585Patterns: Initializer of Elektra55855500x connection
* Elektra5585Dialog: Initializer of Elektra5585 Dialogs
