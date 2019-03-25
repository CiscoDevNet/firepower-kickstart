----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for device Kp,
which will first get access (Telnet, SSH, etc)
to the Kp console, execute/configure Kp commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Kp(BasicDevice): A class that extends BasicDevice and provides methods such as check logs, get logs
* KpLine(BasicLine): A class that also extends BasicDevice and provides various advanced methods to
            initialize terminal size, disconnect device, take a list of expect/send actions and perform them one by one,
            wait until the device is on, reboots a device from a Power Data Unit equipment, get packages currently
            downloaded to the box, get the status of download, wait until download completes, download ftd package,
            check fp2k package, format disk and go to ROMMON mode, set network configurations in ROMMON mode,
            send tftpdnld command in rommon mode, format disk and install integrated fxos build in rommon mode,
            upgrade the ftd package and configure device, baseline device from tftp server
* KpStatemachine: Initializer of KpStatemachine; creates and adds states and paths to different states
* KpStatements: Creates statements for login password
* KpPatterns: Initializer of Kp connection
* KpDialog: Initializer of Kp Dialogs
