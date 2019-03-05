----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for general CLI,
which will first get access (Telnet, SSH, etc)
to the console, execute/configure general commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* BasicDevice: A class that provides various console access methods such as Telnet, SSH, timeouts, etc.
* BasicLine: A console class that provides basic functions such as go to specified state,
            run commands and return the output, run a command and get the expected prompt,
            run multiple lines of commands and return the output for all commands,
            go to enable mode and run the command, go to enable mode and run multiple lines of commands,
            go to config mode and send multiple lines of configuration,
            run a command (based on user input as "cmd", and follow up on dialog), perform the scp action and
            disconnect the line
* NewSpawn(pty_backend.Spawn): Override original read function to ignore non utf-8 decode error
* Factory: Provides possibility to identify device by model, name or version:
            '63': Series3,
            '66': Fmc,
            '69': Ftd5500x,
            '72': Elektra,
            '75': Ftd5500x,
            '76': Ssp,
            '77': Kp
* Access: A class that provides various methods such as check device availability, wait for device availability,
            clear console line
* Power Bar: Provides possibility to Telnet to power-bar and perform the specified action:
            name or IP Address of power-bar, port of the device to perform power action, action status(on, off, reboot),
            power-bar credentials
