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
Warning: Permanently added '[10.89.16.19]:2011' (RSA) to the list of known hosts.
Password:""")

process_command(1, 'vppuser', """c9300-sm36# """)
process_command(2, '', """c9300-sm36# """)
process_command(3, '', """c9300-sm36# """)
process_command(4, '', """c9300-sm36# """)
process_command(5, 'top', 'c9300-sm36# ')
process_command(6, 'terminal length 0', 'c9300-sm36# ')
process_command(7, 'terminal width 511', 'c9300-sm36# ')
process_command(8, 'connect module 1 console', """Telnet escape character is '~'.
Trying 127.5.1.1...
Connected to 127.5.1.1.
Escape character is '~'.

CISCO Serial Over LAN:
Close Network Connection to Exit
""" + '\a')
process_command(9, '\x15', '', True)
process_command(10, '', '')
process_command(11, '', 'Firepower-module1>')
process_command(12, 'connect ftd', """Connecting to ftd(sensor1) console... enter exit to return to bootCLI


System initialization in progress.  Please stand by.  -/|\-/|\-/|\-/|\-/|
You must change the password for 'admin' to continue.
Enter new password: """)
process_command(13, 'Sourcefire', 'Confirm new password: ')
process_command(14, 'Sourcefire', """Passwords do not match.
Enter new password: """)
process_command(15, 'Sourcefire', 'Confirm new password: ')
process_command(16, 'Sourcefire', """
You must configure the network to continue.
You must configure at least one of IPv4 or IPv6.
Do you want to configure IPv4? (y/n) [y]: y
Do you want to configure IPv6? (y/n) [n]: n
Configure IPv4 via DHCP or manually? (dhcp/manual) [manual]: manual
Enter an IPv4 address for the management interface [192.168.0.151]: 192.168.0.151
Enter an IPv4 netmask for the management interface [255.255.0.0]: 255.255.0.0
Enter the IPv4 default gateway for the management interface [192.168.0.254]: 192.168.0.254
Enter a fully qualified hostname for this system [ftd-36A-151.cisco.com]: ftd-36A-151.cisco.com
Enter a comma-separated list of DNS servers or 'none' [10.83.48.30]: 10.83.48.30
Enter a comma-separated list of search domains or 'none' [cisco.com]: cisco.com
If your networking information has changed, you will need to reconnect.
For HTTP Proxy configuration, run 'configure network http-proxy'

Update policy deployment information
    - add device configuration
> Sourcefire """ + '\a')
process_command(17, '', '> ', True)
process_command(18, 'exit', 'Firepower-module1>')
process_command(19, '~', 'telnet> ')
process_command(20, '"q"', 'c9300-sm36# ')
process_command(21, 'connect module 1 console', """Telnet escape character is '~'.
Trying 127.5.1.1...
Connected to 127.5.1.1.
Escape character is '~'.

CISCO Serial Over LAN:
Close Network Connection to Exit
""" + '\a')
process_command(22, '\x15', '', True)
process_command(23, '', '')
process_command(25, '', 'Firepower-module1>')
process_command(22, 'connect ftd', '> ', True)
