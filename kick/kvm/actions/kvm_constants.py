import paramiko


class InputConstants(object):
    
    PxeServerParams = {
        'pxe_server_public_ip': {
            'sja': '172.23.47.63',
            'ast': '10.89.23.30',
            'ful': '10.83.65.25',
            'bgl': '10.225.97.93',
        },
        'pxe_server_ip': '192.168.0.50',
        'pxe_server_port': 8080,
        'baseline_vlan': 2998,
        'uut_netmask': '255.255.255.0',
        'dns_server': '171.70.168.183'
    }
    
    ftd_day0_config = {
            '"EULA"': '"accept"',
            '"Hostname"': '"ftdv-production-1"',
            '"AdminPassword"': '"Admin123"',
            '"FirewallMode"': '"routed"',
            '"DNS1"': '"1.1.1.1"',
            '"DNS2"': '"1.1.1.2"',
            '"DNS3"': '""',
            '"IPv4Mode"': '"manual"',
            '"IPv4Addr"': '"192.168.0.22"',
            '"IPv4Mask"': '"255.255.255.0"',
            '"IPv4Gw"': '"192.168.0.254"',
            '"IPv6Mode"': '"disabled"',
            '"IPv6Addr"': '""',
            '"IPv6Mask"': '""',
            '"IPv6Gw"': '""',
            '"FmcIp"': '"10.12.129.20"',
            '"FmcRegKey"': '"1234567"',
            '"FmcNatId"': '""'
    }
    
    ftd1_day0_config = {
            '"EULA"': '"accept"',
            '"Hostname"': '"ftdv-production"',
            '"AdminPassword"': '"Admin123"',
            '"FirewallMode"': '"routed"',
            '"DNS1"': '"1.1.1.1"',
            '"DNS2"': '"1.1.1.2"',
            '"DNS3"': '""',
            '"IPv4Mode"': '"manual"',
            '"IPv4Addr"': '"192.168.0.10"',
            '"IPv4Mask"': '"255.255.255.0"',
            '"IPv4Gw"': '"192.168.0.254"',
            '"IPv6Mode"': '"disabled"',
            '"IPv6Addr"': '""',
            '"IPv6Mask"': '""',
            '"IPv6Gw"': '""',
            '"FmcIp"': '"192.168.0.20"',
            '"FmcRegKey"': '"1234567"',
            '"FmcNatId"': '""'
    }
    
    fmc_day0_config = {
            '"EULA"': '"accept"',
            '"Hostname"': '"fmcv-production"',
            '"AdminPassword"': '"Admin123"',
            '"FirewallMode"': '"routed"',
            '"DNS1"': '"1.1.1.1"',
            '"DNS2"': '"1.1.1.2"',
            '"DNS3"': '""',
            '"IPv4Mode"': '"manual"',
            '"IPv4Addr"': '"192.168.0.20"',
            '"IPv4Mask"': '"255.255.255.0"',
            '"IPv4Gw"': '"192.168.0.254"',
            '"IPv6Mode"': '"disabled"',
            '"IPv6Addr"': '""',
            '"IPv6Mask"': '""',
            '"IPv6Gw"': '""',
        }
    
    
def find_file_on_pxe(cmd, hostname, username, password, port=22):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=hostname, port=port, username=username,
                password=password)
    stdin, stdout, stderr = ssh.exec_command(cmd)
    result = stdout.readlines()
    assert len(result) == 1, "should find only one file in cmd: {}, "\
        "but got: {}".format(cmd, result)

    ssh.close()
    return result[0].strip()


