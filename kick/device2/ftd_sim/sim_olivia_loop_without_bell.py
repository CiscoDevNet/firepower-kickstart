def process_command(command_id, expect, message, fail_if_empty=False):
    try:
        in_ = input()
    except KeyboardInterrupt:
        in_ = ''
    if expect == in_.strip():
        print(message, end="")
    else:
        if not fail_if_empty:
            print('In is: ', in_)
            print('Expect is:', expect)
            raise SystemExit('Failed at command id: {}'.format(command_id))


print("""
Warning: Permanently added '10.12.29.186' (RSA) to the list of known hosts.
Password:""")

process_command(1, 'Admin123', """
Successful login attempts for user 'admin' : 43
Last login: Wed Jun 26 22:17:30 2019 from 10.83.65.41
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

ful01-n8-qp4110-2-A# 
""")
process_command(2, '', 'ful01-n8-qp4110-2-A# ')
process_command(3, '', 'ful01-n8-qp4110-2-A# ')
process_command(4, '', 'ful01-n8-qp4110-2-A# ')
process_command(5, '', 'ful01-n8-qp4110-2-A# ')
process_command(6, '', 'ful01-n8-qp4110-2-A# ')
process_command(7, 'top', 'ful01-n8-qp4110-2-A# ')
process_command(8, 'terminal length 0', 'ful01-n8-qp4110-2-A# ')
process_command(9, 'terminal width 511', 'ful01-n8-qp4110-2-A# ')
process_command(10, 'connect module 1 console', """Telnet escape character is '~'.
Trying 127.5.1.1...
Connected to 127.5.1.1.
Escape character is '~'.

CISCO Serial Over LAN:
Close Network Connection to Exit
""")
process_command(11, '', '', True)
process_command(11, '', 'ful01-n8-qp4110-1> ', True)
process_command(16, 'exit', '> ', True)
process_command(16, 'exit', 'Firepower-module1> ', True)
process_command(16, 'connect ftd', '> ', True)
