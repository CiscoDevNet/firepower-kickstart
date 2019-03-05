----------------------------------------------
Module overview:
----------------------------------------------
This module provides opeartions for legacy ASA CLI,
which will first get access (Telnet, SSH, etc)
to the ASA console, execute/configure ASA commands, and return outputs. Cisco Unicon will be used
for interaction between command sending/receiving.

Sub modules/Main Classes included:

* Asa: An Asa class that provides various console access methods such as Telnet, SSH, etc.
* AsaLine: An ASA console class that provides basic functions such as execute, config, reload,
           changing hostname, changing modes, etc.
* AsaConfig(asa_config.py): Provides detailed ASA configuration related functions such as interfaces, routes,
             access list, access group, class map, policy map, xlate, network object, etc.
             Supported mode including:<br />
             Context mode: single | multi ctx<br />
             Firewall mode: routed | transparent
* AsaCluster(asa_cluster.py): Provides ASA cluster support
* AsaGtpConfig(asa_gtp.py): Provides ASA GTP related support
* AsaDiameterConfig(asa_diameter.py): Provides ASA Diameter related support

----------------------------------------------
Common imports
----------------------------------------------
``` python
""" The following lines should be used before any of the examples below:
"""
from kick.device2.asa.actions import Asa
```

----------------------------------------------
Connect to ASA device:
----------------------------------------------
``` python
def connect_asa():
    """ Here is the process of creating an ASA instance, get access to the console,
        and execute commands. Cisco Unicon statemachine will be used to keep track of
        ASA states including: disable state, enable state, and config state that correspond to
        ASA disable mode, enable mode, config mode.
    """
    from kick.device2.asa.actions import Asa

    # Create an ASA instance given its hostname and enable password
    asa = Asa('ciscoasa', '')

    # Get access to the ASA console through Telnet
    # An instance of AsaLine will be returned
    asa_conn = asa.telnet_console_no_credential('172.23.135.250', 2009)

    # switch states
    from kick.device2.asa.actions.constants import AsaSmStates
    asa_conn.go_to(AsaSmStates.DISABLE_STATE.value)
    asa_conn.go_to(AsaSmStates.ENABLE_STATE.value)

    # Go to enable state and execute a command
    asa_conn.go_to(AsaSmStates.ENABLE_STATE.value)
    show_version = asa_conn.execute('show version')

    # Execute in enable mode. enable_execute will first go to enable state and then
    # run the command
    show_version = asa_conn.enable_execute('show version')

    # Configure something in the box. config function will first go to config state and then
    # execute the command
    asa_conn.config('interface G0/0\nno shutdown')

    ###############################################################################################
    # Note: method enable_execute will always go to enable state first,                           #
    # and method config will always go to config state first                                      #
    # While method execute does not track states                                                  #
    ###############################################################################################

    # Modify hostname
    asa_conn.change_hostname('new_hostname')
    
    # Modify enable password
    original_enable_pwd = asa_conn.sm.patterns.enable_password
    asa_conn.change_enable_password('new_password')

    asa_conn.change_enable_password(original_enable_pwd)

    ###############################################################################################
    # Note: Since changing host name will also result in prompt change that alters patterns in    #
    # statemachine, never use asa_conn.config('hsotname new_hostname')                            #
    # Same for changing enable password. Use 'change_enable_password' instead of 'config'         #
    ###############################################################################################

    # Configure Firewall mode. Available options: 'rfw' | 'tfw'
    # that stands for routed/transparent firewall
    asa_conn.change_firewall_mode('rfw')

    # Configure Context mode. Available options: 'sfm' | 'mfm'
    # that stands for single/multi contexts mode. Changing ctx mode will result in automatic reboot
    asa_conn.change_context_mode('mfm')

    # Reload the ASA
    asa_conn.reload()

    # Disconnect from ASA console
    asa_conn.disconnect()
```

