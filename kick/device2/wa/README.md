----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for WA (Warick Avenue) device, most of which is provided from the KP (Kilburn Park) device class. 

Similar to the KP device class, this module: 
* Gets access (Telnet, SSH) to the WA console
* Executes/configures Wa commands
* Returns output from commands
* Uses Cisco's Unicon library for sending/receiving commands 

The reason this works is that Warwick Avenue as a product itself is built as an extension of KP. Therefore, most of the commands, configurations, and logic are the same. However, there does exist a few differences between the platforms (e.g. bundle names, console feedback, etc). This module addresses those issues by overriding methods where needed.

Sub modules/Main Classes included:

* Wa(Kp): A class that extends Kp device class. Utilizes the WaLine 
* WaLine(KpLine): A class that extends KpLine class. Overrides subset of KpLine functions to support Warick Avenue
* Other KP Classes are implicitly inherited and can be found in KP module documentation

