----------------------------------------------
Module overview:
----------------------------------------------
This module provides opeartions for CSP (Cloud Services Platform) CLI
which will first get access ( SSH )
to the CSP console, execute/configure CSP commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Csp: An Csp class that provides various console access methods such as SSH, etc.
* CspLine: An Csp console class that provides basic functions such as execute. Using this class we can telnet to
           the services (asav or ftdv) deployed on the CSP (Cloud Services platform)

----------------------------------------------
Common imports
----------------------------------------------
``` python
""" The following lines should be used before any of the examples below:
"""
from kick.device2.csp.actions import Csp
```

----------------------------------------------
Connect to CSP device:
----------------------------------------------
``` python
def connect_csp():
    """ Here is the process of creating an CSP instance, get access to the console,
        and execute commands. Cisco Unicon statemachine will be used to keep track of
        CSP states including: enable state, and config state
    """
    from kick.device2.csp.actions import Csp

    # Create an CSP instance given its hostname and enable password
    csp = Csp('perf-csp2100', '')

    # Get access to the CSP console through SSH
    # An instance of CspLine will be returned
    csp_conn =  csp.ssh_console(csp_ip, port=22, username='admin', password='#Ohu8one2', timeout=None)

    # switch states
    from kick.device2.csp.actions.constants import CspSmStates
    csp_conn.go_to(CspSmStates.ENABLE_STATE.value)
    csp_conn.go_to(CspSmStates.CONFIG_STATE.value)

    # Go to enable state and execute a command
    csp_conn.go_to(CspSmStates.ENABLE_STATE.value)
    show_version = csp_conn.execute('show version')

    #To connect to a Virtual ASA deployed on this service
    asav = Asa(asav_hostname)
    asav_conn = asav.connect_from_csp(csp_conn, port=asav_port)