----------------------------------------------
Configure ASA device:
----------------------------------------------
``` python
def configure_asa():
    """ This function shows how to use class AsaConfig for detailed ASA configuration.
        A console access instance created by AsaLine will be passed to sending/receiving commands.
        An ASA config (a munch that is readable by AsaConfig) will also need to be passed
        into AsaConfig
    """
    import munch, yaml
    from kick.device2.asa.actions import Asa, AsaConfig

    # Define ASA config. Below config string will be converted into a munch for AsaConfig
    # to interpret. You can also store your ASA config into a yaml file
    config = '''
	    ASA_5585_20_SRM:
		  mode: standalone
		  cmode: sfm
		  fmode: rfw
		  hostname: spykerbsinglebox
		  enable_password: ''
		  network_object_group:
		    - name: inside1-0
		      hosts:
		        - start_ip: 22.0.0.1
		          count: 10
		    - name: outside1-0
		      hosts:
		        - start_ip: 32.0.0.1
		          count: 10
		  access_list:
		    - access_list: 100
		      action: permit
		      protocol: ip
		      source: any
		      destination: any
		  access_group:
		    - access_list: 100
		      direction: in
		      interface: outside1
		  interfaces:
		    - hardware: TenGigabitEthernet0/8
		      security: 100
		      nameif: inside1
		      ipv4_address: 154.0.0.1
		      ipv4_netmask: 255.255.255.0
		      ipv4_route:
		        - network: 22.0.0.0
		          netmask: 255.255.0.0
		          gateway: 154.0.0.5
		        - network: 22.1.0.0
		          netmask: 255.255.0.0
		          gateway: 154.0.0.6
		      ipv6_address: 1540::1
		      ipv6_prefix: 64
		      ipv6_route:
		        - network: '2200::'
		          prefix: 64
		          gateway: 1540::5
		        - network: '2210::'
		          prefix: 64
		          gateway: 1540::6
		    - hardware: TenGigabitEthernet0/9
		      security: 0
		      nameif: outside1
		      ipv4_address: 174.0.0.1
		      ipv4_netmask: 255.255.255.0
		      ipv4_route:
		        - network: 32.0.0.0
		          netmask: 255.255.0.0
		          gateway: 174.0.0.5
		        - network: 32.1.0.0
		          netmask: 255.255.0.0
		          gateway: 174.0.0.6
		      ipv6_address: 1740::1
		      ipv6_prefix: 64
		      ipv6_route:
		        - network: '3200::'
		          prefix: 64
		          gateway: 1740::5
		        - network: '3210::'
		          prefix: 64
		          gateway: 1740::6
	'''
	topo = munch.munchify(yaml.safe_load(config))
    asa_topo = topo['ASA_5585_20_SRM']

    # Create an ASA instance and get access through Telnet
    asa = Asa(asa_topo.hostname, asa_topo.enable_password)
    asa_conn = asa.telnet_console('172.23.135.250', 2009)

    # Create an AsaConfig instance given the console access and detailed config
    # During the initialization, AsaConfig will set up context/firewall mode,
    # allocate contexts/interfaces, etc. based on given config
    asa_config = AsaConfig(asa_conn, asa_topo)

    # Execute a command
    show_version = asa_config.execute('show version')

    # Configure something
    asa_config.config('interface Gig0/0\nno shutdown')

    ###############################################################################################
    # Note: in AsaConfig, method execute will always run command in enable state                  #
    # and method config will always run command in config state                                   #
    ###############################################################################################

    # Get software version and hardware model
    version, model = asa_config.show_version()

    # Get ASA Cpu usage
    cpu = asa_config.show_cpu()

    # Configure interfaces based on given config in asa_topo
    asa_config.config_intfs()

    # Configure routes based on given config in asa_topo
    asa_config.config_routes()

    # You can also assign new routes to an interface with a customized config out of asa_topo
	asa_config.config_ipv4_route(intf_name='inside1', network='22.2.0.0', netmask='255.255.0.0', \
	    gateway='154.0.0.7')

	# Configure access lists/access groups based on given config in asa_topo
	asa_config.config_access_lists()
	asa_config.config_access_groups()

	# You can also assign new access list/groups with a customized config out of asa_topo
	asa_config.config_access_list(acl_id=11, action='permit', protocol='tcp', src='any', dst='any')

	###############################################################################################
	# Take a closer look at the execute/config functions (also those detailed config functions)   #
	#     def execute(self, cmd, ctx=None, timeout=10)                                            #
	#     def config(self, cmd, ctx=None, timeout=10, exception_on_bad_config=False)              #                                 #                                                                                             #
	# there is always an input arg called 'ctx' which is None by default. This will be used in    #
	# multi contexts mode when you want to execute/config under a particular context. If you want #
	# to execute under system context, the context name will be 'system'. By default it           #
	# will be None for single context mode.                                                       #
	# For example,                                                                                #
	#     asa_config.execute('show conn count', 'ctx1')                                           #
	#     asa_config.config_ipv4_route('inside1', ipv4_routes, 'ctx1')                            #
	# will execute/config commands under context ctx1                                             #
	#                                                                                             #
	# You can also set the timeout to expect the returning prompt after execute/config a command. #
	# By default it's 10 sec.                                                                     #
	###############################################################################################

	###############################################################################################
	# Another example of ASA config in multimode:                                                 #
	# In the sample config below, there will be 2 contexts named 'admin' and 'ctx1'. specify all  #
	# contexts in attribute 'contexts' separated by space. The first context will be always       #
	# regarded as admin context. Due to addition of various contexts, one more layer keyed by     #
	# context names have to be added for each part of config. For instance, in the below sample   #
	# config, access_list will be added based on each context:                                    #
	#     access_list:                                                                            #
	#         admin:                                                                              #
	#             {access list content of context admin}                                          #
	#         ctx1:                                                                               #
	#             {access list content of context ctx1}                                           #
	###############################################################################################
	config = '''
	    ASA_5585_20_MRM:
		  mode: standalone
		  cmode: mfm
		  fmode: rfw
		  hostname: spykerbsinglebox
		  contexts: admin ctx1
		  access_list:
		    admin: &acl1
		      - access_list: 100
		        action: permit
		        protocol: ip
		        source: any
		        destination: any
		    ctx1: *acl1
		  access_group:
		    admin: $acg1
		      - access_list: 100
		        direction: in
		        interface: outside1
		    ctx1: *acg1
		  interfaces:
		    admin:
		      - hardware: TenGigabitEthernet0/8
		        vlan: 101
		        security: 100
		        nameif: inside1
		        ipv4_address: 154.0.0.1
		        ipv4_netmask: 255.255.255.0
		        ipv4_route:
		          - network: 22.0.0.0
		            netmask: 255.255.0.0
		            gateway: 154.0.0.5
		          - network: 22.1.0.0
		            netmask: 255.255.0.0
		            gateway: 154.0.0.6
		        ipv6_address: 1540::1
		        ipv6_prefix: 64
		        ipv6_route:
		          - network: '2200::'
		            prefix: 64
		            gateway: 1540::5
		          - network: '2210::'
		            prefix: 64
		            gateway: 1540::6
		      - hardware: TenGigabitEthernet0/9
		        vlan: 102
		        security: 0
		        nameif: outside1
		        ipv4_address: 174.0.0.1
		        ipv4_netmask: 255.255.255.0
		        ipv4_route:
		          - network: 32.0.0.0
		            netmask: 255.255.0.0
		            gateway: 174.0.0.5
		          - network: 32.1.0.0
		            netmask: 255.255.0.0
		            gateway: 174.0.0.6
		        ipv6_address: 1740::1
		        ipv6_prefix: 64
		        ipv6_route:
		          - network: '3200::'
		            prefix: 64
		            gateway: 1740::5
		          - network: '3210::'
		            prefix: 64
		            gateway: 1740::6
		    ctx1:
		      - hardware: TenGigabitEthernet0/8
		        vlan: 103
		        security: 100
		        nameif: inside1
		        ipv4_address: 155.0.0.1
		        ipv4_netmask: 255.255.255.0
		        ipv4_route:
		          - network: 23.0.0.0
		            netmask: 255.255.0.0
		            gateway: 155.0.0.5
		          - network: 23.1.0.0
		            netmask: 255.255.0.0
		            gateway: 155.0.0.6
		        ipv6_address: 1550::1
		        ipv6_prefix: 64
		        ipv6_route:
		          - network: '2300::'
		            prefix: 64
		            gateway: 1550::5
		          - network: '2310::'
		            prefix: 64
		            gateway: 1550::6
		      - hardware: TenGigabitEthernet0/9
		        vlan: 104
		        security: 0
		        nameif: outside1
		        ipv4_address: 175.0.0.1
		        ipv4_netmask: 255.255.255.0
		        ipv4_route:
		          - network: 33.0.0.0
		            netmask: 255.255.0.0
		            gateway: 175.0.0.5
		          - network: 33.1.0.0
		            netmask: 255.255.0.0
		            gateway: 175.0.0.6
		        ipv6_address: 1750::1
		        ipv6_prefix: 64
		        ipv6_route:
		          - network: '3300::'
		            prefix: 64
		            gateway: 1750::5
		          - network: '3310::'
		            prefix: 64
		            gateway: 1750::6
	'''
```

