----------------------------------------------
Module overview:
----------------------------------------------
This module provides operations for device EP,
which will first get access (Telnet, SSH, etc)
to the EP console, execute EP commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Ep(BasicDevice): A class that extends BasicDevice and also provides various methods such as logs check
* EpLine(BasicLine): A class that extends BasicDevice and also provides various advanced methods to expert execute
            and sudo execute commands
* EpStatemachine: Initializer of FtdStateMachine; creates and adds states and paths to different states
* EpStatements: Creates statements for login password, sudo password
* EpPatterns: Initializer of EP connection
* EpDialog: Initializer of EP Dialogs


----------------------------------------------
Module usage example:
----------------------------------------------

----------------------------
1 Import Ep class
----------------------------

```python
from kick.device2.ep.actions import Ep
```
----------------------------
2 Define required parameters (HOSTNAME, USERNAME, PASSWORD, IP, PORT)
----------------------------

```python
HOSTNAME = 'sfuser-virtual-machine'
USERNAME = 'sfuser'
PASSWORD = 'Sourcefire'
IP = '10.88.127.150'
PORT = '11169'
```
----------------------------
3 Instantiate Ep object
----------------------------

```python
ep = Ep(hostname=HOSTNAME,
          login_username=USERNAME,
          login_password=PASSWORD,
          sudo_password=PASSWORD)
```
----------------------------
4 Connect to machine via SSH
----------------------------

```python
dev = ep.ssh_vty(ip=IP, port=PORT, username=USERNAME, password=PASSWORD)
```
----------------------------
5 Execute various commands on machine
----------------------------

```python
# sudo_execute()
r = dev.sudo_execute('date')
print("====={}----".format(r))
# expert_execute()
r = dev.expert_execute('date')
print("====={}----".format(r))
```

----------------------------
6 Disconnect from machine
----------------------------
```python
dev.disconnect()
```
