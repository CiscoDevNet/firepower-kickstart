----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for Ssp device,
which will first get access (Telnet, SSH, etc)
to the Ssp console, execute/configure Ssp commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Ssp(BasicDevice): A class that extends BasicDevice and provides methods such as check logs, get logs
* SspLine(BasicLine): A class that also extends BasicDevice and provides various advanced methods to
            initialize terminal size, wait until the device is on, reboots a device from a Power Data Unit equipment,
            get the status of download image, wait until download completes, bundle check on chasis,
            get packages currently downloaded on the box, download image of FXOS, download image of application for
            QP and BS, show firmware Monitor, parse firmware monitor, get the list of logical device objects Scope,
            get the list of application instance objects, get the list of equipped slot list,
            get the list of application objects Scope, get operational state for slot_id, check if the slot of
            slot_id is online, wait till module of slot_id is Online, check whether the application instance is Enabled
            and Online, delete all logical devices, delete all application instances, get bundle package version from
            the bundle package name, wait until app instance ready, create an instance of application,
            create app-instance for each slot, Delete application instance, delete logical device and app instance
            by slot_id for standalone mode, assign port-type to data for all interfaces, check whether the bundle
            package is installed successfully, wait until the bundle package is installed successfully,
            upgrade bundle package, monitor installation, baseline function for fxos and application installation,
* SspStateMachine(StateMachine): An SSP class that restores all states
* SspStatements: Creates statements for login password
* SspPatterns: SSP class that restores all prompt patterns
* SspDialog: Initializer of Ssp Dialogs
