----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for Series3 device,
which will first get access (Telnet, SSH, etc)
to the Series3 console, execute/configure Series3 commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Series3(BasicDevice): A class that extends BasicDevice and provides methods such as logs check, ssh to device's interface
* Series3Line(BasicLine): A class that also extends BasicDevice and provides various advanced methods to
            execute command in expert state given as string, execute command in sudo state, generate configuration file,
            scp a remote file to DUT, scp bz and usb image files from remote sftp server to DUT, configure lilo file
            on DUT, execute run_lilo_and_depmod, mount usb, reboot to install, confirm device is rebooting by executing
            command pwd, reconnect to the device and process the dialog, poll device and configure, validate installed
            version, Series3 baseline
* Series3Statemachine(StateMachine): Initializer of Series3Statemachine; creates and adds states and paths to different
            states
* Series3Statements: Creates statements for login password
* Series3Patterns: Initializer of Series3 connection
* Series3Dialog: Initializer of Series3 Dialogs