----------------------------------------------
ASA Cluster:
----------------------------------------------
``` python
def configure_asa_cluster():
    """ This function shows manipulations of an ASA cluster given access of each unit. After the
        cluster master is determined, you can just use AsaConfig for detailed config operations
    """
    from kick.device2.asa.actions import Asa, AsaCluster

    # Create ASA instances of all cluster units given their hostname and enable password
    asa1 = Asa('ciscoasa', '')
    asa2 = Asa('ciscoasa', '')
    asa3 = Asa('ciscoasa', '')
    asa4 = Asa('ciscoasa', '')

    # Get access to the ASA console through Telnet.
    # Instances of AsaLine will be returned
    asa_conn1 = asa.telnet_console('172.23.135.250', 2009)
    asa_conn2 = asa.telnet_console('172.23.135.250', 2010)
    asa_conn3 = asa.telnet_console('172.23.135.250', 2011)
    asa_conn4 = asa.telnet_console('172.23.135.250', 2012)

    asa_conns = [asa_conn1, asa_conn2, asa_conn3, asa_conn4]

    # Create ASA Cluster instance given all console connections and cluster group name
    asa_cluster = AsaCluster(asa_instances=asa_conns, clu_group_name='cluster')

    # Determine master unit and return its corresponding console connection
    asa_master = asa_cluster.pick_up_master()

    ###############################################################################################
    # Note: After the master is determined, you can just use AsaConfig from previous section for  #
    # any config operations, with the master console connection passed into AsaConfig             #
    ###############################################################################################

    # Some other operations in AsaCluster
    # Make a unit to be master. If the unit is already master, do nothing.
    asa_cluster.make_master(asa_conn2)

    # Check if a unit is in cluster. The cluster state should be either MASTER or SLAVE
    # if it's ready
    asa_cluster.is_unit_ready(asa_conn1)

    # Wait until all units are ready in cluster. Wait time is set to 120 sec by default.
    asa_cluster.wait_until_all_units_ready(timeout=180)

    # Disable a unit
    asa_cluster.disable_unit(asa_conn3)

    # Add a unit back to cluster
    asa_cluster.enable_unit(asa_conn3)

    ###############################################################################################
    # Note: During a cluster unit being disabled/enabled, there is a possibility of master change #
    # enable_unit/disable_unit will return the new master unit if that happens.                   #
    # There is also a class attribute AsaCluster.master that keeps track of the master unit       #
    ###############################################################################################
```







