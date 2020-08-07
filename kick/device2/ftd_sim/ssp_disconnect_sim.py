import os

print('Password: ')
in_ = input()

print("""Successful login attempts for user 'admin' : 1
Last login: Tue Apr 23 23:39:12 2019
Cisco Firepower Extensible Operating System (FX-OS) Software
TAC support: http://www.cisco.com/tac
Copyright (c) 2009-2019, Cisco Systems, Inc. All rights reserved.

The copyrights to certain works contained in this software are
owned by other third parties and used and distributed under
license.

Certain components of this software are licensed under the "GNU General Public
License, version 3" provided with ABSOLUTELY NO WARRANTY under the terms of
"GNU General Public License, Version 3", available here:
http://www.gnu.org/licenses/gpl.html. See User Manual (''Licensing'') for
details.

Certain components of this software are licensed under the "GNU General Public
License, version 2" provided with ABSOLUTELY NO WARRANTY under the terms of
"GNU General Public License, version 2", available here:
http://www.gnu.org/licenses/old-licenses/gpl-2.0.html. See User Manual
(''Licensing'') for details.

Certain components of this software are licensed under the "GNU LESSER GENERAL
PUBLIC LICENSE, version 3" provided with ABSOLUTELY NO WARRANTY under the terms
of "GNU LESSER GENERAL PUBLIC LICENSE" Version 3", available here:
http://www.gnu.org/licenses/lgpl.html. See User Manual (''Licensing'') for
details.

Certain components of this software are licensed under the "GNU Lesser General
Public License, version 2.1" provided with ABSOLUTELY NO WARRANTY under the
terms of "GNU Lesser General Public License, version 2", available here:
http://www.gnu.org/licenses/old-licenses/lgpl-2.1.html. See User Manual
(''Licensing'') for details.

Certain components of this software are licensed under the "GNU Library General
Public License, version 2" provided with ABSOLUTELY NO WARRANTY under the terms
of "GNU Library General Public License, version 2", available here:
http://www.gnu.org/licenses/old-licenses/lgpl-2.0.html. See User Manual
(''Licensing'') for details.

""")

in_ = input('ful01-n8-qp4110-1-A# ')
in_ = input('ful01-n8-qp4110-1-A# ')
in_ = input('ful01-n8-qp4110-1-A# ')
in_ = input('ful01-n8-qp4110-1-A# ')
in_ = input('ful01-n8-qp4110-1-A# ')
in_ = input('ful01-n8-qp4110-1-A# ')
in_ = input('ful01-n8-qp4110-1-A# ')
out = """Telnet escape character is '~'.
Trying 127.5.1.1...
Connected to 127.5.1.1.
Escape character is '~'.

CISCO Serial Over LAN:
Close Network Connection to Exit
:"""
if os.path.exists('./disconnected.py'):
    out += "\x07"
try:
    in_ = input(out)
except KeyboardInterrupt:
    pass
if not os.path.exists('./disconnected.py'):
    in_ = input('Firepower-module1>')
in_ = input('Firepower-module1>')
print('Connecting to ftd(ftd1) console... enter exit to return to bootCLI')
try:
    in_ = input('> ')
except KeyboardInterrupt:
    pass
if os.path.exists('./disconnected.py'):
    while True:
        if "exit" in in_:
            print('Disconnected from ftd(ftd1) console!')
            in_ = input('Firepower-module1>')
            if 'connect ftd' in in_:
                in_ = input('> ')
        else:
            break
in_ = input('> ')
in_ = input('admin@firepower:/opt/cisco/csp/applications$ ')
if os.path.exists('./disconnected.py'):
    in_ = input('admin@firepower:/opt/cisco/csp/applications$ ')
if not os.path.exists('./disconnected.py'):
    print('Inactive timeout reached, logging out.\nConnection to 10.12.29.183 closed.')
    open('./disconnected.py', 'w').close()
    exit(0)
