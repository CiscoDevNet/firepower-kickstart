----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for device Series3 FMC, which will first get access (Telnet, SSH, etc) to the FMC console, execute/configure Series3 FMC commands, and return outputs. 
Cisco Unicon will be used for interaction between command sending/receiving.
Sub modules/Main Classes included:
Series3Fmc: A class that provides various methods such as ssh to FMC
Series3Line: A class that provides various advanced methods to find matched line or substring from return_data, 
execute a command and verify the output and baseline process for Series3 FMC
